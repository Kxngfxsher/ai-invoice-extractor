import io

from openpyxl import load_workbook

from app.config import SAMPLES_DIR
from app.export import safe_text


def by_file(client) -> dict[str, dict]:
    return {doc["filename"]: doc for doc in client.get("/api/documents").json()}


def test_demo_is_seeded(client):
    docs = by_file(client)
    assert len(docs) == 5
    assert docs["01_schet_stroymarket.pdf"]["status"] == "approved"
    assert docs["04_schet_error_sum.pdf"]["verdict"] == "attention"
    assert docs["06_schet_new_bank.pdf"]["verdict"] == "attention"
    stats = client.get("/api/stats").json()
    assert stats["total"] == 5 and stats["approved"] == 3 and stats["waiting"] == 2 and stats["attention"] == 2
    assert stats["approved_sum"] == 45_720.00 + 19_400.00 + 75_150.00
    assert stats["untouched_rate"] == 1.0
    assert stats["problems_found"] == 2
    config = client.get("/api/config").json()
    assert config["engine"] == "rules" and config["company"] == "ООО «Северный Двор»"


def test_samples_typo_and_duplicate(client):
    samples = {sample["file"]: sample for sample in client.get("/api/samples").json()}
    assert samples["01_schet_stroymarket.pdf"]["loaded"] and not samples["05_schet_bad_inn.pdf"]["loaded"]
    assert samples["h1_schet_poligraf.pdf"]["known_layout"] is False

    typo = client.post("/api/samples/05_schet_bad_inn.pdf")
    assert typo.status_code == 201
    assert [(issue["level"], issue["field"]) for issue in typo.json()["issues"]] == [("error", "seller.inn")]

    duplicate = client.post("/api/samples/08_schet_duplicate.pdf").json()
    assert duplicate["verdict"] == "check"
    assert "дубль" in duplicate["issues"][0]["message"]
    assert client.post("/api/samples/..%2Fsecret.pdf").status_code == 404


def test_operator_fixes_total_then_approves_and_exports(client):
    doc = by_file(client)["04_schet_error_sum.pdf"]
    data = doc["data"]
    data["total"] = 44_800.00
    data["vat_amount"] = 7_466.67
    fixed = client.put(f"/api/documents/{doc['id']}", json=data).json()
    assert fixed["verdict"] == "ready" and fixed["edited"] is True
    assert [issue["level"] for issue in fixed["issues"]] == ["info"]  # поставщика нет в справочнике

    approved = client.post(f"/api/documents/{doc['id']}/approve").json()
    assert approved["status"] == "approved"
    assert client.put(f"/api/documents/{doc['id']}", json=data).status_code == 409
    assert client.post(f"/api/documents/{doc['id']}/reject").status_code == 409
    assert client.get("/api/stats").json()["untouched_rate"] == 0.75

    workbook = load_workbook(io.BytesIO(client.get("/api/export.xlsx").content))
    documents, items = workbook["Документы"], workbook["Позиции"]
    assert documents.max_row == 5 and documents["A1"].value == "Вид"
    rows = {row[1]: row for row in documents.iter_rows(min_row=2, values_only=True)}
    assert rows["ТК-778"][8] == 44_800.00
    assert rows["СМ-1482"][4] == "0012345673"  # ИНН остаётся текстом, ведущие нули не теряются
    assert rows["СМ-1482"][14] == "40702810300000001482"
    assert items.max_row == 1 + 4 + 3 + 3 + 3

    csv_bytes = client.get("/api/export.csv").content
    assert csv_bytes.startswith(b"\xef\xbb\xbf") and "ТК-778".encode() in csv_bytes
    exported = client.get("/api/export.json", params={"scope": "all"}).json()
    assert len(exported) == 5 and exported[0]["number"] == "СМ-1482"

    reopened = client.post(f"/api/documents/{doc['id']}/reopen").json()
    assert reopened["status"] == "new" and reopened["decided_at"] is None


def test_upload_preview_and_bad_files(client):
    content = (SAMPLES_DIR / "07_akt_uslugi.pdf").read_bytes()
    uploaded = client.post("/api/documents", files={"file": ("..\\..\\акт <октябрь>.pdf", content, "application/pdf")})
    assert uploaded.status_code == 201
    doc = uploaded.json()
    assert doc["filename"] == "акт октябрь.pdf"  # путь и служебные символы отброшены
    assert doc["doc_type_label"] == "Акт" and doc["verdict"] == "ready"

    preview = client.get(f"/api/documents/{doc['id']}/preview")
    assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")

    assert client.post("/api/documents", files={"file": ("virus.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")}).status_code == 422
    scan = client.post("/api/documents", files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")})
    assert scan.status_code == 422 and "Claude" in scan.json()["detail"]
    assert client.get("/api/documents/999").status_code == 404
    assert client.post(f"/api/documents/{doc['id']}/explode").status_code == 404
    assert client.get("/").status_code == 200


def test_reset_restores_demo(client):
    client.post("/api/samples/05_schet_bad_inn.pdf")
    assert client.post("/api/demo/reset").json() == {"seeded": 5}
    assert client.get("/api/stats").json()["total"] == 5


def test_spreadsheet_formula_injection_is_neutralized():
    assert safe_text("=HYPERLINK(\"http://evil.example\")") == "'=HYPERLINK(\"http://evil.example\")"
    assert safe_text("+7 900 000-00-00") == "'+7 900 000-00-00"
    assert safe_text("ООО «Ромашка»") == "ООО «Ромашка»"
    assert safe_text(45_720.0) == 45_720.0

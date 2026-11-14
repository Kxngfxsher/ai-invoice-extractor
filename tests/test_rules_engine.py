import pytest

from app.config import SAMPLES_DIR
from app.engines import Document, EngineError
from app.engines.rules import RulesEngine, parse_number
from app.schemas import normalize
from tests.conftest import reference

DEV_FILES = [
    "01_schet_stroymarket.pdf",
    "02_schet_kanctovary.pdf",
    "03_schet_it_uslugi.pdf",
    "04_schet_error_sum.pdf",
    "05_schet_bad_inn.pdf",
    "06_schet_new_bank.pdf",
    "07_akt_uslugi.pdf",
    "08_schet_duplicate.pdf",
]


@pytest.mark.parametrize("filename", DEV_FILES)
def test_known_layouts_are_extracted_exactly(filename, expected, company):
    """Регрессия: на знакомых макетах разбор обязан совпадать с эталоном до последнего поля."""
    data, meta = RulesEngine(company).extract(Document(SAMPLES_DIR / filename, "pdf", filename))
    assert normalize(data) == reference(expected[filename])
    assert meta.engine == "rules"


def test_printed_values_are_not_corrected(expected, company):
    """Движок переписывает документ как есть: ошибку в итоге должна найти проверка, а не скрыть разбор."""
    data, _ = RulesEngine(company).extract(Document(SAMPLES_DIR / "04_schet_error_sum.pdf", "pdf", "x.pdf"))
    assert data.total == 45_800.00
    assert round(sum(item.amount for item in data.items), 2) == 44_800.00


def test_images_and_scans_are_rejected_with_clear_reason(tmp_path, company):
    engine = RulesEngine(company)
    with pytest.raises(EngineError, match="Claude"):
        engine.extract(Document(tmp_path / "scan.png", "png", "scan.png"))
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(EngineError):
        engine.extract(Document(broken, "pdf", "broken.pdf"))


@pytest.mark.parametrize("cell, value", [("18 600,00", 18600.0), ("98,50", 98.5), ("120", 120.0), ("—", None), (None, None)])
def test_parse_number(cell, value):
    assert parse_number(cell) == value

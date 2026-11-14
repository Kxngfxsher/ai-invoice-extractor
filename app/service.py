"""Сценарии работы с документами: загрузка, извлечение, проверка, правка, решение, выгрузка."""

import hashlib
import json
import re
from pathlib import Path

from .config import MAX_UPLOAD_BYTES, SAMPLES_DIR, Settings, load_company, load_counterparties
from .db import Store
from .engines import Document, EngineError, build_engine
from .engines.rules import RulesEngine
from .pdfio import render_preview, sniff
from .schemas import DOC_TYPE_LABELS, InvoiceData, normalize
from .validation import validate, verdict

EXTENSIONS = {"pdf": "pdf", "png": "png", "jpeg": "jpg"}
SEED_FILES = ["01_schet_stroymarket.pdf", "02_schet_kanctovary.pdf", "03_schet_it_uslugi.pdf", "04_schet_error_sum.pdf", "06_schet_new_bank.pdf"]
SEED_APPROVED = SEED_FILES[:3]


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    pass


def safe_filename(name: str) -> str:
    """Имя файла приходит от пользователя: оставляем только последнюю часть пути без служебных символов."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f<>:\"|?*]", "", base).strip()
    return base[:120] or "document"


class InvoiceService:
    def __init__(self, settings: Settings, engine=None):
        self.settings = settings
        self.company = load_company()
        self.counterparties = load_counterparties()
        self.store = Store(settings.db_path)
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.rules = RulesEngine(self.company)
        self.engine_error: str | None = None
        if engine is None:
            engine = self.rules
            if settings.engine == "claude":
                try:
                    engine = build_engine("claude", self.company, settings.model, settings.effort)
                except Exception as exc:  # нет SDK или ключа: демо продолжает работать на правилах
                    self.engine_error = f"{type(exc).__name__}: {exc}"
        self.engine = engine

    # --- чтение ------------------------------------------------------------------------------

    def get(self, doc_id: int) -> dict:
        row = self.store.get(doc_id)
        if row is None:
            raise NotFound(f"Документ {doc_id} не найден")
        return self._decorate(row)

    def list(self) -> list[dict]:
        return [self._decorate(row) for row in self.store.all()]

    def stats(self) -> dict:
        rows = self.store.all()
        approved = [row for row in rows if row["status"] == "approved"]
        waiting = [row for row in rows if row["status"] == "new"]
        problems = sum(issue["level"] in ("error", "warning") for row in rows for issue in row["issues"])
        fields = sum(self._field_count(row["original"]) for row in rows)
        return {
            "total": len(rows),
            "waiting": len(waiting),
            "attention": sum(row["verdict"] == "attention" for row in waiting),
            "approved": len(approved),
            "approved_sum": round(sum(row["total"] or 0 for row in approved), 2),
            "untouched_rate": round(sum(not row["edited"] for row in approved) / len(approved), 2) if approved else None,
            "problems_found": problems,
            "fields_extracted": fields,
            "time_saved_minutes": round(len(rows) * self.settings.manual_minutes_per_document),
            "manual_minutes_per_document": self.settings.manual_minutes_per_document,
            "llm_cost_usd": round(sum(row["meta"].get("cost_usd") or 0 for row in rows), 4),
        }

    def samples(self) -> list[dict]:
        """Готовые примеры документов для демонстрации."""
        expected = json.loads((SAMPLES_DIR / "expected.json").read_text(encoding="utf-8"))
        loaded = self.store.hashes()
        return [
            {
                "file": name,
                "title": entry["title"],
                "known_layout": entry["set"] == "dev",
                "loaded": hashlib.sha256((SAMPLES_DIR / name).read_bytes()).hexdigest() in loaded,
            }
            for name, entry in expected.items()
        ]

    def preview_path(self, doc_id: int) -> Path:
        """Картинка первой страницы. Для PDF рисуется один раз и кладётся рядом с файлом."""
        row = self.get(doc_id)
        source = self.settings.uploads_dir / row["stored_name"]
        if row["kind"] != "pdf":
            return source
        target = source.with_suffix(".preview.png")
        if not target.exists():
            render_preview(source, target)
        return target

    # --- действия ----------------------------------------------------------------------------

    def process(self, filename: str, content: bytes, force_rules: bool = False) -> dict:
        """Принимает файл: сохраняет, извлекает данные, проверяет и создаёт запись."""
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("Файл больше 10 МБ")
        kind = sniff(content)
        if kind is None:
            raise ValueError("Поддерживаются файлы PDF, PNG и JPG")
        sha256 = hashlib.sha256(content).hexdigest()
        stored_name = f"{sha256[:20]}.{EXTENSIONS[kind]}"
        path = self.settings.uploads_dir / stored_name
        path.write_bytes(content)
        filename = safe_filename(filename)

        data, meta = self._extract(Document(path, kind, filename), force_rules)
        data = normalize(data)
        issues = self._validate(data, exclude_id=None)
        doc_id = self.store.insert(
            filename=filename,
            stored_name=stored_name,
            kind=kind,
            sha256=sha256,
            data=data.model_dump(),
            issues=[issue.model_dump() for issue in issues],
            verdict=verdict(issues),
            meta=meta.model_dump(),
        )
        return self.get(doc_id)

    def load_sample(self, name: str) -> dict:
        allowed = {sample["file"] for sample in self.samples()}
        if name not in allowed:
            raise NotFound("Такого примера нет")
        return self.process(name, (SAMPLES_DIR / name).read_bytes())

    def update(self, doc_id: int, data: InvoiceData) -> dict:
        """Оператор поправил поля: данные проверяются заново."""
        row = self.store.get(doc_id)  # «сырая» запись: нужен original для подсчёта правок
        if row is None:
            raise NotFound(f"Документ {doc_id} не найден")
        if row["status"] != "new":
            raise Conflict("Документ уже обработан. Верните его в работу, чтобы изменить")
        data = normalize(data)
        issues = self._validate(data, exclude_id=doc_id)
        dumped = data.model_dump()
        self.store.update_data(
            doc_id, dumped, [issue.model_dump() for issue in issues], verdict(issues), edited=dumped != row["original"]
        )
        return self.get(doc_id)

    def decide(self, doc_id: int, status: str) -> dict:
        row = self.get(doc_id)
        if status != "new" and row["status"] != "new":
            raise Conflict("Решение по документу уже принято")
        self.store.set_status(doc_id, status)
        return self.get(doc_id)

    def export_rows(self, scope: str = "approved") -> list[dict]:
        rows = self.store.all()
        if scope == "approved":
            rows = [row for row in rows if row["status"] == "approved"]
        return list(reversed(rows))

    # --- демо --------------------------------------------------------------------------------

    def seed(self) -> int:
        """Очищает базу и загружает несколько примеров, часть из них уже подтверждена."""
        self.store.clear()
        for path in self.settings.uploads_dir.glob("*"):
            if path.is_file():
                path.unlink()
        for name in SEED_FILES:
            doc = self.process(name, (SAMPLES_DIR / name).read_bytes(), force_rules=not self.settings.seed_with_llm)
            if name in SEED_APPROVED:
                self.store.set_status(doc["id"], "approved")
        return len(SEED_FILES)

    # --- внутреннее --------------------------------------------------------------------------

    def _extract(self, document: Document, force_rules: bool):
        engine = self.rules if force_rules else self.engine
        try:
            return engine.extract(document)
        except EngineError as exc:
            if engine is self.rules:
                raise ValueError(f"Не удалось распознать документ: {exc}") from exc
            try:
                data, meta = self.rules.extract(document)
            except EngineError as fallback_exc:
                raise ValueError(f"Не удалось распознать документ: {exc}; резервный разбор: {fallback_exc}") from exc
            meta.note = f"LLM недоступна ({exc}); документ разобран правилами"
            return data, meta

    def _validate(self, data: InvoiceData, exclude_id: int | None):
        duplicates = self.store.find_duplicates(data.seller.inn, data.number, data.date, exclude_id)
        return validate(
            data,
            own_inn=self.company.get("inn"),
            counterparties=self.counterparties,
            duplicates=duplicates,
        )

    @staticmethod
    def _field_count(data: dict) -> int:
        """Сколько значений движок извлёк из документа (для показателя на панели)."""
        count = sum(data[key] is not None for key in ("number", "date", "total", "vat_rate", "vat_amount", "basis")) + 1
        for group in ("seller", "buyer", "bank"):
            count += sum(value is not None for value in data[group].values())
        for item in data["items"]:
            count += sum(value is not None for value in item.values())
        return count

    @staticmethod
    def _decorate(row: dict) -> dict:
        row["doc_type_label"] = DOC_TYPE_LABELS.get(row["data"]["doc_type"], "Документ")
        row.pop("original", None)
        return row

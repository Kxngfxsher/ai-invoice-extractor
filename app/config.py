"""Настройки приложения: переменные окружения и необязательный файл .env."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SAMPLES_DIR = BASE_DIR / "samples"
DEFAULT_MODEL = "claude-opus-5-5"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env (KEY=VALUE). Уже заданные переменные не перезаписывает."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    engine: str  # фактический движок: rules | claude
    engine_requested: str
    model: str
    effort: str
    var_dir: Path  # база данных и загруженные файлы
    demo_mode: bool
    seed_with_llm: bool
    manual_minutes_per_document: float

    @property
    def db_path(self) -> Path:
        return self.var_dir / "invoices.db"

    @property
    def uploads_dir(self) -> Path:
        return self.var_dir / "uploads"


def get_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    requested = os.getenv("ENGINE", "auto").strip().lower()
    if requested not in ("auto", "rules", "claude"):
        requested = "auto"
    has_credentials = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    engine = requested if requested != "auto" else ("claude" if has_credentials else "rules")
    return Settings(
        engine=engine,
        engine_requested=requested,
        model=os.getenv("CLAUDE_MODEL", DEFAULT_MODEL).strip(),
        effort=os.getenv("CLAUDE_EFFORT", "medium").strip().lower(),
        var_dir=Path(os.getenv("INVOICE_VAR_DIR", str(BASE_DIR / "var"))),
        demo_mode=_flag("DEMO_MODE", True),
        seed_with_llm=_flag("SEED_WITH_LLM", False),
        manual_minutes_per_document=float(os.getenv("MANUAL_MINUTES_PER_DOCUMENT", "5")),
    )


def load_company() -> dict:
    """Наша организация: покупатель в обрабатываемых документах."""
    return json.loads((DATA_DIR / "company.json").read_text(encoding="utf-8"))


def load_counterparties() -> list[dict]:
    """Справочник знакомых поставщиков с проверенными банковскими реквизитами."""
    return json.loads((DATA_DIR / "counterparties.json").read_text(encoding="utf-8"))

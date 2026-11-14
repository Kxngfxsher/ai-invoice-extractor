import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import SAMPLES_DIR, Settings, load_company, load_counterparties  # noqa: E402
from app.schemas import InvoiceData, normalize  # noqa: E402

EMPTY_BANK = {"bank_name": None, "bik": None, "account": None, "corr_account": None}


def make_settings(var_dir: Path, **overrides) -> Settings:
    values = dict(
        engine="rules",
        engine_requested="rules",
        model="claude-opus-5-5",
        effort="medium",
        var_dir=var_dir,
        demo_mode=True,
        seed_with_llm=False,
        manual_minutes_per_document=5.0,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path / "var")


@pytest.fixture
def company() -> dict:
    return load_company()


@pytest.fixture
def counterparties() -> list[dict]:
    return load_counterparties()


@pytest.fixture(scope="session")
def expected() -> dict[str, dict]:
    """Эталон: данные, из которых генератор печатал PDF-примеры."""
    return json.loads((SAMPLES_DIR / "expected.json").read_text(encoding="utf-8"))


def reference(entry: dict) -> InvoiceData:
    data = dict(entry["data"])
    if data["bank"] is None:
        data["bank"] = EMPTY_BANK
    return normalize(InvoiceData.model_validate(data))


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings)) as test_client:
        yield test_client

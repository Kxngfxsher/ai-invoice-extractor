"""Проверка интеграции с SDK Anthropic без сети: HTTP-транспорт подменён заглушкой.

Тесты подтверждают, что документ уходит в запрос как PDF или изображение, что ответ по схеме
превращается в InvoiceData, а ошибки API приводят к резервному разбору правилами.
Реальный вызов API они не заменяют: его проверяет scripts/evaluate.py --engine claude.
"""

import base64
import json

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from app.config import SAMPLES_DIR  # noqa: E402
from app.engines import Document, EngineError  # noqa: E402
from app.engines.claude import FALLBACK_BETA, ClaudeEngine  # noqa: E402
from app.service import InvoiceService  # noqa: E402
from tests.conftest import reference  # noqa: E402

SAMPLE = "01_schet_stroymarket.pdf"


def api_response(payload: dict, model: str = "claude-opus-5-5", stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 2400, "output_tokens": 700, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    }


def make_engine(company, handler, model: str = "claude-opus-5-5") -> ClaudeEngine:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return ClaudeEngine(company, model=model, effort="medium", client=client)


def test_pdf_is_sent_as_document_and_answer_is_parsed(company, expected):
    payload = expected[SAMPLE]["data"]
    captured = []

    def handler(request):
        captured.append(request)
        return httpx2.Response(200, json=api_response(payload))

    data, meta = make_engine(company, handler).extract(Document(SAMPLES_DIR / SAMPLE, "pdf", SAMPLE))

    body = json.loads(captured[0].content)
    document, prompt = body["messages"][0]["content"]
    assert document["type"] == "document"
    assert document["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(document["source"]["data"]) == (SAMPLES_DIR / SAMPLE).read_bytes()
    assert prompt["type"] == "text"
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert FALLBACK_BETA in captured[0].headers["anthropic-beta"]
    assert body["output_config"]["effort"] == "medium"
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert {"seller", "buyer", "bank", "items", "total"} <= set(schema["required"])
    assert "ООО «Северный Двор»" in body["system"][0]["text"]

    assert data.seller.inn == payload["seller"]["inn"] and len(data.items) == 4
    assert meta.model == "claude-opus-5-5"
    assert meta.cost_usd == pytest.approx((2400 * 4 + 700 * 20) / 1_000_000)


def test_photo_is_sent_as_image(company, expected, tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 32)
    captured = []

    def handler(request):
        captured.append(request)
        return httpx2.Response(200, json=api_response(expected[SAMPLE]["data"], model="claude-haiku-5-5"))

    make_engine(company, handler, model="claude-haiku-5-5").extract(Document(photo, "jpeg", "photo.jpg"))
    body = json.loads(captured[0].content)
    block = body["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"
    assert "fallbacks" not in body


def test_refusal_and_api_errors_raise_engine_error(company):
    refusal = make_engine(company, lambda request: httpx2.Response(200, json={**api_response({}), "stop_reason": "refusal"}))
    with pytest.raises(EngineError):
        refusal.extract(Document(SAMPLES_DIR / SAMPLE, "pdf", SAMPLE))

    def overloaded(request):
        return httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})

    with pytest.raises(EngineError, match="ошибка API 529"):
        make_engine(company, overloaded).extract(Document(SAMPLES_DIR / SAMPLE, "pdf", SAMPLE))


def test_service_falls_back_to_rules_and_still_validates(settings, company, expected):
    def unavailable(request):
        raise httpx2.ConnectError("no route", request=request)

    service = InvoiceService(settings, engine=make_engine(company, unavailable))
    doc = service.process(SAMPLE, (SAMPLES_DIR / SAMPLE).read_bytes())
    assert doc["meta"]["engine"] == "rules"
    assert "нет связи с API" in doc["meta"]["note"]
    assert doc["data"] == reference(expected[SAMPLE]).model_dump()
    assert doc["verdict"] == "ready"


def test_llm_digit_error_is_caught_by_checks(settings, company, expected):
    """Если модель ошибётся в одной цифре счёта, документ не пройдёт как «готовый»."""
    payload = json.loads(json.dumps(expected[SAMPLE]["data"]))
    account = payload["bank"]["account"]
    payload["bank"]["account"] = account[:-1] + str((int(account[-1]) + 1) % 10)
    service = InvoiceService(settings, engine=make_engine(company, lambda request: httpx2.Response(200, json=api_response(payload))))
    doc = service.process(SAMPLE, (SAMPLES_DIR / SAMPLE).read_bytes())
    assert doc["meta"]["engine"] == "claude" and doc["verdict"] == "attention"
    assert any(issue["field"] == "bank.account" and issue["level"] == "error" for issue in doc["issues"])

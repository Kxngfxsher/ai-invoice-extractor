"""Оценка качества извлечения на документах с известным эталоном.

    python scripts/evaluate.py                    # движок правил
    python scripts/evaluate.py --engine claude    # Claude: нужен ANTHROPIC_API_KEY, запросы платные

Наборы:
  dev      8 документов в трёх макетах, под которые писались правила разбора;
  holdout  3 документа в двух макетах, которых правила «не видели». Это честная проверка.

Эталон лежит в samples/expected.json: это данные, из которых генератор печатал PDF.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import SAMPLES_DIR, get_settings, load_company  # noqa: E402
from app.engines import Document, EngineError, build_engine  # noqa: E402
from app.schemas import InvoiceData, normalize  # noqa: E402

GROUPS = {
    "Шапка (вид, номер, дата, основание)": ["doc_type", "number", "date", "basis"],
    "Стороны (название, ИНН, КПП)": ["seller.name", "seller.inn", "seller.kpp", "buyer.name", "buyer.inn", "buyer.kpp"],
    "Банк (название, БИК, счета)": ["bank.bank_name", "bank.bik", "bank.account", "bank.corr_account"],
    "Итоги (сумма, ставка и сумма НДС)": ["total", "vat_rate", "vat_amount"],
}
ITEM_FIELDS = ["name", "quantity", "unit", "price", "amount"]


def canon(value):
    if isinstance(value, str):
        return " ".join(value.lower().replace("ё", "е").split())
    if isinstance(value, float):
        return round(value, 2)
    return value


def get(data: dict, path: str):
    for part in path.split("."):
        data = (data or {}).get(part)
    return data


def compare(expected: dict, actual: dict) -> dict[str, tuple[int, int]]:
    """Возвращает по каждой группе полей пару (верно, всего)."""
    result: dict[str, tuple[int, int]] = {}
    if expected.get("bank") is None:  # в акте банковских реквизитов нет: ожидаем пустые поля
        expected = {**expected, "bank": {"bank_name": None, "bik": None, "account": None, "corr_account": None}}
    for group, fields in GROUPS.items():
        hits = sum(canon(get(expected, field)) == canon(get(actual, field)) for field in fields)
        result[group] = (hits, len(fields))
    hits = total = 0
    for index, item in enumerate(expected["items"]):
        got = actual["items"][index] if index < len(actual["items"]) else {}
        for field in ITEM_FIELDS:
            total += 1
            hits += canon(item[field]) == canon(got.get(field))
    result["Строки табличной части"] = (hits, total)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Оценка качества извлечения данных из документов")
    parser.add_argument("--engine", choices=["rules", "claude"], default="rules")
    parser.add_argument("--set", choices=["dev", "holdout", "all"], default="all", dest="dataset")
    parser.add_argument("--json", type=Path, help="сохранить отчёт в JSON")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение платных запросов")
    args = parser.parse_args()

    settings = get_settings()
    company = load_company()
    engine = build_engine(args.engine, company, settings.model, settings.effort)
    expected_all = json.loads((SAMPLES_DIR / "expected.json").read_text(encoding="utf-8"))
    names = ["dev", "holdout"] if args.dataset == "all" else [args.dataset]

    if args.engine == "claude" and not args.yes:
        count = sum(entry["set"] in names for entry in expected_all.values())
        answer = input(f"Будет отправлено {count} платных запросов к {settings.model}. Продолжить? [y/N] ")
        if answer.strip().lower() not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return

    label = "правила" if args.engine == "rules" else f"Claude ({settings.model}, effort={settings.effort})"
    print(f"Движок: {label}")
    started = time.perf_counter()
    report: dict[str, dict] = {}
    for name in names:
        totals: dict[str, list[int]] = {}
        files: dict[str, str] = {}
        cost = latency = 0.0
        for filename, entry in expected_all.items():
            if entry["set"] != name:
                continue
            try:
                data, meta = engine.extract(Document(SAMPLES_DIR / filename, "pdf", filename))
                actual = normalize(data).model_dump()
                cost += meta.cost_usd or 0
                latency += meta.latency_ms
            except EngineError as exc:
                actual = normalize(InvoiceData.model_validate(_empty())).model_dump()
                files[filename] = f"ошибка движка: {exc}"
            scores = compare(entry["data"], actual)
            hits = sum(pair[0] for pair in scores.values())
            total = sum(pair[1] for pair in scores.values())
            files.setdefault(filename, f"{hits}/{total} полей")
            for group, (group_hits, group_total) in scores.items():
                bucket = totals.setdefault(group, [0, 0])
                bucket[0] += group_hits
                bucket[1] += group_total
        count = len(files)
        report[name] = {"groups": totals, "files": files, "cost_usd": round(cost, 4), "avg_latency_ms": round(latency / max(count, 1))}

        print(f"\n=== {name}: {count} документов ===")
        all_hits = sum(pair[0] for pair in totals.values())
        all_total = sum(pair[1] for pair in totals.values())
        for group, (hits, total) in totals.items():
            print(f"  {group:<38} {hits / total * 100:5.1f}%  ({hits}/{total})")
        print(f"  {'Все поля':<38} {all_hits / all_total * 100:5.1f}%  ({all_hits}/{all_total})")
        print(f"  Среднее время: {report[name]['avg_latency_ms']} мс · стоимость: ${report[name]['cost_usd']}")
        for filename, summary in files.items():
            print(f"    {filename}: {summary}")
    print(f"\nГотово за {time.perf_counter() - started:.1f} с")

    if args.json:
        args.json.write_text(json.dumps({"engine": label, "report": report}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Отчёт сохранён: {args.json}")


def _empty() -> dict:
    from app.schemas import empty_invoice

    return empty_invoice().model_dump()


if __name__ == "__main__":
    main()

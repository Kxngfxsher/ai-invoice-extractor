"""Движок правил: разбор PDF с текстовым слоем регулярными выражениями и по таблицам.

Работает без интернета и ключей, но только на знакомых макетах: счёт из учётной программы,
счёт из онлайн-сервиса и акт. Сканы, фотографии и непривычно свёрстанные документы ему не по
силам, для них нужен движок Claude. Разницу показывает scripts/evaluate.py.
"""

import re
import time

from ..pdfio import PdfContent, read_pdf
from ..schemas import Bank, EngineMeta, InvoiceData, LineItem, Party, parse_date
from . import Document, EngineError

MONEY = r"\d{1,3}(?: \d{3})*[.,]\d{2}"
DATE = r"\d{1,2}\s+[а-яё]+\s+\d{4}|\d{1,2}[./]\d{1,2}[./]\d{4}"

_HEADER_RE = re.compile(
    r"(?P<kind>Сч[её]т|Акт|Универсальный передаточный документ|УПД|Товарная накладная)"
    rf"[^\n№]*№\s*(?P<number>\S+)\s+от\s+(?P<date>{DATE})",
    re.IGNORECASE,
)
_ORG_RE = re.compile(
    r"(?:ООО|АО|ПАО|ЗАО)\s+«[^»\n]{2,80}»"
    r"|(?:ИП|Индивидуальный предприниматель)\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}"
)
_INN_RE = re.compile(r"ИНН(?:/КПП)?[^\d\n]{0,25}(\d{12}|\d{10})(?!\d)(?:\s*[/,]?\s*(?:КПП\s*)?(\d{9})(?!\d))?")
_BANK_LABELED_RE = re.compile(r"(?m)^Банк(?: получателя)?:\s*(.+)$")
_BANK_BEFORE_BIK_RE = re.compile(r"(?m)^(.+?)\s+БИК:?\s*\d{9}")
_BIK_RE = re.compile(r"БИК:?\s*(\d{9})(?!\d)")
_ACCOUNT_RE = re.compile(r"(?<!\d)\d{20}(?!\d)")
_TOTAL_RE = re.compile(rf"Всего к оплате:?\s*({MONEY})", re.IGNORECASE)
_SUBTOTAL_RE = re.compile(rf"(?m)^Итого:?\s*({MONEY})")
_VAT_RE = re.compile(rf"(?:в том числе|в т\.\s?ч\.)\s*НДС\s*\(?\s*(\d{{1,2}})\s*%\s*\)?:?\s*({MONEY})", re.IGNORECASE)
_BASIS_RE = re.compile(r"(?m)^Основание:\s*(.+)$")

_DOC_TYPES = {"сч": "invoice", "ак": "act", "уп": "upd", "ун": "upd", "то": "waybill"}
_COLUMNS = (
    ("name", ("товар", "наименование")),
    ("quantity", ("кол",)),
    ("unit", ("ед",)),
    ("price", ("цена",)),
    ("amount", ("сумма",)),
)


def parse_number(cell: str | None) -> float | None:
    if cell is None:
        return None
    cleaned = re.sub(r"\s", "", str(cell)).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _same(a: str, b: str) -> bool:
    return a.lower().replace("ё", "е") == b.lower().replace("ё", "е")


def _unique(values):
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def parse_items(tables: list[list[list[str | None]]]) -> list[LineItem]:
    """Строки табличной части: ищем таблицу с колонками «наименование» и «сумма»."""
    for table in tables:
        for header_index, header in enumerate(table):
            columns: dict[str, int] = {}
            for position, cell in enumerate(header):
                title = (cell or "").lower()
                for key, markers in _COLUMNS:
                    if key not in columns and any(marker in title for marker in markers):
                        columns[key] = position
                        break
            if "name" not in columns or "amount" not in columns:
                continue
            items = []
            for row in table[header_index + 1 :]:
                def cell_of(key: str) -> str | None:
                    position = columns.get(key)
                    return row[position] if position is not None and position < len(row) else None

                name = " ".join((cell_of("name") or "").split())
                if not name:
                    continue
                items.append(
                    LineItem(
                        name=name,
                        quantity=parse_number(cell_of("quantity")),
                        unit=(cell_of("unit") or "").strip() or None,
                        price=parse_number(cell_of("price")),
                        amount=parse_number(cell_of("amount")),
                    )
                )
            if items:
                return items
    return []


def parse(content: PdfContent, company: dict) -> InvoiceData:
    text = content.text

    # Вид, номер и дата документа.
    doc_type, number, doc_date = "other", None, None
    header = _HEADER_RE.search(text)
    if header:
        doc_type = _DOC_TYPES.get(header.group("kind").lower()[:2], "other")
        number = header.group("number").rstrip(".,")
        doc_date = parse_date(header.group("date"))
    else:
        head = text[:600].lower().replace("ё", "е")
        if "счет" in head:
            doc_type = "invoice"
        elif re.search(r"\bакт\b", head):
            doc_type = "act"

    # Банк получателя.
    bank_match = _BANK_LABELED_RE.search(text) or _BANK_BEFORE_BIK_RE.search(text)
    bank_name = bank_match.group(1).strip() if bank_match else None
    bik = _BIK_RE.search(text)
    accounts = _unique(_ACCOUNT_RE.findall(text))
    corr_account = next((account for account in accounts if account.startswith("301")), None)
    account = next((account for account in accounts if not account.startswith("301")), None)

    # Стороны: наша организация — покупатель, первая из остальных — поставщик.
    own_name, own_inn = company.get("name", ""), company.get("inn")
    names = [name for name in _unique(" ".join(match.split()) for match in _ORG_RE.findall(text)) if name not in (bank_name or "")]
    buyer_name = next((name for name in names if _same(name, own_name)), None)
    seller_name = next((name for name in names if name != buyer_name), None)
    if buyer_name is None and len(names) > 1:
        buyer_name = names[1]

    inns = _unique(_INN_RE.findall(text))  # пары (ИНН, КПП) в порядке появления
    inns = [pair for index, pair in enumerate(inns) if pair[0] not in [earlier[0] for earlier in inns[:index]]]
    buyer_pair = next((pair for pair in inns if pair[0] == own_inn), None)
    seller_pair = next((pair for pair in inns if pair != buyer_pair), None)
    if buyer_pair is None and len(inns) > 1:
        buyer_pair = inns[1]
    kpp_by_inn = {inn: kpp for inn, kpp in _INN_RE.findall(text) if kpp}  # КПП может стоять не у первого упоминания

    def party(name: str | None, pair: tuple[str, str] | None) -> Party:
        inn = pair[0] if pair else None
        return Party(name=name, inn=inn, kpp=kpp_by_inn.get(inn) if inn else None)

    # Итоги.
    total_match = _TOTAL_RE.search(text) or _SUBTOTAL_RE.search(text)
    vat_match = _VAT_RE.search(text)
    basis = _BASIS_RE.search(text)

    return InvoiceData(
        doc_type=doc_type,
        number=number,
        date=doc_date,
        seller=party(seller_name, seller_pair),
        buyer=party(buyer_name, buyer_pair),
        bank=Bank(bank_name=bank_name, bik=bik.group(1) if bik else None, account=account, corr_account=corr_account),
        items=parse_items(content.tables),
        total=parse_number(total_match.group(1)) if total_match else None,
        vat_rate=int(vat_match.group(1)) if vat_match else None,
        vat_amount=parse_number(vat_match.group(2)) if vat_match else None,
        basis=basis.group(1).strip() if basis else None,
    )


class RulesEngine:
    name = "rules"

    def __init__(self, company: dict):
        self.company = company

    def extract(self, document: Document) -> tuple[InvoiceData, EngineMeta]:
        if document.kind != "pdf":
            raise EngineError("сканы и фотографии распознаёт только движок Claude")
        started = time.perf_counter()
        try:
            content = read_pdf(document.path)
        except Exception as exc:  # повреждённый или зашифрованный файл
            raise EngineError(f"не удалось прочитать PDF ({type(exc).__name__})") from exc
        if len(content.text.strip()) < 40:
            raise EngineError("в PDF нет текстового слоя: это скан, его распознаёт только движок Claude")
        data = parse(content, self.company)
        return data, EngineMeta(engine="rules", latency_ms=int((time.perf_counter() - started) * 1000))

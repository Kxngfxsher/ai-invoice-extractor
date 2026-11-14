"""Модели данных: что извлекается из документа и какие замечания находит проверка."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["invoice", "act", "upd", "waybill", "other"]
DOC_TYPE_LABELS: dict[str, str] = {
    "invoice": "Счёт на оплату",
    "act": "Акт",
    "upd": "УПД",
    "waybill": "Накладная",
    "other": "Другой документ",
}


class Party(BaseModel):
    name: str | None = Field(description="Название организации или ИП, как в документе")
    inn: str | None = Field(description="ИНН: 10 или 12 цифр")
    kpp: str | None = Field(description="КПП: 9 знаков; у ИП его нет")


class Bank(BaseModel):
    bank_name: str | None = Field(description="Название банка получателя платежа")
    bik: str | None = Field(description="БИК: 9 цифр")
    account: str | None = Field(description="Расчётный счёт получателя: 20 цифр")
    corr_account: str | None = Field(description="Корреспондентский счёт банка: 20 цифр")


class LineItem(BaseModel):
    name: str = Field(description="Наименование товара или услуги")
    quantity: float | None = Field(description="Количество")
    unit: str | None = Field(description="Единица измерения")
    price: float | None = Field(description="Цена за единицу")
    amount: float | None = Field(description="Сумма по строке")


class InvoiceData(BaseModel):
    """Данные первичного документа. Эту схему возвращают оба движка: разбор PDF правилами и Claude.

    Все поля обязательные (без значений по умолчанию): так схема подходит для structured outputs.
    """

    doc_type: DocType = Field(description="Вид документа")
    number: str | None = Field(description="Номер документа")
    date: str | None = Field(description="Дата документа в формате ГГГГ-ММ-ДД")
    seller: Party = Field(description="Кто выставил документ: поставщик, исполнитель, продавец")
    buyer: Party = Field(description="Кому выставлен документ: покупатель, заказчик, плательщик")
    bank: Bank = Field(description="Банковские реквизиты получателя платежа")
    items: list[LineItem] = Field(description="Строки табличной части")
    total: float | None = Field(description="Итоговая сумма к оплате")
    vat_rate: int | None = Field(description="Ставка НДС в процентах; null, если документ без НДС")
    vat_amount: float | None = Field(description="Сумма НДС; null, если документ без НДС")
    basis: str | None = Field(description="Основание: договор, заказ")


class Issue(BaseModel):
    level: Literal["error", "warning", "info"]
    field: str | None  # путь поля для подсветки в интерфейсе: seller.inn, items.2.amount, total
    message: str


class EngineMeta(BaseModel):
    engine: Literal["rules", "claude"]
    model: str | None = None
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    note: str | None = None


def empty_invoice() -> InvoiceData:
    return InvoiceData(
        doc_type="other",
        number=None,
        date=None,
        seller=Party(name=None, inn=None, kpp=None),
        buyer=Party(name=None, inn=None, kpp=None),
        bank=Bank(bank_name=None, bik=None, account=None, corr_account=None),
        items=[],
        total=None,
        vat_rate=None,
        vat_amount=None,
        basis=None,
    )


# --- Приведение к единому виду -------------------------------------------------------------------

_MONTHS = {
    name: number
    for number, name in enumerate(
        "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split(), start=1
    )
}


def parse_date(value: str | None) -> str | None:
    """Приводит дату к ГГГГ-ММ-ДД. Понимает «3 ноября 2026 г.», «06.11.2026», «2026-11-06»."""
    if not value:
        return None
    text = value.strip().lower()
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        match = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
        if match:
            day, month, year = (int(part) for part in match.groups())
        else:
            match = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text)
            if not match or match.group(2) not in _MONTHS:
                return None
            day, month, year = int(match.group(1)), _MONTHS[match.group(2)], int(match.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _text(value: str | None) -> str | None:
    cleaned = " ".join((value or "").split())
    return cleaned or None


def _digits(value: str | None) -> str | None:
    cleaned = re.sub(r"[\s\-]", "", value or "")
    return cleaned or None


def _money(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def normalize(data: InvoiceData) -> InvoiceData:
    """Единый вид значений после любого движка: цифры без пробелов, дата ISO, суммы до копеек."""
    return InvoiceData(
        doc_type=data.doc_type,
        number=_text(data.number),
        date=parse_date(data.date) or _text(data.date),
        seller=Party(name=_text(data.seller.name), inn=_digits(data.seller.inn), kpp=_digits(data.seller.kpp)),
        buyer=Party(name=_text(data.buyer.name), inn=_digits(data.buyer.inn), kpp=_digits(data.buyer.kpp)),
        bank=Bank(
            bank_name=_text(data.bank.bank_name),
            bik=_digits(data.bank.bik),
            account=_digits(data.bank.account),
            corr_account=_digits(data.bank.corr_account),
        ),
        items=[
            LineItem(
                name=_text(item.name) or "",
                quantity=item.quantity,
                unit=_text(item.unit),
                price=_money(item.price),
                amount=_money(item.amount),
            )
            for item in data.items
            if _text(item.name)
        ],
        total=_money(data.total),
        vat_rate=data.vat_rate if data.vat_rate else None,
        vat_amount=_money(data.vat_amount) if data.vat_rate else None,
        basis=_text(data.basis),
    )

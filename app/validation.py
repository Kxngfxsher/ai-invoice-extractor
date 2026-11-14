"""Проверки извлечённых данных обычным кодом: реквизиты, арифметика, контрагент, дубли.

Проверки одинаковы для любого движка. LLM может ошибиться в одной цифре счёта, а документ может
содержать опечатку или подменённые реквизиты: и то, и другое должно быть поймано до оплаты.
"""

from datetime import date, timedelta

from .requisites import account_key_is_valid, bik_is_valid, inn_is_valid, kpp_is_valid
from .schemas import InvoiceData, Issue

MONEY_TOLERANCE = 0.011  # копейка с запасом на двоичную арифметику
VAT_TOLERANCE = 0.06  # расхождения округления НДС по строкам


def fmt_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _close(a: float, b: float, tolerance: float = MONEY_TOLERANCE) -> bool:
    return abs(a - b) <= tolerance


def validate(
    data: InvoiceData,
    *,
    own_inn: str | None = None,
    counterparties: list[dict] | None = None,
    duplicates: list[dict] | None = None,
    today: date | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    today = today or date.today()

    def add(level: str, field: str | None, message: str) -> None:
        issues.append(Issue(level=level, field=field, message=message))

    # --- обязательные поля ---
    if not data.number:
        add("error", "number", "Не найден номер документа")
    if not data.seller.name:
        add("error", "seller.name", "Не найдено название поставщика")
    if data.total is None:
        add("error", "total", "Не найдена итоговая сумма")

    # --- дата ---
    if not data.date:
        add("error", "date", "Не найдена дата документа")
    else:
        try:
            parsed = date.fromisoformat(data.date)
        except ValueError:
            add("error", "date", "Дата не распознана: ожидается ГГГГ-ММ-ДД")
        else:
            if parsed > today + timedelta(days=1):
                add("warning", "date", "Дата документа в будущем")
            elif parsed < today - timedelta(days=3 * 365):
                add("warning", "date", "Документу больше трёх лет")

    # --- ИНН и КПП ---
    if not data.seller.inn:
        add("error", "seller.inn", "Не найден ИНН поставщика")
    elif not inn_is_valid(data.seller.inn):
        add(
            "error",
            "seller.inn",
            "ИНН поставщика не проходит контрольную сумму: ошибка распознавания или опечатка в документе",
        )
    if data.seller.kpp and not kpp_is_valid(data.seller.kpp):
        add("warning", "seller.kpp", "КПП поставщика имеет неверный формат")
    if data.buyer.inn:
        if not inn_is_valid(data.buyer.inn):
            add("warning", "buyer.inn", "ИНН покупателя не проходит контрольную сумму")
        elif own_inn and data.buyer.inn != own_inn:
            add("warning", "buyer.inn", "Документ выставлен на другую организацию: ИНН покупателя не наш")
    if data.buyer.kpp and not kpp_is_valid(data.buyer.kpp):
        add("warning", "buyer.kpp", "КПП покупателя имеет неверный формат")

    # --- банковские реквизиты (в акте их может не быть) ---
    bank = data.bank
    has_bank = any((bank.bik, bank.account, bank.corr_account))
    if data.doc_type == "invoice" and not has_bank:
        add("warning", "bank.account", "В счёте не найдены банковские реквизиты")
    if has_bank:
        if not bank_field_ok(bank.bik, bik_is_valid):
            add("error", "bank.bik", "БИК должен состоять из 9 цифр")
        if not bank.account:
            add("error", "bank.account", "Не найден расчётный счёт")
        elif not (bank.account.isdigit() and len(bank.account) == 20):
            add("error", "bank.account", "Расчётный счёт должен состоять из 20 цифр")
        elif bik_is_valid(bank.bik) and not account_key_is_valid(bank.bik, bank.account):
            add(
                "error",
                "bank.account",
                "Расчётный счёт не соответствует БИК по контрольному ключу: вероятна ошибка в цифре",
            )
        if bank.corr_account and bik_is_valid(bank.bik):
            if not account_key_is_valid(bank.bik, bank.corr_account, correspondent=True):
                add("warning", "bank.corr_account", "Корреспондентский счёт не соответствует БИК по контрольному ключу")

    # --- строки и итог ---
    if not data.items:
        add("warning", "items", "Не найдены строки табличной части")
    for index, item in enumerate(data.items):
        if None not in (item.quantity, item.price, item.amount):
            expected = round(item.quantity * item.price, 2)
            if not _close(expected, item.amount):
                add(
                    "error",
                    f"items.{index}.amount",
                    f"Строка {index + 1}: количество × цена = {fmt_money(expected)}, а в документе {fmt_money(item.amount)}",
                )
    amounts = [item.amount for item in data.items if item.amount is not None]
    items_sum = round(sum(amounts), 2) if amounts else None
    vat_on_top = False
    if items_sum is not None and data.total is not None:
        if _close(items_sum, data.total):
            pass
        elif data.vat_amount is not None and _close(items_sum + data.vat_amount, data.total):
            vat_on_top = True  # цены указаны без НДС, налог начислен сверху
        else:
            add(
                "error",
                "total",
                f"Итог {fmt_money(data.total)} не сходится с суммой строк {fmt_money(items_sum)}: "
                f"разница {fmt_money(abs(data.total - items_sum))}",
            )

    # --- НДС ---
    if data.vat_rate:
        if data.vat_amount is None:
            add("warning", "vat_amount", f"Указана ставка НДС {data.vat_rate}%, но сумма налога не найдена")
        elif data.total is not None:
            if vat_on_top and items_sum is not None:
                expected_vat = round(items_sum * data.vat_rate / 100, 2)
            else:
                expected_vat = round(data.total * data.vat_rate / (100 + data.vat_rate), 2)
            if not _close(expected_vat, data.vat_amount, VAT_TOLERANCE):
                add(
                    "warning",
                    "vat_amount",
                    f"НДС {fmt_money(data.vat_amount)} не соответствует ставке {data.vat_rate}%: "
                    f"ожидалось {fmt_money(expected_vat)}",
                )

    # --- контрагент ---
    if counterparties is not None and data.seller.inn and inn_is_valid(data.seller.inn):
        known = next((entry for entry in counterparties if entry["inn"] == data.seller.inn), None)
        if known is None:
            add("info", "seller.inn", "Новый поставщик: в справочнике контрагентов его нет")
        elif bank.account and (bank.account != known["account"] or bank.bik != known["bik"]):
            add(
                "error",
                "bank.account",
                "Банковские реквизиты отличаются от тех, по которым этому поставщику платили раньше. "
                "Перед оплатой подтвердите смену реквизитов по известному вам телефону поставщика",
            )

    # --- дубли ---
    for duplicate in duplicates or []:
        add(
            "warning",
            "number",
            f"Похоже на дубль: документ с таким же номером, датой и поставщиком уже загружен ({duplicate['filename']})",
        )

    return issues


def bank_field_ok(value: str | None, checker) -> bool:
    return bool(value) and checker(value)


def verdict(issues: list[Issue]) -> str:
    """Сводная оценка документа: attention (есть ошибки), check (предупреждения), ready."""
    levels = {issue.level for issue in issues}
    if "error" in levels:
        return "attention"
    if "warning" in levels:
        return "check"
    return "ready"

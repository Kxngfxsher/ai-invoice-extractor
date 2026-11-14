"""Выгрузка проверенных документов: Excel (два листа), CSV и JSON.

Табличные форматы открываются в Excel и загружаются в учётные системы через импорт из
табличного документа.
"""

import csv
import io

from .schemas import DOC_TYPE_LABELS

STATUS_LABELS = {"new": "на проверке", "approved": "подтверждён", "rejected": "отклонён"}

DOCUMENT_COLUMNS = [
    ("Вид", 18), ("Номер", 14), ("Дата", 12), ("Поставщик", 36), ("ИНН поставщика", 16), ("КПП поставщика", 14),
    ("Покупатель", 30), ("ИНН покупателя", 16), ("Сумма", 14), ("Ставка НДС, %", 13), ("НДС", 13),
    ("Основание", 36), ("Банк", 34), ("БИК", 12), ("Расчётный счёт", 24), ("Корр. счёт", 24),
    ("Статус", 14), ("Файл", 30),
]
ITEM_COLUMNS = [
    ("Номер документа", 16), ("Дата", 12), ("Поставщик", 36), ("№ строки", 9), ("Наименование", 52),
    ("Количество", 12), ("Ед.", 8), ("Цена", 14), ("Сумма", 14),
]


def safe_text(value):
    """Защита от формул в ячейках: текст из документа не должен исполняться в Excel."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def document_row(doc: dict) -> list:
    data = doc["data"]
    return [
        DOC_TYPE_LABELS.get(data["doc_type"], data["doc_type"]),
        data["number"], data["date"], data["seller"]["name"], data["seller"]["inn"], data["seller"]["kpp"],
        data["buyer"]["name"], data["buyer"]["inn"], data["total"], data["vat_rate"], data["vat_amount"],
        data["basis"], data["bank"]["bank_name"], data["bank"]["bik"], data["bank"]["account"],
        data["bank"]["corr_account"], STATUS_LABELS.get(doc["status"], doc["status"]), doc["filename"],
    ]


def item_rows(doc: dict) -> list[list]:
    data = doc["data"]
    return [
        [data["number"], data["date"], data["seller"]["name"], index, item["name"], item["quantity"], item["unit"], item["price"], item["amount"]]
        for index, item in enumerate(data["items"], start=1)
    ]


def build_xlsx(documents: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="0F6E66")

    def fill_sheet(sheet, columns, rows, money_columns):
        sheet.append([title for title, _ in columns])
        for row in rows:
            sheet.append([safe_text(value) for value in row])
        for index, (_, width) in enumerate(columns, start=1):
            cell = sheet.cell(row=1, column=index)
            cell.font, cell.fill = header_font, header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            sheet.column_dimensions[get_column_letter(index)].width = width
        for column in money_columns:
            for row_cells in sheet.iter_rows(min_row=2, min_col=column, max_col=column):
                row_cells[0].number_format = "#,##0.00"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions

    documents_sheet = workbook.active
    documents_sheet.title = "Документы"
    fill_sheet(documents_sheet, DOCUMENT_COLUMNS, [document_row(doc) for doc in documents], money_columns=(9, 11))
    items_sheet = workbook.create_sheet("Позиции")
    fill_sheet(items_sheet, ITEM_COLUMNS, [row for doc in documents for row in item_rows(doc)], money_columns=(8, 9))

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_csv(documents: list[dict]) -> bytes:
    """CSV в кодировке UTF-8 с BOM и разделителем «;»: так его без настроек открывает русский Excel."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([title for title, _ in DOCUMENT_COLUMNS])
    for doc in documents:
        writer.writerow(["" if value is None else safe_text(value) for value in document_row(doc)])
    return ("﻿" + buffer.getvalue()).encode("utf-8")

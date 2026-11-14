"""Генератор демонстрационных документов: PDF с текстовым слоем и эталон для проверки качества.

    python scripts/make_samples.py

Готовые файлы уже лежат в samples/, запускать скрипт нужно только чтобы изменить примеры.
PDF печатает установленный Chrome или Edge в режиме headless (путь можно задать в BROWSER).

Все организации вымышлены. ИНН начинаются с «00» (такого кода региона не существует),
поэтому не могут совпасть с настоящими; контрольные цифры при этом верные.
"""

import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.requisites import complete_inn, with_account_key  # noqa: E402

SAMPLES_DIR = ROOT / "samples"
MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()


# --- Реквизиты ---------------------------------------------------------------------------------

def bank(name: str, bik: str, corr_tail: str) -> dict:
    corr = with_account_key(bik, "30101810000000000" + corr_tail, correspondent=True)
    return {"bank_name": name, "bik": bik, "corr_account": corr}


BANKS = {
    "demo": bank("АО «Демо-Банк» г. Москва", "040000123", "123"),
    "vostok": bank("ПАО «Восточный Расчётный Банк» г. Казань", "040000456", "456"),
    "neva": bank("АО «Нева-Кредит» г. Санкт-Петербург", "040000789", "789"),
}


def company(name: str, inn_base: str, kpp: str | None, address: str, bank_key: str, account_tail: str) -> dict:
    bank_details = BANKS[bank_key]
    account = with_account_key(bank_details["bik"], "40702810000000" + account_tail)
    return {
        "name": name,
        "inn": complete_inn(inn_base),
        "kpp": kpp,
        "address": address,
        "bank": {**bank_details, "account": account},
    }


BUYER = company("ООО «Северный Двор»", "001000001", "000001001", "101000, г. Москва, ул. Примерная, д. 10, оф. 5", "demo", "000101")
SELLERS = {
    "stroymarket": company("ООО «СтройМаркет-Опт»", "001234567", "000001001", "115000, г. Москва, ш. Складское, д. 4, стр. 2", "demo", "001482"),
    "kuznetsov": company("ИП Кузнецов Павел Андреевич", "0023456789", None, "420000, г. Казань, ул. Образцовая, д. 7", "vostok", "002210"),
    "itline": company("ООО «Айти-Линия»", "003456789", "000001001", "190000, г. Санкт-Петербург, пр. Тестовый, д. 21, лит. А", "neva", "003377"),
    "delivery": company("ООО «ТК Быстрая Доставка»", "004567891", "000001001", "140000, Московская обл., г. Люберцы, ул. Транспортная, д. 3", "demo", "004101"),
    "cleaning": company("ООО «ЧистоОфис»", "005678912", "000001001", "125000, г. Москва, ул. Демонстрационная, д. 15", "vostok", "005005"),
    "poligraf": company("ООО «Полиграф-Экспресс»", "006789123", "000001001", "129000, г. Москва, пер. Печатный, д. 2", "neva", "006457"),
    "sokolova": company("ИП Соколова Марина Игоревна", "0078912345", None, "150000, г. Ярославль, ул. Учебная, д. 9", "vostok", "007120"),
    "mebel": company("ООО «МебельПроф»", "008912345", "000001001", "603000, г. Нижний Новгород, ул. Фабричная, д. 30", "demo", "008077"),
}
# Счёт № 6 приходит от знакомого поставщика, но с другими банковскими реквизитами.
STROYMARKET_NEW_BANK = {**BANKS["vostok"], "account": with_account_key(BANKS["vostok"]["bik"], "40702810000000991482")}
# В счёте № 5 в ИНН поставщика «опечатка»: последняя цифра не проходит контрольную сумму.
CLEANING_BAD_INN = SELLERS["cleaning"]["inn"][:-1] + str((int(SELLERS["cleaning"]["inn"][-1]) + 3) % 10)

DOCS = [
    {
        "file": "01_schet_stroymarket.pdf", "set": "dev", "layout": "classic", "doc_type": "invoice",
        "title": "Счёт от знакомого поставщика, НДС 20%",
        "number": "СМ-1482", "date": "2026-11-03", "seller": "stroymarket", "vat_rate": 20,
        "basis": "Договор поставки № 27/26 от 12.01.2026",
        "items": [
            ("Цемент М500 Д0, мешок 50 кг", 40, "шт", 465.00),
            ("Смесь штукатурная гипсовая, 30 кг", 25, "шт", 512.00),
            ("Профиль направляющий 27×28, 3 м", 120, "шт", 98.50),
            ("Доставка по городу", 1, "усл", 2500.00),
        ],
    },
    {
        "file": "02_schet_kanctovary.pdf", "set": "dev", "layout": "classic", "doc_type": "invoice",
        "title": "Счёт от ИП на упрощёнке, без НДС",
        "number": "214", "date": "2026-11-05", "seller": "kuznetsov", "vat_rate": None,
        "basis": "Счёт-заказ № 214 от 05.11.2026",
        "items": [
            ("Бумага офисная А4, 500 л., класс C", 30, "пач", 389.00),
            ("Папка-регистратор 80 мм", 24, "шт", 245.00),
            ("Ручка шариковая синяя", 100, "шт", 18.50),
        ],
    },
    {
        "file": "03_schet_it_uslugi.pdf", "set": "dev", "layout": "modern", "doc_type": "invoice",
        "title": "Счёт на услуги в современном оформлении",
        "number": "ИТ-0931", "date": "2026-11-06", "seller": "itline", "vat_rate": 20,
        "basis": "Договор № 44-ИТ от 01.03.2026",
        "items": [
            ("Абонентское обслуживание ИТ-инфраструктуры, ноябрь 2026", 1, "мес", 42000.00),
            ("Настройка рабочих мест", 6, "шт", 1800.00),
            ("Лицензия антивируса, 12 месяцев", 15, "шт", 1490.00),
        ],
    },
    {
        "file": "04_schet_error_sum.pdf", "set": "dev", "layout": "classic", "doc_type": "invoice",
        "title": "Счёт с арифметической ошибкой в итоге",
        "number": "ТК-778", "date": "2026-11-07", "seller": "delivery", "vat_rate": 20,
        "basis": "Договор перевозки № 15 от 20.05.2026",
        "items": [
            ("Перевозка груза Москва — Тула, 5 т", 2, "рейс", 18500.00),
            ("Погрузочно-разгрузочные работы", 6, "ч", 950.00),
            ("Простой транспорта", 3, "ч", 700.00),
        ],
        "total_shift": 1000.00,
    },
    {
        "file": "05_schet_bad_inn.pdf", "set": "dev", "layout": "classic", "doc_type": "invoice",
        "title": "Счёт с опечаткой в ИНН поставщика",
        "number": "ЧО-356", "date": "2026-11-09", "seller": "cleaning", "vat_rate": None,
        "basis": "Договор на уборку № 8 от 01.02.2026", "seller_inn": CLEANING_BAD_INN,
        "items": [
            ("Ежедневная уборка офиса 180 м², ноябрь 2026", 1, "мес", 36000.00),
            ("Мойка окон", 45, "м2", 120.00),
        ],
    },
    {
        "file": "06_schet_new_bank.pdf", "set": "dev", "layout": "classic", "doc_type": "invoice",
        "title": "Счёт знакомого поставщика с новыми реквизитами",
        "number": "СМ-1517", "date": "2026-11-10", "seller": "stroymarket", "vat_rate": 20,
        "basis": "Договор поставки № 27/26 от 12.01.2026", "bank": STROYMARKET_NEW_BANK,
        "items": [
            ("Гипсокартон влагостойкий 12,5 мм, лист", 80, "шт", 498.00),
            ("Саморезы по металлу 3,5×25, 1000 шт", 12, "упак", 410.00),
        ],
    },
    {
        "file": "07_akt_uslugi.pdf", "set": "dev", "layout": "act", "doc_type": "act",
        "title": "Акт выполненных работ",
        "number": "118", "date": "2026-10-31", "seller": "itline", "vat_rate": 20,
        "basis": "Договор № 44-ИТ от 01.03.2026",
        "items": [
            ("Абонентское обслуживание ИТ-инфраструктуры, октябрь 2026", 1, "мес", 42000.00),
            ("Выезд инженера вне графика", 2, "выезд", 3500.00),
        ],
    },
    {
        "file": "08_schet_duplicate.pdf", "set": "dev", "layout": "classic", "doc_type": "invoice",
        "title": "Повторно присланный счёт (дубль)",
        "number": "214", "date": "2026-11-05", "seller": "kuznetsov", "vat_rate": None,
        "basis": "Счёт-заказ № 214 от 05.11.2026",
        "items": [
            ("Бумага офисная А4, 500 л., класс C", 30, "пач", 389.00),
            ("Папка-регистратор 80 мм", 24, "шт", 245.00),
            ("Ручка шариковая синяя", 100, "шт", 18.50),
        ],
    },
    {
        "file": "h1_schet_poligraf.pdf", "set": "holdout", "layout": "minimal", "doc_type": "invoice",
        "title": "Счёт без рамок, нестандартные подписи полей",
        "number": "2026-0457", "date": "2026-11-09", "seller": "poligraf", "vat_rate": 20,
        "basis": None,
        "items": [
            ("Визитки 90×50, 4+4, тираж 1000", 2, "тираж", 1850.00),
            ("Буклет А4, два сгиба, 500 экз.", 1, "тираж", 9400.00),
            ("Дизайн макета", 3, "ч", 1500.00),
        ],
    },
    {
        "file": "h2_schet_sokolova.pdf", "set": "holdout", "layout": "minimal", "doc_type": "invoice",
        "title": "Счёт без рамок от ИП, без НДС",
        "number": "2026-0112", "date": "2026-11-11", "seller": "sokolova", "vat_rate": None,
        "basis": None,
        "items": [
            ("Корпоративный тренинг «Работа с возражениями», 8 ч", 1, "усл", 48000.00),
            ("Раздаточные материалы", 14, "компл", 350.00),
        ],
    },
    {
        "file": "h3_schet_dogovor_mebel.pdf", "set": "holdout", "layout": "contract", "doc_type": "invoice",
        "title": "Счёт-договор с реквизитами внизу",
        "number": "77", "date": "2026-11-10", "seller": "mebel", "vat_rate": 20,
        "basis": None,
        "items": [
            ("Стол письменный 1400×700, дуб сонома", 8, "шт", 11900.00),
            ("Кресло офисное с сетчатой спинкой", 8, "шт", 8450.00),
            ("Тумба подкатная, 3 ящика", 8, "шт", 6200.00),
            ("Сборка и расстановка мебели", 1, "усл", 9600.00),
        ],
    },
]


# --- Форматирование ----------------------------------------------------------------------------

def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "\u00a0").replace(".", ",")


def quantity(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", ",")


def long_date(iso: str) -> str:
    parsed = date.fromisoformat(iso)
    return f"{parsed.day} {MONTHS[parsed.month - 1]} {parsed.year}"


def short_date(iso: str, separator: str = ".") -> str:
    parsed = date.fromisoformat(iso)
    return f"{parsed.day:02d}{separator}{parsed.month:02d}{separator}{parsed.year}"


def _triple(number: int, feminine: bool) -> list[str]:
    hundreds = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
    tens = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
    teens = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
    units_m = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    units_f = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    words = [hundreds[number // 100]]
    rest = number % 100
    if 10 <= rest < 20:
        words.append(teens[rest - 10])
    else:
        words += [tens[rest // 10], (units_f if feminine else units_m)[rest % 10]]
    return [word for word in words if word]


def _plural(number: int, forms: tuple[str, str, str]) -> str:
    if 11 <= number % 100 <= 14:
        return forms[2]
    return forms[{1: 0, 2: 1, 3: 1, 4: 1}.get(number % 10, 2)]


def rubles_in_words(amount: float) -> str:
    """Сумма прописью, как в бухгалтерских документах."""
    rubles = int(amount)
    kopecks = round((amount - rubles) * 100)
    words: list[str] = []
    for value, forms, feminine in (
        (rubles // 1_000_000, ("миллион", "миллиона", "миллионов"), False),
        (rubles // 1000 % 1000, ("тысяча", "тысячи", "тысяч"), True),
    ):
        if value:
            words += _triple(value, feminine) + [_plural(value, forms)]
    words += _triple(rubles % 1000, False) or ([] if rubles else ["ноль"])
    text = " ".join(words) + " " + _plural(rubles, ("рубль", "рубля", "рублей"))
    return f"{text[:1].upper()}{text[1:]} {kopecks:02d} " + _plural(kopecks, ("копейка", "копейки", "копеек"))


# --- Подготовка данных документа ---------------------------------------------------------------

def prepare(doc: dict) -> dict:
    """Считает суммы и собирает всё, что печатается в документе (оно же эталон для проверки)."""
    seller = SELLERS[doc["seller"]]
    items = [
        {"name": name, "quantity": float(qty), "unit": unit, "price": price, "amount": round(qty * price, 2)}
        for name, qty, unit, price in doc["items"]
    ]
    total = round(sum(item["amount"] for item in items) + doc.get("total_shift", 0), 2)
    rate = doc["vat_rate"]
    vat = round(total * rate / (100 + rate), 2) if rate else None
    bank_details = doc.get("bank") or seller["bank"]
    return {
        "doc_type": doc["doc_type"],
        "number": doc["number"],
        "date": doc["date"],
        "seller": {"name": seller["name"], "inn": doc.get("seller_inn", seller["inn"]), "kpp": seller["kpp"]},
        "buyer": {"name": BUYER["name"], "inn": BUYER["inn"], "kpp": BUYER["kpp"]},
        "bank": None if doc["layout"] == "act" else {
            "bank_name": bank_details["bank_name"],
            "bik": bank_details["bik"],
            "account": bank_details["account"],
            "corr_account": bank_details["corr_account"],
        },
        "items": items,
        "total": total,
        "vat_rate": rate,
        "vat_amount": vat,
        "basis": doc["basis"],
        "_seller_address": seller["address"],
    }


def esc(value) -> str:
    return html.escape(str(value))


def inn_kpp(party: dict, separator: str = ", ") -> str:
    parts = [f"ИНН {party['inn']}"] + ([f"КПП {party['kpp']}"] if party["kpp"] else [])
    return separator.join(parts)


def item_rows(data: dict, numbered: bool = True) -> str:
    rows = []
    for index, item in enumerate(data["items"], start=1):
        number = f"<td class='c'>{index}</td>" if numbered else ""
        rows.append(
            f"<tr>{number}<td>{esc(item['name'])}</td><td class='r'>{quantity(item['quantity'])}</td>"
            f"<td class='c'>{esc(item['unit'])}</td><td class='r'>{money(item['price'])}</td>"
            f"<td class='r'>{money(item['amount'])}</td></tr>"
        )
    return "\n".join(rows)


def vat_line(data: dict) -> tuple[str, str]:
    if data["vat_rate"]:
        return f"В том числе НДС ({data['vat_rate']}%):", money(data["vat_amount"])
    return "Без налога (НДС)", "—"


BASE_CSS = """
@page { size: A4; margin: 14mm 15mm; }
* { box-sizing: border-box; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #000; margin: 0; }
table { border-collapse: collapse; width: 100%; }
.r { text-align: right; white-space: nowrap; } .c { text-align: center; }
small { font-size: 8pt; }
h1 { font-size: 14pt; margin: 14pt 0 8pt; }
.bordered td, .bordered th { border: 1px solid #000; padding: 3pt 5pt; vertical-align: top; }
.bordered th { font-weight: bold; text-align: center; }
"""


def page(body: str, extra_css: str = "") -> str:
    return f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><style>{BASE_CSS}{extra_css}</style></head><body>{body}</body></html>"


# --- Макеты ------------------------------------------------------------------------------------

def layout_classic(data: dict) -> str:
    """Привычный счёт на оплату из учётной программы: таблица банка сверху, позиции, итоги."""
    seller, buyer, bank_details = data["seller"], data["buyer"], data["bank"]
    vat_label, vat_value = vat_line(data)
    kpp_cell = f"КПП {seller['kpp']}" if seller["kpp"] else "КПП"
    return page(f"""
<table class="bordered">
  <tr><td colspan="2" rowspan="2">{esc(bank_details['bank_name'])}<br><small>Банк получателя</small></td>
      <td style="width:14%">БИК</td><td style="width:34%">{bank_details['bik']}</td></tr>
  <tr><td>Сч. №</td><td>{bank_details['corr_account']}</td></tr>
  <tr><td>ИНН {seller['inn']}</td><td>{kpp_cell}</td><td rowspan="2">Сч. №</td><td rowspan="2">{bank_details['account']}</td></tr>
  <tr><td colspan="2">{esc(seller['name'])}<br><small>Получатель</small></td></tr>
</table>
<h1>Счет на оплату № {esc(data['number'])} от {long_date(data['date'])} г.</h1>
<hr>
<table class="parties">
  <tr><td class="label">Поставщик<br>(Исполнитель):</td><td><b>{esc(seller['name'])}, {inn_kpp(seller)}, {esc(data['_seller_address'])}</b></td></tr>
  <tr><td class="label">Покупатель<br>(Заказчик):</td><td><b>{esc(buyer['name'])}, {inn_kpp(buyer)}, {esc(BUYER['address'])}</b></td></tr>
  <tr><td class="label">Основание:</td><td><b>{esc(data['basis'])}</b></td></tr>
</table>
<table class="bordered items">
  <tr><th style="width:5%">№</th><th>Товары (работы, услуги)</th><th style="width:9%">Кол-во</th><th style="width:8%">Ед.</th><th style="width:14%">Цена</th><th style="width:15%">Сумма</th></tr>
  {item_rows(data)}
</table>
<table class="totals">
  <tr><td class="r"><b>Итого:</b></td><td class="r sum"><b>{money(data['total'])}</b></td></tr>
  <tr><td class="r"><b>{vat_label}</b></td><td class="r sum"><b>{vat_value}</b></td></tr>
  <tr><td class="r"><b>Всего к оплате:</b></td><td class="r sum"><b>{money(data['total'])}</b></td></tr>
</table>
<p>Всего наименований {len(data['items'])}, на сумму {money(data['total'])} руб.<br><b>{rubles_in_words(data['total'])}</b></p>
<hr>
<p class="sign">Руководитель ____________________ &nbsp;&nbsp;&nbsp; Бухгалтер ____________________</p>
""", """
.parties td { padding: 4pt 0; vertical-align: top; } .parties .label { width: 17%; }
.items { margin-top: 8pt; } .totals { margin-top: 6pt; } .totals .sum { width: 18%; }
.sign { margin-top: 26pt; }
""")


def layout_modern(data: dict) -> str:
    """Счёт из онлайн-сервиса: реквизиты блоками, даты цифрами, подписи «Р/с» и «К/с»."""
    seller, buyer, bank_details = data["seller"], data["buyer"], data["bank"]
    rows = "\n".join(
        f"<tr><td>{esc(item['name'])}</td><td class='r'>{quantity(item['quantity'])}</td><td class='c'>{esc(item['unit'])}</td>"
        f"<td class='r'>{money(item['price'])}</td><td class='r'>{money(item['amount'])}</td></tr>"
        for item in data["items"]
    )
    return page(f"""
<table class="head"><tr>
  <td><div class="brand">{esc(seller['name'].replace('ООО ', '').strip('«»'))}</div><div class="muted">ИТ-обслуживание для бизнеса</div></td>
  <td class="r"><div class="doc">Счёт № {esc(data['number'])}</div><div>от {short_date(data['date'])}</div></td>
</tr></table>
<table class="blocks"><tr>
  <td><div class="cap">Поставщик</div><b>{esc(seller['name'])}</b><br>ИНН/КПП: {seller['inn']} / {seller['kpp']}<br>{esc(data['_seller_address'])}</td>
  <td><div class="cap">Покупатель</div><b>{esc(buyer['name'])}</b><br>ИНН/КПП: {buyer['inn']} / {buyer['kpp']}<br>{esc(BUYER['address'])}</td>
</tr></table>
<div class="box"><div class="cap">Банковские реквизиты</div>
  Банк: {esc(bank_details['bank_name'])}<br>БИК: {bank_details['bik']}<br>Р/с: {bank_details['account']}<br>К/с: {bank_details['corr_account']}</div>
<p>Основание: {esc(data['basis'])}</p>
<table class="bordered">
  <tr><th>Наименование</th><th style="width:10%">Кол-во</th><th style="width:10%">Ед. изм.</th><th style="width:15%">Цена, ₽</th><th style="width:16%">Сумма, ₽</th></tr>
  {rows}
</table>
<table class="totals">
  <tr><td class="r">Итого:</td><td class="r sum">{money(data['total'])}</td></tr>
  <tr><td class="r">В том числе НДС {data['vat_rate']}%:</td><td class="r sum">{money(data['vat_amount'])}</td></tr>
  <tr><td class="r"><b>Всего к оплате:</b></td><td class="r sum"><b>{money(data['total'])}</b></td></tr>
</table>
<p class="muted">Счёт действителен 5 банковских дней. Оплата означает согласие с условиями договора.</p>
""", """
.head td { vertical-align: top; padding-bottom: 12pt; border-bottom: 2pt solid #1d4ed8; }
.brand { font-size: 18pt; font-weight: bold; color: #1d4ed8; } .doc { font-size: 15pt; font-weight: bold; }
.muted { color: #555; font-size: 8.5pt; } .cap { font-size: 8pt; text-transform: uppercase; color: #555; margin-bottom: 3pt; }
.blocks td { width: 50%; vertical-align: top; padding: 12pt 10pt 12pt 0; }
.box { background: #f1f5f9; padding: 8pt 10pt; margin-bottom: 8pt; line-height: 1.5; }
.totals { margin-top: 6pt; } .totals .sum { width: 20%; } .totals td { padding: 2pt 5pt; }
""")


def layout_act(data: dict) -> str:
    seller, buyer = data["seller"], data["buyer"]
    vat_label, vat_value = vat_line(data)
    return page(f"""
<h1>Акт № {esc(data['number'])} от {long_date(data['date'])} г.</h1>
<hr>
<table class="parties">
  <tr><td class="label">Исполнитель:</td><td><b>{esc(seller['name'])}, {inn_kpp(seller)}, {esc(data['_seller_address'])}</b></td></tr>
  <tr><td class="label">Заказчик:</td><td><b>{esc(buyer['name'])}, {inn_kpp(buyer)}, {esc(BUYER['address'])}</b></td></tr>
  <tr><td class="label">Основание:</td><td><b>{esc(data['basis'])}</b></td></tr>
</table>
<table class="bordered items">
  <tr><th style="width:5%">№</th><th>Наименование работ, услуг</th><th style="width:9%">Кол-во</th><th style="width:9%">Ед.</th><th style="width:14%">Цена</th><th style="width:15%">Сумма</th></tr>
  {item_rows(data)}
</table>
<table class="totals">
  <tr><td class="r"><b>Итого:</b></td><td class="r sum"><b>{money(data['total'])}</b></td></tr>
  <tr><td class="r"><b>{vat_label}</b></td><td class="r sum"><b>{vat_value}</b></td></tr>
</table>
<p>Всего оказано услуг {len(data['items'])}, на сумму {money(data['total'])} руб.<br><b>{rubles_in_words(data['total'])}</b></p>
<p>Вышеперечисленные услуги выполнены полностью и в срок. Заказчик претензий по объёму, качеству и срокам оказания услуг не имеет.</p>
<hr>
<table class="sign"><tr><td><b>ИСПОЛНИТЕЛЬ</b><br>{esc(seller['name'])}<br><br>____________________</td>
<td><b>ЗАКАЗЧИК</b><br>{esc(buyer['name'])}<br><br>____________________</td></tr></table>
""", """
.parties td { padding: 4pt 0; vertical-align: top; } .parties .label { width: 15%; }
.items { margin-top: 8pt; } .totals { margin-top: 6pt; } .totals .sum { width: 18%; }
.sign { margin-top: 18pt; } .sign td { width: 50%; vertical-align: top; }
""")


def layout_minimal(data: dict) -> str:
    """Отложенный макет: без рамок, другие названия полей, дата через косую черту."""
    seller, buyer, bank_details = data["seller"], data["buyer"], data["bank"]
    rows = "\n".join(
        f"<tr><td>{esc(item['name'])}</td><td class='r'>{quantity(item['quantity'])} {esc(item['unit'])}</td>"
        f"<td class='r'>{money(item['price'])}</td><td class='r'>{money(item['amount'])}</td></tr>"
        for item in data["items"]
    )
    kpp = lambda party: f"{party['inn']}/{party['kpp']}" if party["kpp"] else party["inn"]  # noqa: E731
    tax = f"в том числе НДС {data['vat_rate']}% — {money(data['vat_amount'])} ₽" if data["vat_rate"] else "НДС не облагается"
    return page(f"""
<table><tr><td><div class="brand">{esc(seller['name'])}</div></td>
<td class="r"><div class="doc">Счёт {esc(data['number'])}</div>Дата: {short_date(data['date'], '/')}</td></tr></table>
<p>Продавец: {esc(seller['name'])}<br>ИНН/КПП продавца: {kpp(seller)}<br>{esc(data['_seller_address'])}</p>
<p>Плательщик: {esc(buyer['name'])}<br>ИНН/КПП плательщика: {kpp(buyer)}</p>
<p><b>Реквизиты для оплаты</b><br>Получатель платежа: {esc(seller['name'])}<br>
Расчётный счёт {bank_details['account']} в {esc(bank_details['bank_name'])}<br>
БИК {bank_details['bik']}, корр. счёт {bank_details['corr_account']}</p>
<table class="plain">
  <tr><th style="text-align:left">Описание</th><th class="r">Количество</th><th class="r">Стоимость</th><th class="r">Всего</th></tr>
  {rows}
</table>
<p class="total">ИТОГО К ОПЛАТЕ: {money(data['total'])} ₽</p>
<p class="r">{tax}</p>
<p class="muted">Оплатите счёт в течение трёх рабочих дней. В назначении платежа укажите номер счёта.</p>
""", """
.brand { font-size: 16pt; font-weight: bold; letter-spacing: 1pt; } .doc { font-size: 13pt; font-weight: bold; }
p { line-height: 1.5; } .plain { margin-top: 10pt; } .plain th { border-bottom: 1pt solid #000; padding: 4pt 0; }
.plain td { padding: 5pt 0; border-bottom: 0.5pt dotted #999; }
.total { text-align: right; font-size: 13pt; font-weight: bold; margin: 12pt 0 2pt; } .muted { color: #555; font-size: 8.5pt; }
""")


def layout_contract(data: dict) -> str:
    """Отложенный макет: счёт-договор, колонки в другом порядке, реквизиты сторон внизу."""
    seller, buyer, bank_details = data["seller"], data["buyer"], data["bank"]
    rows = "\n".join(
        f"<tr><td class='c'>{index}</td><td>{esc(item['name'])}</td><td class='r'>{money(item['price'])}</td>"
        f"<td class='r'>{quantity(item['quantity'])} {esc(item['unit'])}</td><td class='r'>{money(item['amount'])}</td></tr>"
        for index, item in enumerate(data["items"], start=1)
    )
    return page(f"""
<h1 class="c">Счёт-договор № {esc(data['number'])} от {short_date(data['date'])}</h1>
<p>{esc(seller['name'])}, именуемое в дальнейшем «Поставщик», и {esc(buyer['name'])}, именуемое в дальнейшем «Покупатель»,
заключили настоящий счёт-договор о нижеследующем.</p>
<p>1. Поставщик обязуется передать, а Покупатель принять и оплатить следующий товар:</p>
<table class="bordered">
  <tr><th style="width:5%">№</th><th>Товар</th><th style="width:15%">Цена, руб.</th><th style="width:13%">Кол-во</th><th style="width:16%">Сумма, руб.</th></tr>
  {rows}
</table>
<p class="r"><b>Итого с НДС {data['vat_rate']}%: {money(data['total'])} руб.</b><br>в т.ч. НДС: {money(data['vat_amount'])} руб.</p>
<p>2. Оплата производится в размере 100% в течение 5 банковских дней. 3. Срок поставки — 10 рабочих дней с даты оплаты.
4. Оплата настоящего счёта-договора означает согласие Покупателя с его условиями.</p>
<p><b>Реквизиты сторон</b></p>
<table class="bordered"><tr>
<td style="width:50%"><b>Поставщик</b><br>{esc(seller['name'])}<br>ИНН {seller['inn']}<br>КПП {seller['kpp']}<br>
р/с {bank_details['account']}<br>{esc(bank_details['bank_name'])}<br>БИК {bank_details['bik']}<br>к/с {bank_details['corr_account']}</td>
<td><b>Покупатель</b><br>{esc(buyer['name'])}<br>ИНН {buyer['inn']}<br>КПП {buyer['kpp']}<br>{esc(BUYER['address'])}</td>
</tr></table>
""", "h1 { font-size: 13pt; } p { line-height: 1.45; }")


LAYOUTS = {
    "classic": layout_classic,
    "modern": layout_modern,
    "act": layout_act,
    "minimal": layout_minimal,
    "contract": layout_contract,
}


# --- Печать в PDF ------------------------------------------------------------------------------

def find_browser() -> str:
    candidates = [
        os.getenv("BROWSER"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("Не найден Chrome или Edge. Укажите путь в переменной окружения BROWSER.")


def print_pdf(browser: str, html_path: Path, pdf_path: Path, profile: Path) -> None:
    subprocess.run(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        timeout=120,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not pdf_path.exists():
        raise SystemExit(f"Браузер не создал файл {pdf_path.name}")


def main() -> None:
    browser = find_browser()
    SAMPLES_DIR.mkdir(exist_ok=True)
    expected: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for doc in DOCS:
            data = prepare(doc)
            html_path = tmp_path / (Path(doc["file"]).stem + ".html")
            html_path.write_text(LAYOUTS[doc["layout"]](data), encoding="utf-8")
            print_pdf(browser, html_path, SAMPLES_DIR / doc["file"], tmp_path / "profile")
            data.pop("_seller_address")
            expected[doc["file"]] = {"set": doc["set"], "layout": doc["layout"], "title": doc["title"], "data": data}
            print(f"  {doc['file']}")
    (SAMPLES_DIR / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")

    # Справочник контрагентов: «знакомые» поставщики и их проверенные банковские реквизиты.
    known = [
        {"name": SELLERS[key]["name"], "inn": SELLERS[key]["inn"], "bik": SELLERS[key]["bank"]["bik"], "account": SELLERS[key]["bank"]["account"]}
        for key in ("stroymarket", "kuznetsov", "itline")
    ]
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "counterparties.json").write_text(json.dumps(known, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_dir / "company.json").write_text(
        json.dumps({"name": BUYER["name"], "inn": BUYER["inn"], "kpp": BUYER["kpp"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Готово: {len(DOCS)} документов в {SAMPLES_DIR}")


if __name__ == "__main__":
    main()

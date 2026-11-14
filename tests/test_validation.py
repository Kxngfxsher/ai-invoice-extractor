from datetime import date

from app.schemas import normalize, parse_date
from app.validation import validate, verdict
from tests.conftest import reference

TODAY = date(2026, 11, 13)


def check(data, company, counterparties, **kwargs):
    return validate(data, own_inn=company["inn"], counterparties=counterparties, today=TODAY, **kwargs)


def fields(issues, level):
    return [issue.field for issue in issues if issue.level == level]


def test_clean_invoice_from_known_supplier_is_ready(expected, company, counterparties):
    issues = check(reference(expected["01_schet_stroymarket.pdf"]), company, counterparties)
    assert issues == []
    assert verdict(issues) == "ready"


def test_invoice_without_vat_is_ready(expected, company, counterparties):
    assert verdict(check(reference(expected["02_schet_kanctovary.pdf"]), company, counterparties)) == "ready"


def test_total_that_does_not_match_lines_is_an_error(expected, company, counterparties):
    issues = check(reference(expected["04_schet_error_sum.pdf"]), company, counterparties)
    assert "total" in fields(issues, "error")
    message = next(issue.message for issue in issues if issue.field == "total")
    assert "44 800,00" in message and "1 000,00" in message
    assert verdict(issues) == "attention"


def test_inn_typo_is_an_error(expected, company, counterparties):
    issues = check(reference(expected["05_schet_bad_inn.pdf"]), company, counterparties)
    assert fields(issues, "error") == ["seller.inn"]


def test_changed_bank_details_of_known_supplier_are_flagged(expected, company, counterparties):
    issues = check(reference(expected["06_schet_new_bank.pdf"]), company, counterparties)
    assert fields(issues, "error") == ["bank.account"]
    assert "подтвердите смену реквизитов" in issues[0].message


def test_new_supplier_is_only_an_info(expected, company, counterparties):
    issues = check(reference(expected["h3_schet_dogovor_mebel.pdf"]), company, counterparties)
    assert [(issue.level, issue.field) for issue in issues] == [("info", "seller.inn")]
    assert verdict(issues) == "ready"


def test_act_does_not_require_bank_details(expected, company, counterparties):
    issues = check(reference(expected["07_akt_uslugi.pdf"]), company, counterparties)
    assert issues == []


def test_duplicate_is_a_warning(expected, company, counterparties):
    issues = check(
        reference(expected["08_schet_duplicate.pdf"]),
        company,
        counterparties,
        duplicates=[{"id": 2, "filename": "02_schet_kanctovary.pdf"}],
    )
    assert fields(issues, "warning") == ["number"]
    assert verdict(issues) == "check"


def test_line_arithmetic_account_key_and_vat(expected, company, counterparties):
    data = reference(expected["01_schet_stroymarket.pdf"])
    data.items[0].amount = 18_700.00  # 40 × 465 = 18 600
    data.bank.account = data.bank.account[:-1] + str((int(data.bank.account[-1]) + 1) % 10)
    data.vat_amount = 5_000.00
    issues = check(data, company, counterparties)
    errors = fields(issues, "error")
    assert "items.0.amount" in errors and "total" in errors and "bank.account" in errors
    assert "vat_amount" in fields(issues, "warning")


def test_vat_on_top_of_prices_is_accepted(expected, company, counterparties):
    data = reference(expected["01_schet_stroymarket.pdf"])
    net = round(sum(item.amount for item in data.items), 2)
    data.vat_amount = round(net * 0.2, 2)
    data.total = round(net + data.vat_amount, 2)
    assert check(data, company, counterparties) == []


def test_missing_fields_wrong_buyer_and_future_date(expected, company, counterparties):
    data = reference(expected["03_schet_it_uslugi.pdf"])
    data.number = None
    data.total = None
    data.date = "2027-01-15"
    data.buyer.inn = "7707083893"
    issues = check(data, company, counterparties)
    assert {"number", "total"} <= set(fields(issues, "error"))
    assert {"date", "buyer.inn"} <= set(fields(issues, "warning"))


def test_date_parsing_and_normalization(expected):
    assert parse_date("3 ноября 2026 г.") == "2026-11-03"
    assert parse_date("06.11.2026") == "2026-11-06"
    assert parse_date("09/11/2026") == "2026-11-09"
    assert parse_date("31 февраля 2026") is None
    data = reference(expected["01_schet_stroymarket.pdf"])
    data.seller.inn = " 0012 345 673 "
    data.bank.account = "40702 810 3 0000 0001482"
    cleaned = normalize(data)
    assert cleaned.seller.inn == "0012345673" and cleaned.bank.account == "40702810300000001482"

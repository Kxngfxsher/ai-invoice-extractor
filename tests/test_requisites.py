import pytest

from app.requisites import (
    account_key_is_valid,
    bik_is_valid,
    complete_inn,
    inn_is_valid,
    kpp_is_valid,
    with_account_key,
)


def test_inn_checksum_for_legal_entity():
    assert inn_is_valid("7707083893")  # общеизвестный ИНН крупного банка
    assert not inn_is_valid("7707083894")  # изменена последняя цифра
    assert not inn_is_valid("770708389")
    assert not inn_is_valid("77070838ab")
    assert not inn_is_valid(None)


def test_inn_checksum_for_individual():
    inn = complete_inn("0023456789")
    assert len(inn) == 12 and inn_is_valid(inn)
    assert not inn_is_valid(inn[:-1] + str((int(inn[-1]) + 1) % 10))
    assert not inn_is_valid(inn[:10] + str((int(inn[10]) + 1) % 10) + inn[11])


@pytest.mark.parametrize("base", ["001234567", "009999999", "000000001"])
def test_complete_inn_produces_valid_numbers(base):
    assert inn_is_valid(complete_inn(base))


def test_kpp_and_bik_format():
    assert kpp_is_valid("770701001") and kpp_is_valid("7707AB001")
    assert not kpp_is_valid("77070100") and not kpp_is_valid(None)
    assert bik_is_valid("044525225") and not bik_is_valid("04452522")


def test_account_key_matches_reference_example():
    # Общеизвестная пара: БИК крупного банка и его корреспондентский счёт в Банке России.
    assert account_key_is_valid("044525225", "30101810400000000225", correspondent=True)
    assert not account_key_is_valid("044525225", "30101810500000000225", correspondent=True)


def test_single_digit_error_in_account_is_detected():
    bik = "040000123"
    account = with_account_key(bik, "40702810000000001482")
    assert account_key_is_valid(bik, account)
    for position in (0, 5, 12, 19):
        broken = account[:position] + str((int(account[position]) + 1) % 10) + account[position + 1 :]
        assert not account_key_is_valid(bik, broken), position
    assert not account_key_is_valid("040000456", account)  # тот же счёт с чужим БИК
    assert not account_key_is_valid(bik, account[:-1])

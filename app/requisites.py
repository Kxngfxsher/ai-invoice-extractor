"""Проверка российских реквизитов: ИНН, КПП, БИК, расчётный и корреспондентский счёт.

Контрольные разряды считаются по официальным алгоритмам (для счетов — порядок Банка России
№ 515 от 08.09.1997). Одна неверно распознанная цифра в счёте означает платёж не тому
получателю, поэтому эти проверки выполняются для любого движка, включая LLM.
"""

import re

_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_ACCOUNT_WEIGHTS = (7, 1, 3)


def _inn_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(digit) * weight for digit, weight in zip(digits, weights)) % 11 % 10


def inn_is_valid(inn: str | None) -> bool:
    """ИНН юрлица (10 цифр) или ИП/физлица (12 цифр) с верными контрольными цифрами."""
    if not re.fullmatch(r"\d{10}|\d{12}", inn or ""):
        return False
    if len(inn) == 10:
        return _inn_digit(inn, _INN10_WEIGHTS) == int(inn[9])
    return _inn_digit(inn, _INN12_WEIGHTS_1) == int(inn[10]) and _inn_digit(inn, _INN12_WEIGHTS_2) == int(inn[11])


def complete_inn(base: str) -> str:
    """Дописывает контрольные цифры к первым 9 (юрлицо) или 10 (ИП) цифрам ИНН."""
    if re.fullmatch(r"\d{9}", base):
        return base + str(_inn_digit(base, _INN10_WEIGHTS))
    if re.fullmatch(r"\d{10}", base):
        first = base + str(_inn_digit(base, _INN12_WEIGHTS_1))
        return first + str(_inn_digit(first, _INN12_WEIGHTS_2))
    raise ValueError("нужно 9 или 10 цифр")


def kpp_is_valid(kpp: str | None) -> bool:
    return bool(re.fullmatch(r"\d{4}[\dA-Z]{2}\d{3}", kpp or ""))


def bik_is_valid(bik: str | None) -> bool:
    return bool(re.fullmatch(r"\d{9}", bik or ""))


def _account_prefix(bik: str, correspondent: bool) -> str:
    # Для счёта клиента берутся три последние цифры БИК, для корсчёта — «0» и 5–6-я цифры БИК.
    return "0" + bik[4:6] if correspondent else bik[-3:]


def _account_sum(prefix: str, account: str) -> int:
    return sum(int(digit) * _ACCOUNT_WEIGHTS[index % 3] % 10 for index, digit in enumerate(prefix + account))


def account_key_is_valid(bik: str | None, account: str | None, correspondent: bool = False) -> bool:
    """Проверяет контрольный ключ счёта (9-я цифра) в паре с БИК банка."""
    if not (bik_is_valid(bik) and re.fullmatch(r"\d{20}", account or "")):
        return False
    return _account_sum(_account_prefix(bik, correspondent), account) % 10 == 0


def with_account_key(bik: str, account: str, correspondent: bool = False) -> str:
    """Подставляет верный контрольный ключ в 20-значный номер счёта (нужно генератору примеров)."""
    zeroed = account[:8] + "0" + account[9:]
    key = _account_sum(_account_prefix(bik, correspondent), zeroed) % 10 * 3 % 10
    return account[:8] + str(key) + account[9:]

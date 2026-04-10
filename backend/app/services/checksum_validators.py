"""Checksum validation utilities for Russian structured identifiers.

Each validator returns True if the identifier passes its checksum algorithm,
False otherwise. All functions expect cleaned digit-only strings.
"""

from __future__ import annotations


def validate_inn_10(inn: str) -> bool:
    """Validate 10-digit INN (legal entity) by checksum.

    Algorithm: weighted sum of first 9 digits with coefficients
    [2, 4, 10, 3, 5, 9, 4, 6, 8], mod 11, mod 10 must equal the 10th digit.

    Args:
        inn: 10-digit string.

    Returns:
        True if checksum is valid.

    Examples:
        >>> validate_inn_10("7707083893")
        True
        >>> validate_inn_10("1234567890")
        False
    """
    if len(inn) != 10 or not inn.isdigit():
        return False
    coefficients = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum = sum(int(inn[i]) * coefficients[i] for i in range(9)) % 11 % 10
    return checksum == int(inn[9])


def validate_inn_12(inn: str) -> bool:
    """Validate 12-digit INN (individual) by two checksums.

    Algorithm: two rounds of weighted sums. The 11th digit is checked first,
    then the 12th digit using a different coefficient vector.

    Args:
        inn: 12-digit string.

    Returns:
        True if both checksums are valid.

    Examples:
        >>> validate_inn_12("500100732259")
        True
    """
    if len(inn) != 12 or not inn.isdigit():
        return False
    coef1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    coef2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    check1 = sum(int(inn[i]) * coef1[i] for i in range(10)) % 11 % 10
    check2 = sum(int(inn[i]) * coef2[i] for i in range(11)) % 11 % 10
    return check1 == int(inn[10]) and check2 == int(inn[11])


def validate_ogrn(ogrn: str) -> bool:
    """Validate 13-digit OGRN.

    Algorithm: first 12 digits as integer mod 11, last digit mod 10
    must equal the 13th digit.

    Args:
        ogrn: 13-digit string.

    Returns:
        True if checksum is valid.

    Examples:
        >>> validate_ogrn("1027700132195")
        True
    """
    if len(ogrn) != 13 or not ogrn.isdigit():
        return False
    checksum = int(ogrn[:12]) % 11 % 10
    return checksum == int(ogrn[12])


def validate_ogrnip(ogrnip: str) -> bool:
    """Validate 15-digit OGRNIP.

    Algorithm: first 14 digits as integer mod 13, last digit mod 10
    must equal the 15th digit.

    Args:
        ogrnip: 15-digit string.

    Returns:
        True if checksum is valid.

    Examples:
        >>> validate_ogrnip("304500116000157")
        True
    """
    if len(ogrnip) != 15 or not ogrnip.isdigit():
        return False
    checksum = int(ogrnip[:14]) % 13 % 10
    return checksum == int(ogrnip[14])


def validate_snils(snils: str) -> bool:
    """Validate SNILS (Russian pension insurance number).

    The input should be 9 digits of the number + 2 check digits (11 total).
    Numbers <= 001001998 are not checked (legacy range).

    Algorithm:
        Weighted sum of first 9 digits (weights 9..1).
        If sum < 100: checksum = sum.
        If sum == 100 or 101: checksum = 0.
        If sum > 101: sum = sum % 101; if result >= 100 then 0, else result.

    Args:
        snils: 11-digit string (no dashes or spaces).

    Returns:
        True if checksum is valid.

    Examples:
        >>> validate_snils("11223344595")
        True
    """
    if len(snils) != 11 or not snils.isdigit():
        return False

    number_part = int(snils[:9])
    if number_part <= 1001998:
        return True  # legacy range, no checksum

    weighted_sum = sum(int(snils[i]) * (9 - i) for i in range(9))

    if weighted_sum < 100:
        check = weighted_sum
    elif weighted_sum in (100, 101):
        check = 0
    else:
        remainder = weighted_sum % 101
        check = 0 if remainder >= 100 else remainder

    return check == int(snils[9:11])

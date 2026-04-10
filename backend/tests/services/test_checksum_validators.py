"""Tests for checksum validation utilities."""

import json
from pathlib import Path

import pytest

from app.services.checksum_validators import (
    validate_inn_10,
    validate_inn_12,
    validate_ogrn,
    validate_ogrnip,
    validate_snils,
)

FIXTURES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "synthetic_pii.json").read_text(encoding="utf-8")
)


class TestInn10:
    @pytest.mark.parametrize("inn", FIXTURES["valid_inn_10"])
    def test_valid(self, inn):
        assert validate_inn_10(inn) is True

    @pytest.mark.parametrize("inn", FIXTURES["invalid_inn_10"])
    def test_invalid(self, inn):
        assert validate_inn_10(inn) is False

    def test_empty(self):
        assert validate_inn_10("") is False

    def test_non_digit(self):
        assert validate_inn_10("77070838ab") is False

    def test_wrong_length(self):
        assert validate_inn_10("123") is False
        assert validate_inn_10("12345678901") is False


class TestInn12:
    @pytest.mark.parametrize("inn", FIXTURES["valid_inn_12"])
    def test_valid(self, inn):
        assert validate_inn_12(inn) is True

    @pytest.mark.parametrize("inn", FIXTURES["invalid_inn_12"])
    def test_invalid(self, inn):
        assert validate_inn_12(inn) is False

    def test_empty(self):
        assert validate_inn_12("") is False

    def test_non_digit(self):
        assert validate_inn_12("50010073225x") is False


class TestOgrn:
    @pytest.mark.parametrize("ogrn", FIXTURES["valid_ogrn"])
    def test_valid(self, ogrn):
        assert validate_ogrn(ogrn) is True

    @pytest.mark.parametrize("ogrn", FIXTURES["invalid_ogrn"])
    def test_invalid(self, ogrn):
        assert validate_ogrn(ogrn) is False

    def test_empty(self):
        assert validate_ogrn("") is False

    def test_wrong_length(self):
        assert validate_ogrn("12345") is False


class TestOgrnip:
    @pytest.mark.parametrize("ogrnip", FIXTURES["valid_ogrnip"])
    def test_valid(self, ogrnip):
        assert validate_ogrnip(ogrnip) is True

    @pytest.mark.parametrize("ogrnip", FIXTURES["invalid_ogrnip"])
    def test_invalid(self, ogrnip):
        assert validate_ogrnip(ogrnip) is False

    def test_empty(self):
        assert validate_ogrnip("") is False


class TestSnils:
    @pytest.mark.parametrize("snils", FIXTURES["valid_snils"])
    def test_valid(self, snils):
        assert validate_snils(snils) is True

    @pytest.mark.parametrize("snils", FIXTURES["invalid_snils"])
    def test_invalid(self, snils):
        assert validate_snils(snils) is False

    def test_empty(self):
        assert validate_snils("") is False

    def test_legacy_range(self):
        # Numbers <= 001001998 pass without checksum
        assert validate_snils("00100199800") is True

    def test_non_digit(self):
        assert validate_snils("1122334459x") is False

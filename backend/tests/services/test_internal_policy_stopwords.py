"""Regression tests for internal policy false positives."""

from __future__ import annotations

from app.services.regex_recognizers import OrganizationRuRecognizer
from app.services.stopwords import is_stopword


def test_policy_role_words_are_not_person_entities() -> None:
    for value in (
        "Сотрудники",
        "Сотрудников",
        "Сотрудником",
        "Доверителями",
        "Контрагентов",
        "Кандидата",
    ):
        assert is_stopword(value, "PER")


def test_policy_and_public_tool_words_are_not_locations_or_people() -> None:
    assert is_stopword("Положении", "LOC")
    assert is_stopword("Интернете", "LOC")
    assert is_stopword("Адвокатского Бюро", "LOC")
    assert is_stopword("Адвокатского  Бюро", "LOC")
    assert is_stopword("Российской  Федерации", "LOC")
    assert is_stopword("Сотрудниками Бюро", "LOC")
    assert is_stopword("Alice AI", "PER")
    assert is_stopword("Алиса AI", "PER")
    assert is_stopword("ChatGPT", "ORG")
    assert is_stopword("Ключевые", "PER")


def test_professional_firm_genitive_recognizer_keeps_full_name_only() -> None:
    text = "Сотрудниками Адвокатского Бюро ЕПАМ указанное Положение подписано."

    orgs = [
        text[result.start:result.end]
        for result in OrganizationRuRecognizer().analyze(text, ["ORG"])
    ]

    assert "Адвокатского Бюро ЕПАМ" in orgs
    assert "Адвокатского Бюро" not in orgs

"""Stop-word lists for filtering false positive NER detections.

Legal documents contain many terms that look like entities to spaCy/GLiNER
but are actually generic legal terminology. These lists are applied as a
post-processing step after all NER layers, before adding to EntityRegistry.
"""

from __future__ import annotations

# Legal roles and party names -- never PER, ORG, or LOC
LEGAL_ROLE_STOPWORDS: set[str] = {
    # Contract parties (all declension forms)
    "исполнитель", "исполнителя", "исполнителю", "исполнителем",
    "заказчик", "заказчика", "заказчику", "заказчиком",
    "поставщик", "поставщика", "покупатель", "покупателя",
    "продавец", "продавца", "подрядчик", "подрядчика",
    "субподрядчик", "арендодатель", "арендатор",
    "кредитор", "должник", "заёмщик", "заемщик",
    "залогодатель", "залогодержатель",
    "сторона", "стороны", "сторон", "сторонами",
    "третье лицо", "третьи лица",
    "принципал", "агент", "комиссионер", "комитент",
    "лицензиар", "лицензиат", "правообладатель",
    "грузоотправитель", "грузополучатель", "перевозчик", "экспедитор",
    # Procedural roles
    "истец", "ответчик", "заявитель", "участник", "представитель",
    "обвиняемый", "потерпевший", "свидетель", "эксперт",
    # Document references
    "заявка", "заявки", "заявке", "заявку", "заявкой", "заявками",
    "приложение", "приложении", "приложения", "приложением",
    "дополнение", "акт", "протокол",
    "накладная", "договор", "контракт", "соглашение",
    "счёт-фактура", "счет-фактура",
    # Legal terms that spaCy mistakes for PER
    "заказчиком", "исполнителя",
}

# Position titles -- not sensitive PII
POSITION_STOPWORDS: set[str] = {
    "генеральный директор", "директор", "исполнительный директор",
    "президент", "вице-президент", "председатель",
    "главный бухгалтер", "бухгалтер",
    "заместитель", "руководитель", "начальник",
    "управляющий", "менеджер", "координатор",
    "юрист", "юрисконсульт", "адвокат", "нотариус",
    "секретарь", "помощник",
    "директор по логистике", "коммерческий директор",
    "финансовый директор", "технический директор",
    "операционный директор",
}

# False ORG detections
ORG_STOPWORDS: set[str] = {
    "бик", "инн", "огрн", "огрнип", "кпп", "окпо", "октмо", "оквэд",
    "р/с", "к/с", "л/с",
    "пао", "ооо", "ао", "зао", "оао", "нко", "ип",
    "российская федерация", "рф",
    "мо", "рт", "ро",
    "арбитражный суд", "арбитражном суде",
    "приложение", "приложении", "приложения",
    "приложение 1", "приложение 2", "приложение 3",
    "приложении 1", "приложении 2", "приложении 3",
    "приложение №1", "приложение №2", "приложение №3",
}

# False LOC detections
LOC_STOPWORDS: set[str] = {
    "торговая", "логистическая", "центральная", "главная",
    "транспортная", "промышленная", "складская",
    "российской федерации", "российская федерация",
    "устав", "устава", "уставе", "уставом",
    "мо",
}


def is_stopword(text: str, entity_type: str) -> bool:
    """Check if detected entity text is a known false positive.

    Uses exact matching, stem matching, and short-text filtering.
    """
    normalized = text.strip().lower()

    # Very short entities (1-2 chars) are almost always false positives
    if len(normalized) <= 2 and entity_type in ("PER", "ORG", "LOC"):
        return True

    # Exact match in global stopword lists
    if normalized in LEGAL_ROLE_STOPWORDS:
        return True
    if normalized in POSITION_STOPWORDS:
        return True

    # Multi-word: if every word is a legal-role stopword, the phrase is too.
    # Catches combos like "Заявки Заказчика" where each word is a stop-word.
    words = normalized.split()
    if len(words) >= 2:
        if all(w in LEGAL_ROLE_STOPWORDS for w in words):
            return True

    # Stem matching for multi-word position titles (handles declensions)
    if len(words) >= 2:
        entity_stems = {w[:4] for w in words if len(w) >= 4}
        for phrase in POSITION_STOPWORDS:
            phrase_words = phrase.split()
            if len(words) == len(phrase_words) and len(phrase_words) >= 2:
                phrase_stems = {w[:4] for w in phrase_words if len(w) >= 4}
                if entity_stems and entity_stems == phrase_stems:
                    return True

    # Type-specific stop lists
    if entity_type == "ORG" and normalized in ORG_STOPWORDS:
        return True
    if entity_type == "LOC" and normalized in LOC_STOPWORDS:
        return True

    # Filter "Приложение N" patterns for ORG type
    if entity_type == "ORG":
        import re
        if re.match(r"^приложени[еия]\s*[№#]?\s*\d{1,2}$", normalized):
            return True

    return False

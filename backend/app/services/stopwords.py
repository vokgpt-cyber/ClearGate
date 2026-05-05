"""Stop-word lists for filtering false positive NER detections.

Legal documents contain many terms that look like entities to spaCy/GLiNER
but are actually generic legal terminology. These lists are applied as a
post-processing step after all NER layers, before adding to EntityRegistry.
Expanded in v0.3.0 with FORM_FIELD_STOPWORDS to filter field labels.
"""

from __future__ import annotations

import re

# Legal roles and party names -- never PER, ORG, or LOC
LEGAL_ROLE_STOPWORDS: set[str] = {
    # Contract parties (all declension forms)
    "исполнитель", "исполнителя", "исполнителю", "исполнителем",
    "заказчик", "заказчика", "заказчику", "заказчиком",
    "поставщик", "поставщика", "покупатель", "покупателя",
    "услугодатель", "услугодателя", "услугодателю", "услугодателем",
    "продавец", "продавца", "подрядчик", "подрядчика",
    "субподрядчик", "арендодатель", "арендатор",
    "кредитор", "должник", "заёмщик", "заемщик",
    "залогодатель", "залогодержатель",
    "сторона", "стороны", "сторон", "сторонами",
    "раскрывающая", "раскрывающей", "раскрывающую", "раскрывающим",
    "получающая", "получающей", "получающую", "получающим",
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

# Form-field labels — words that label the field rather than name a person/
# org/place. NER models love these; they're never sensitive PII themselves.
# Match only as standalone single tokens (exact match after lowercase+strip),
# never as substrings — "Адрес поставки" the address is real, "Адрес:" alone
# is just a label.
FORM_FIELD_STOPWORDS: set[str] = {
    # Personal-data labels
    "имя", "фамилия", "отчество", "фио",
    "ф.и.о.", "ф.и.о", "ф/и/о",
    "имени", "фамилии", "отчества",
    # Identifier-field labels (NOT the IDs themselves)
    "паспорт", "паспорта", "снилс", "инн", "огрн", "огрнип",
    "кпп", "окпо", "октмо", "оквэд", "бик",
    # Contact-field labels
    "телефон", "телефона", "тел", "тел.", "т.",
    "email", "e-mail", "почта", "электронная почта",
    "факс", "сайт", "url",
    # Address-field labels
    "адрес", "адреса", "адресу", "адресом",
    "место", "места", "местонахождение", "местонахождения",
    "юридический адрес", "фактический адрес", "почтовый адрес",
    "город", "город:", "область", "район", "улица", "ул.",
    "дом", "д.", "корпус", "корп.", "кв.", "квартира", "офис",
    "индекс",
    # Date-field labels
    "дата", "даты", "дате", "датой",
    "дата рождения", "место рождения",
    # Signature-block labels
    "подпись", "подписи", "роспись",
    "расшифровка", "расшифровки", "расшифровка подписи",
    "должность", "должности",
    "м.п.", "мп",
    # Document-meta labels
    "номер", "№", "n", "no",
    "от", "до",
}

# False ORG detections
ORG_STOPWORDS: set[str] = {
    "бик", "инн", "огрн", "огрнип", "кпп", "окпо", "октмо", "оквэд",
    "р/с", "к/с", "л/с",
    "пао", "ооо", "ао", "зао", "оао", "нко", "ип",
    "российская федерация", "рф",
    "между",
    "аренда", "лизинг", "кредит", "заем", "заём", "займ", "займа",
    "поставка", "подряд", "услуги", "агентирование", "дистрибуция",
    "дистрибьюторский", "дистрибьюторский договор",
    "rub", "rur", "usd", "eur", "cny", "cnh", "rmb", "gbp", "chf",
    "jpy", "hkd", "aed", "try", "kzt", "byn", "uah",
    "юань", "юаней", "юаня", "доллар", "доллары", "долларов", "евро",
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
    normalized = text.strip().rstrip(":;,.!?-").strip().lower()
    canonical = normalized.replace("ё", "е")

    def in_stopwords(value: str, stopwords: set[str]) -> bool:
        return value in stopwords or value.replace("ё", "е") in stopwords

    # Very short entities (1-2 chars) are almost always false positives
    if len(normalized) <= 2 and entity_type in ("PER", "ORG", "LOC"):
        return True

    # Form-field labels — never sensitive PII themselves. Filter regardless
    # of which entity_type the NER model assigned to them.
    if in_stopwords(normalized, FORM_FIELD_STOPWORDS):
        return True

    # Exact match in global stopword lists
    if in_stopwords(normalized, LEGAL_ROLE_STOPWORDS):
        return True
    if in_stopwords(normalized, POSITION_STOPWORDS):
        return True

    # Multi-word: if every word is a legal-role stopword, the phrase is too.
    # Catches combos like "Заявки Заказчика" where each word is a stop-word.
    words = canonical.split()
    if len(words) >= 2:
        if all(w in LEGAL_ROLE_STOPWORDS for w in words):
            return True

    # Slash/comma role chains such as "Поставщик/Услугодатель/Подрядчик"
    # are labels in template contracts, not sensitive entities.
    role_tokens = re.findall(r"[а-яёa-z]+", canonical)
    if len(role_tokens) >= 2:
        if all(t in LEGAL_ROLE_STOPWORDS or t in POSITION_STOPWORDS for t in role_tokens):
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
    if entity_type == "ORG" and in_stopwords(normalized, ORG_STOPWORDS):
        return True
    if entity_type == "LOC" and in_stopwords(normalized, LOC_STOPWORDS):
        return True

    # Filter "Приложение N" patterns for ORG type
    if entity_type == "ORG":
        if re.match(r"^приложени[еия]\s*[№#]?\s*\d{1,2}$", canonical):
            return True

    return False

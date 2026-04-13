/**
 * Entity type registry — the single source of truth for every PII
 * category VELUM can detect. All colors, labels, and placeholder
 * fallbacks for the UI live here so the rest of the codebase can stay
 * agnostic of specific types.
 *
 * Keep this in sync with:
 *   - backend/app/services/entity_registry.py (_RU_LABELS / _EN_LABELS)
 *   - backend/app/models/entities.py (DetectedEntity.entity_type values)
 */

export type EntityTypeCode =
  | 'PER'
  | 'ORG'
  | 'LOC'
  | 'ADDR'
  | 'MON'
  | 'DATE'
  | 'RU_INN'
  | 'RU_OGRN'
  | 'RU_SNILS'
  | 'RU_PASSPORT'
  | 'RU_BANK_ACCOUNT'
  | 'RU_BIK'
  | 'RU_PHONE'
  | 'RU_DATE'
  | 'EMAIL_ADDRESS'
  | 'RU_CASE_NUMBER'
  | 'RU_CONTRACT_NUMBER'
  | 'POSITION'
  | 'PROJECT_CODENAME';

export interface EntityTypeInfo {
  /** Stable code used by the backend pipeline. */
  code: EntityTypeCode;
  /** Short human label, RU. */
  labelRu: string;
  /** Short human label, EN. */
  labelEn: string;
  /**
   * CSS modifier class fragment. The full class becomes
   * `velum-entity velum-entity--{cssKey}`.
   */
  cssKey: string;
  /**
   * Rough semantic group — used by the legend to decide grouping order
   * and by heuristics that want to treat "identifiers" differently from
   * "personal names".
   */
  group: 'person' | 'organization' | 'place' | 'id' | 'contact' | 'value' | 'other';
}

/**
 * Registry of all known entity types. Order here determines the
 * preferred display order in the legend.
 */
export const ENTITY_TYPES: Record<EntityTypeCode, EntityTypeInfo> = {
  PER: {
    code: 'PER',
    labelRu: 'Лицо',
    labelEn: 'Person',
    cssKey: 'per',
    group: 'person',
  },
  POSITION: {
    code: 'POSITION',
    labelRu: 'Должность',
    labelEn: 'Position',
    cssKey: 'position',
    group: 'person',
  },
  ORG: {
    code: 'ORG',
    labelRu: 'Организация',
    labelEn: 'Organization',
    cssKey: 'org',
    group: 'organization',
  },
  PROJECT_CODENAME: {
    code: 'PROJECT_CODENAME',
    labelRu: 'Проект',
    labelEn: 'Project',
    cssKey: 'project',
    group: 'organization',
  },
  LOC: {
    code: 'LOC',
    labelRu: 'Место',
    labelEn: 'Location',
    cssKey: 'loc',
    group: 'place',
  },
  ADDR: {
    code: 'ADDR',
    labelRu: 'Адрес',
    labelEn: 'Address',
    cssKey: 'addr',
    group: 'place',
  },
  RU_INN: {
    code: 'RU_INN',
    labelRu: 'ИНН',
    labelEn: 'INN',
    cssKey: 'inn',
    group: 'id',
  },
  RU_OGRN: {
    code: 'RU_OGRN',
    labelRu: 'ОГРН',
    labelEn: 'OGRN',
    cssKey: 'ogrn',
    group: 'id',
  },
  RU_SNILS: {
    code: 'RU_SNILS',
    labelRu: 'СНИЛС',
    labelEn: 'SNILS',
    cssKey: 'snils',
    group: 'id',
  },
  RU_PASSPORT: {
    code: 'RU_PASSPORT',
    labelRu: 'Паспорт',
    labelEn: 'Passport',
    cssKey: 'passport',
    group: 'id',
  },
  RU_BANK_ACCOUNT: {
    code: 'RU_BANK_ACCOUNT',
    labelRu: 'Счёт',
    labelEn: 'Account',
    cssKey: 'bank',
    group: 'id',
  },
  RU_BIK: {
    code: 'RU_BIK',
    labelRu: 'БИК',
    labelEn: 'BIK',
    cssKey: 'bank',
    group: 'id',
  },
  RU_PHONE: {
    code: 'RU_PHONE',
    labelRu: 'Телефон',
    labelEn: 'Phone',
    cssKey: 'phone',
    group: 'contact',
  },
  EMAIL_ADDRESS: {
    code: 'EMAIL_ADDRESS',
    labelRu: 'Email',
    labelEn: 'Email',
    cssKey: 'email',
    group: 'contact',
  },
  RU_CASE_NUMBER: {
    code: 'RU_CASE_NUMBER',
    labelRu: 'Номер дела',
    labelEn: 'Case no.',
    cssKey: 'case',
    group: 'id',
  },
  RU_CONTRACT_NUMBER: {
    code: 'RU_CONTRACT_NUMBER',
    labelRu: 'Номер договора',
    labelEn: 'Contract no.',
    cssKey: 'contract',
    group: 'id',
  },
  MON: {
    code: 'MON',
    labelRu: 'Сумма',
    labelEn: 'Amount',
    cssKey: 'mon',
    group: 'value',
  },
  DATE: {
    code: 'DATE',
    labelRu: 'Дата',
    labelEn: 'Date',
    cssKey: 'date',
    group: 'value',
  },
  RU_DATE: {
    code: 'RU_DATE',
    labelRu: 'Дата',
    labelEn: 'Date',
    cssKey: 'date',
    group: 'value',
  },
};

/**
 * Look up a type info record, falling back to a generic entry if the
 * backend ever returns a code we don't know about (forward-compatible).
 */
export function getEntityTypeInfo(code: string): EntityTypeInfo {
  const known = ENTITY_TYPES[code as EntityTypeCode];
  if (known) return known;
  return {
    code: code as EntityTypeCode,
    labelRu: code,
    labelEn: code,
    cssKey: 'other',
    group: 'other',
  };
}

/** Build the CSS class string for an entity mark. */
export function entityClassName(code: string): string {
  const info = getEntityTypeInfo(code);
  return `velum-entity velum-entity--${info.cssKey}`;
}

/** Preferred order for displaying types in the legend. */
export const LEGEND_ORDER: EntityTypeCode[] = [
  'PER',
  'POSITION',
  'ORG',
  'PROJECT_CODENAME',
  'LOC',
  'ADDR',
  'RU_INN',
  'RU_OGRN',
  'RU_SNILS',
  'RU_PASSPORT',
  'RU_BANK_ACCOUNT',
  'RU_BIK',
  'RU_CASE_NUMBER',
  'RU_CONTRACT_NUMBER',
  'RU_PHONE',
  'EMAIL_ADDRESS',
  'MON',
  'DATE',
];

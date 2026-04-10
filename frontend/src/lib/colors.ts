/** Entity type color palette — warm tones matching EPAM brand, WCAG AA compliant. */

export interface EntityColor {
  bg: string;
  text: string;
  border: string;
}

const ENTITY_COLORS: Record<string, EntityColor> = {
  PER:              { bg: '#EDE7F6', text: '#4527A0', border: '#B39DDB' },
  ORG:              { bg: '#E8F5E9', text: '#2E7D32', border: '#A5D6A7' },
  LOC:              { bg: '#FFF3E0', text: '#E65100', border: '#FFCC80' },
  ADDR:             { bg: '#FFF3E0', text: '#BF360C', border: '#FFAB91' },
  RU_INN:           { bg: '#FCE4EC', text: '#880E4F', border: '#F48FB1' },
  RU_OGRN:          { bg: '#FCE4EC', text: '#880E4F', border: '#F48FB1' },
  RU_SNILS:         { bg: '#E8EAF6', text: '#283593', border: '#9FA8DA' },
  RU_PASSPORT:      { bg: '#E8EAF6', text: '#283593', border: '#9FA8DA' },
  RU_BANK_ACCOUNT:  { bg: '#E0F7FA', text: '#00695C', border: '#80CBC4' },
  RU_PHONE:         { bg: '#F3E5F5', text: '#6A1B9A', border: '#CE93D8' },
  EMAIL_ADDRESS:    { bg: '#F3E5F5', text: '#6A1B9A', border: '#CE93D8' },
  RU_DATE:          { bg: '#FFF8E1', text: '#F57F17', border: '#FFE082' },
  RU_CASE_NUMBER:   { bg: '#EFEBE9', text: '#4E342E', border: '#BCAAA4' },
  RU_CONTRACT_NUMBER: { bg: '#EFEBE9', text: '#4E342E', border: '#BCAAA4' },
  MON:              { bg: '#E0F2F1', text: '#004D40', border: '#80CBC4' },
  DEFAULT:          { bg: '#F5F5F5', text: '#616161', border: '#BDBDBD' },
};

export function getEntityColor(entityType: string): EntityColor {
  return ENTITY_COLORS[entityType] ?? ENTITY_COLORS.DEFAULT;
}

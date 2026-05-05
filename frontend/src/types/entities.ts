export interface DetectedEntity {
  text: string;
  entity_type: string;
  start: number;
  end: number;
  score: number;
  source_layer: 'regex' | 'ner' | 'llm' | 'llm-scan';
  metadata: Record<string, unknown>;
}

export interface MappingEntry {
  placeholder: string;
  canonical_value: string;
  original_forms: string[];
  entity_type: string;
}

export interface AnonymizeResponse {
  anonymized_text: string;
  entities: DetectedEntity[];
  stats: Record<string, number>;
}

export interface SessionInfo {
  session_id: string;
  created_at: string;
  entity_count: number;
  locale: string;
}

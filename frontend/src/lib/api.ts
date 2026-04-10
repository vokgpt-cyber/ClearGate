const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export { API_URL };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`API error ${response.status}: ${error}`);
  }
  return response.json() as Promise<T>;
}

/**
 * Upload a DOCX file and attach its raw bytes to a specific session so the
 * frontend can later render the document with Word-like fidelity.
 *
 * The backend stores the bytes in memory only and wipes them when the
 * session is closed. It is an error to call this for non-DOCX files.
 */
export async function uploadDocx(
  sessionId: string,
  file: File,
): Promise<{
  text: string;
  format: string;
  page_count: number | null;
  char_count: number;
  document_id: string | null;
}> {
  if (!file.name.toLowerCase().endsWith('.docx')) {
    throw new Error('Only .docx files are supported in Iteration 1');
  }

  const formData = new FormData();
  formData.append('file', file);

  const url = `${API_URL}/api/documents/upload?session_id=${encodeURIComponent(sessionId)}`;
  const response = await fetch(url, { method: 'POST', body: formData });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Upload failed (${response.status}): ${error}`);
  }
  return response.json();
}

/**
 * URL at which the raw DOCX bytes for a given session can be fetched.
 * Used by DocxViewer to stream the file into docx-preview.
 */
export function rawDocumentUrl(sessionId: string): string {
  return `${API_URL}/api/documents/${encodeURIComponent(sessionId)}/raw`;
}

export async function createSession(locale = 'ru'): Promise<{ session_id: string }> {
  return request('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ locale, enable_llm_layer: false }),
  });
}

export async function anonymizeText(
  sessionId: string,
  text: string,
): Promise<{ anonymized_text: string; entities: unknown[]; stats: Record<string, number> }> {
  return request(`/api/sessions/${sessionId}/anonymize`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export async function deanonymizeText(
  sessionId: string,
  text: string,
): Promise<{ text: string }> {
  return request(`/api/sessions/${sessionId}/deanonymize`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export async function getEntities(
  sessionId: string,
): Promise<{ entities: unknown[] }> {
  return request(`/api/sessions/${sessionId}/entities`);
}

/**
 * Manually register a custom entity selected by the user in the UI.
 *
 * The backend returns the assigned id + placeholder; the caller is
 * responsible for adding the entity to the workspace state and
 * re-rendering the overlays.
 */
export async function addCustomEntity(
  sessionId: string,
  payload: { text: string; entity_type: string; start: number; end: number },
): Promise<{
  id: string;
  placeholder: string;
  entity: {
    text: string;
    entity_type: string;
    start: number;
    end: number;
    score: number;
    source_layer?: string;
    metadata?: Record<string, unknown>;
  };
}> {
  return request(`/api/sessions/${sessionId}/entities`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function healthCheck(): Promise<{
  status: string;
  version: string;
  profile: string;
}> {
  return request('/health');
}

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


/**
 * Export the anonymized version of the original uploaded DOCX.
 *
 * The backend loads the raw DOCX that was attached to the session
 * during upload, walks its paragraphs, and replaces every non-rejected
 * entity's original text with its registry-assigned placeholder. The
 * returned blob is an `application/vnd.openxmlformats-...` file ready
 * to hand to a download helper.
 *
 * @param sessionId - Session that owns the DOCX (aka documentId).
 * @param entities - Current in-memory entity list from the workspace.
 *                   Rejected entities are ignored by the backend.
 * @returns Blob + suggested filename parsed from Content-Disposition.
 */
export async function exportAnonymizedDocx(
  sessionId: string,
  entities: Array<{
    text: string;
    state?: string;
    metadata?: Record<string, unknown>;
  }>,
): Promise<{ blob: Blob; filename: string }> {
  const payload = {
    entities: entities.map((e) => ({
      text: e.text,
      placeholder: (e.metadata?.placeholder as string | undefined) ?? '',
      state: e.state ?? 'pending',
    })),
  };

  const response = await fetch(
    `${API_URL}/api/documents/${encodeURIComponent(sessionId)}/export-anonymized`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Export failed (${response.status}): ${errorText}`);
  }

  const blob = await response.blob();

  // Parse filename* (RFC 5987) or filename= from Content-Disposition.
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const starMatch = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plainMatch = /filename="([^"]+)"/i.exec(disposition);
  let filename = 'document_anonymized.docx';
  if (starMatch) {
    try {
      filename = decodeURIComponent(starMatch[1]);
    } catch {
      filename = starMatch[1];
    }
  } else if (plainMatch) {
    filename = plainMatch[1];
  }

  return { blob, filename };
}

/**
 * Trigger a browser download for a Blob. Works in both the regular
 * browser and Tauri's WebView2 — no filesystem access needed, the
 * webview handles the save dialog.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Defer revoke slightly so the click handler has finished.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}


// ── Phase 1 round-trip: import response → deanonymize → export ──

/** A placeholder the LLM used that we couldn't resolve automatically. */
export interface UnresolvedPlaceholder {
  placeholder: string;
  label: string;
  number: number;
  normalized: string;
}

/** Result from the deanonymize-docx endpoint. */
export interface DeanonymizeDocxResult {
  unresolved: UnresolvedPlaceholder[];
  total_replacements: number;
  total_unresolved: number;
}

/** Result from importing a response .docx. */
export interface ImportResponseResult {
  message: string;
  session_id: string;
  char_count: number;
  placeholder_count: number;
}

/**
 * Import a response DOCX (the LLM's anonymized reply) into a session.
 */
export async function importResponseDocx(
  sessionId: string,
  file: File,
): Promise<ImportResponseResult> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(
    `${API_URL}/api/documents/${encodeURIComponent(sessionId)}/import-response`,
    { method: 'POST', body: formData },
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Import failed (${response.status}): ${errorText}`);
  }
  return response.json();
}


/**
 * Trigger server-side deanonymization of the imported response DOCX.
 * Returns stats about replacements and any unresolved placeholders.
 */
export async function deanonymizeDocx(
  sessionId: string,
  manualResolutions: Array<{ placeholder: string; value: string }> = [],
): Promise<DeanonymizeDocxResult> {
  const payload = manualResolutions.length > 0
    ? { manual_resolutions: manualResolutions }
    : {};

  const response = await fetch(
    `${API_URL}/api/documents/${encodeURIComponent(sessionId)}/deanonymize-docx`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Deanonymize failed (${response.status}): ${errorText}`);
  }
  return response.json();
}

/**
 * Export the deanonymized DOCX, optionally supplying manual resolutions
 * for placeholders the automatic matcher couldn't resolve.
 */
export async function exportDeanonymizedDocx(
  sessionId: string,
  manualResolutions: Array<{ placeholder: string; value: string }> = [],
): Promise<{ blob: Blob; filename: string }> {
  const payload = { manual_resolutions: manualResolutions };

  const response = await fetch(
    `${API_URL}/api/documents/${encodeURIComponent(sessionId)}/export-deanonymized`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Export failed (${response.status}): ${errorText}`);
  }

  const blob = await response.blob();

  const disposition = response.headers.get('Content-Disposition') ?? '';
  const starMatch = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plainMatch = /filename="([^"]+)"/i.exec(disposition);
  let filename = 'DEAN_document.docx';
  if (starMatch) {
    try {
      filename = decodeURIComponent(starMatch[1]);
    } catch {
      filename = starMatch[1];
    }
  } else if (plainMatch) {
    filename = plainMatch[1];
  }

  return { blob, filename };
}

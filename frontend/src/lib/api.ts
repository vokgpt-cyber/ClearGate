// Resolve the backend base URL at module load.
//
// Three intended states:
//   undefined → local dev (npm run dev / Tauri) → hit localhost:8000
//   ""        → pilot behind nginx → use relative URLs (same-origin)
//   "http://…" → baked by Docker build arg → use that absolute URL
//
// Nullish-coalescing (??) treats only `undefined`/`null` as missing, so an
// explicit empty string survives and turns every fetch into a relative call
// (e.g. `/api/sessions`), which nginx then proxies to the backend.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/**
 * Build the WebSocket base URL at call time (not at import time) so we can
 * inherit the hostname the user actually typed. Same tri-state as API_URL,
 * but for `""` we derive the URL from `window.location` — the same-origin
 * case that nginx proxies via `/ws/*`.
 */
function wsUrl(): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  if (env === undefined) return 'ws://localhost:8000'; // local dev
  if (env !== '') return env; // explicit absolute URL
  // Same-origin: inherit whatever hostname:port the page is served from.
  if (typeof window === 'undefined') return 'ws://localhost:8000';
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${window.location.host}`;
}

export { API_URL, wsUrl };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    // credentials:'include' is required so the cg_session cookie rides along
    // with every API call; without it the browser strips cookies on
    // cross-origin requests (local dev: :3000 → :8000) and the backend
    // treats the user as unauthenticated.
    credentials: 'include',
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
  const response = await fetch(url, { method: 'POST', body: formData, credentials: 'include' });
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

/** Metadata returned by GET /api/sessions for each persisted session. */
export interface SessionMeta {
  session_id: string;
  locale: string;
  created_at: string;
  entity_count: number;
  has_document: boolean;
  docx_filename: string | null;
}

/**
 * List all persisted sessions (metadata only).
 * Used on startup to restore the sidebar from the SQLite store.
 */
export async function listSessions(): Promise<SessionMeta[]> {
  return request('/api/sessions');
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
      credentials: 'include',
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

/** A single placeholder that was successfully substituted with its real value. */
export interface Restoration {
  placeholder: string;
  real_value: string;
  entity_type: string;
  paragraph_index: number;
}

/** Result from the deanonymize-docx endpoint. */
export interface DeanonymizeDocxResult {
  unresolved: UnresolvedPlaceholder[];
  restorations: Restoration[];
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
    { method: 'POST', body: formData, credentials: 'include' },
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
      credentials: 'include',
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
      credentials: 'include',
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


// ── Sprint B.4: auth helpers ─────────────────────────────────────────────

/** Public user view returned by the backend. */
export interface AuthUser {
  user_id: string;
  username: string;
  is_active: boolean;
}

/** Shape of a successful POST /api/auth/login response. */
export interface LoginResponse {
  user: AuthUser;
}

/**
 * POST /api/auth/login — exchange credentials for a session cookie.
 *
 * On success the backend sets the `cg_session` HttpOnly cookie and
 * returns the authenticated user; callers should stash the user in
 * AuthContext so the rest of the app knows who is logged in.
 *
 * On 401 the backend replies with a generic "Invalid username or
 * password" detail; we preserve that via the shared `request()`
 * helper's Error message so the login form can surface it.
 */
export async function login(username: string, password: string): Promise<AuthUser> {
  const res = await request<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  return res.user;
}

/**
 * POST /api/auth/logout — clear the session cookie on the server.
 *
 * The endpoint returns 204 No Content with no body, so we bypass the
 * JSON-parsing `request()` helper and call fetch directly. This is a
 * best-effort call: if the network fails we still want the UI to
 * forget the local user, so the caller should clear AuthContext state
 * regardless of what this returns.
 */
export async function logout(): Promise<void> {
  await fetch(`${API_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  });
}

/**
 * GET /api/auth/me — resolve the currently authenticated user from the
 * session cookie.
 *
 * Returns `null` when the cookie is missing / expired / invalid — that
 * is the "not logged in" signal. Any other failure surfaces as a
 * thrown Error so unexpected backend problems don't silently drop the
 * user into an unauthenticated state and mask bugs.
 */
export async function getCurrentUser(): Promise<AuthUser | null> {
  const response = await fetch(`${API_URL}/api/auth/me`, {
    credentials: 'include',
  });
  if (response.status === 401) return null;
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API error ${response.status}: ${body}`);
  }
  return (await response.json()) as AuthUser;
}

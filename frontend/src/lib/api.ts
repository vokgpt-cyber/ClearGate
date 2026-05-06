function resolveApiUrl(): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (env === undefined) return 'http://localhost:18000';
  if (env !== '') return env;

  if (typeof window !== 'undefined' && window.location.port === '3000') {
    return `${window.location.protocol}//${window.location.hostname}:18000`;
  }

  return '';
}

const API_URL = resolveApiUrl();

/**
 * Build the WebSocket base URL at call time (not at import time) so we can
 * inherit the hostname the user actually typed. Same tri-state as API_URL,
 * but for `""` we derive the URL from `window.location` — the same-origin
 * case that nginx proxies via `/ws/*`.
 */
function wsUrl(): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  if (env === undefined) return 'ws://localhost:18000'; // local dev
  if (env !== '') return env; // explicit absolute URL
  if (typeof window !== 'undefined' && window.location.port === '3000') {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${window.location.hostname}:18000`;
  }
  // Same-origin: inherit whatever hostname:port the page is served from.
  if (typeof window === 'undefined') return 'ws://localhost:18000';
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

export async function uploadDocument(
  sessionId: string,
  file: File,
): Promise<{
  text: string;
  format: string;
  page_count: number | null;
  char_count: number;
  document_id: string | null;
}> {
  const lowerName = file.name.toLowerCase();
  if (!lowerName.endsWith('.docx') && !lowerName.endsWith('.pdf') && !lowerName.endsWith('.txt')) {
    throw new Error('Only .docx, .pdf, and .txt files are supported');
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

export async function createSession(
  locale = 'ru',
  options: { enableLlmLayer?: boolean } = {},
): Promise<{ session_id: string }> {
  // Fast local mode by default. Deep Scan can become an explicit advanced
  // option later; it should not silently add minutes to every document.
  const enable_llm_layer = options.enableLlmLayer ?? false;
  return request('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ locale, enable_llm_layer }),
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

export async function deepScanText(
  sessionId: string,
  text: string,
  entities: unknown[],
): Promise<{
  anonymized_text: string;
  entities: unknown[];
  stats: Record<string, number>;
  suggestions?: unknown[];
  suggestion_count?: number;
}> {
  const cleanEntities = entities
    .filter((entity): entity is Record<string, unknown> => (
      typeof entity === 'object' && entity !== null
    ))
    .map((entity) => {
      const metadata =
        typeof entity.metadata === 'object' && entity.metadata !== null
          ? { ...(entity.metadata as Record<string, unknown>) }
          : {};
      if (typeof entity.id === 'string') metadata.id = entity.id;
      if (typeof entity.state === 'string') metadata.state = entity.state;
      return {
        text: entity.text,
        entity_type: entity.entity_type,
        start: entity.start,
        end: entity.end,
        score: entity.score,
        source_layer: entity.source_layer ?? 'regex',
        metadata,
      };
    });
  return request(`/api/sessions/${sessionId}/deep-scan`, {
    method: 'POST',
    body: JSON.stringify({ text, entities: cleanEntities }),
  });
}

export async function getCachedAnonymization(
  sessionId: string,
): Promise<{ anonymized_text: string; entities: unknown[]; stats: Record<string, number> } | null> {
  const response = await fetch(
    `${API_URL}/api/sessions/${encodeURIComponent(sessionId)}/anonymization`,
    { credentials: 'include' },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API error ${response.status}: ${body}`);
  }
  return response.json();
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
  has_anonymization?: boolean;
  workflow_stage?: WorkflowStage;
  has_response?: boolean;
  has_deanonymized?: boolean;
}

/**
 * List all persisted sessions (metadata only).
 * Used on startup to restore the sidebar from the SQLite store.
 */
export async function listSessions(): Promise<SessionMeta[]> {
  return request('/api/sessions');
}

export async function closeSession(sessionId: string): Promise<void> {
  const response = await fetch(
    `${API_URL}/api/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE', credentials: 'include' },
  );
  if (!response.ok && response.status !== 204) {
    const body = await response.text();
    throw new Error(`Delete session failed (${response.status}): ${body}`);
  }
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
  raw_text: string;
  normalized: string;
  paragraph_index: number;
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

export type WorkflowStage = 'anonymized' | 'llm_response' | 'deanonymized';

export interface DocumentWorkflowState {
  stage: WorkflowStage;
  response_imported: boolean;
  deanonymized_available: boolean;
  response_docx_filename: string | null;
  deanonymize_result: DeanonymizeDocxResult | null;
  manual_resolutions: Array<{ placeholder: string; value: string }>;
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

export async function getDocumentWorkflow(
  sessionId: string,
): Promise<DocumentWorkflowState | null> {
  const response = await fetch(
    `${API_URL}/api/documents/${encodeURIComponent(sessionId)}/workflow`,
    { credentials: 'include' },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Workflow state failed (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function setDocumentWorkflowStage(
  sessionId: string,
  stage: WorkflowStage,
): Promise<DocumentWorkflowState> {
  return request(`/api/documents/${encodeURIComponent(sessionId)}/workflow-stage`, {
    method: 'POST',
    body: JSON.stringify({ stage }),
  });
}


// ── Sprint B.4: auth helpers ─────────────────────────────────────────────

/** Public user view returned by the backend. */
export interface AuthUser {
  user_id: string;
  username: string;
  is_active: boolean;
  /** Role assigned via LDAP group membership or local admin grant.
   *  Optional for backward compatibility with pre-v0.4.0 backends that
   *  don't return the field; treated as "lawyer" when missing. */
  role?: 'admin' | 'lawyer';
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

// =================== Feedback (Phase 6) ===================

export interface FeedbackItem {
  id: string;
  category: 'bug' | 'suggestion' | 'question';
  text: string;
  status: 'new' | 'in_progress' | 'resolved' | 'wontfix';
  created_at: string;
  admin_reply: string | null;
  admin_reply_at: string | null;
}

type FeedbackItemWire = Omit<FeedbackItem, 'id'> & { id: string | number };

function normalizeFeedbackItem(item: FeedbackItemWire): FeedbackItem {
  return { ...item, id: String(item.id) };
}

export async function submitFeedback(input: {
  text: string;
  category: FeedbackItem['category'];
  current_url?: string;
  screenshot?: string;
}): Promise<{ id: string; created_at: string }> {
  const response = await request<{ id: string | number; created_at: string }>(
    '/api/feedback/',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  );
  return { ...response, id: String(response.id) };
}

export async function listMyFeedback(): Promise<FeedbackItem[]> {
  const response = await request<{ items: FeedbackItemWire[]; count: number }>(
    '/api/feedback/mine',
  );
  return response.items.map(normalizeFeedbackItem);
}

// =================== Admin (Phase 6) ===================

export interface AdminUserItem {
  user_id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  role: 'admin' | 'lawyer';
  is_active: boolean;
  ldap_dn: string | null;
  created_at: string;
  last_login_at: string | null;
}

export async function adminListUsers(): Promise<AdminUserItem[]> {
  const response = await request<{ users: AdminUserItem[]; total: number }>(
    '/api/admin/users',
  );
  return response.users;
}

export async function adminCreateUser(input: {
  username: string;
  password: string;
  email?: string;
  display_name?: string;
  role?: 'admin' | 'lawyer';
}): Promise<AdminUserItem> {
  return request('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function adminUpdateUser(
  user_id: string,
  patch: {
    is_active?: boolean;
    role?: 'admin' | 'lawyer';
    email?: string;
    display_name?: string;
    new_password?: string;
  },
): Promise<AdminUserItem> {
  return request(`/api/admin/users/${user_id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export async function adminDeleteUser(user_id: string): Promise<void> {
  const response = await fetch(
    `${API_URL}/api/admin/users/${encodeURIComponent(user_id)}`,
    { method: 'DELETE', credentials: 'include' },
  );
  if (!response.ok && response.status !== 204) {
    const body = await response.text();
    throw new Error(`Delete user failed (${response.status}): ${body}`);
  }
}

export interface AdminFeedbackItem extends FeedbackItem {
  user_id: string;
  username: string;
}

export async function adminListFeedback(
  status?: FeedbackItem['status'],
): Promise<AdminFeedbackItem[]> {
  const qs = status ? `?status=${status}` : '';
  const response = await request<{
    items: Array<Omit<AdminFeedbackItem, 'id'> & { id: string | number }>;
    total: number;
  }>(
    `/api/admin/feedback${qs}`,
  );
  return response.items.map((item) => ({
    ...item,
    id: String(item.id),
  }));
}

export async function adminReplyFeedback(
  id: string,
  reply: string,
  status: FeedbackItem['status'],
): Promise<AdminFeedbackItem> {
  return request(`/api/admin/feedback/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ admin_reply: reply, status }),
  });
}

export interface AnalyticsSummary {
  /** Total session count in the requested time range. */
  total_sessions: number;
  /** Anonymize-call latency percentiles in milliseconds. */
  anonymize_latency: {
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
  };
  /** Sessions bucketed by date — used for the daily chart. */
  sessions_per_day: Array<{ date: string; count: number }>;
  /** Top entity types found across all anonymizations. The admin page
   *  reads `.type` so we expose it under that name (the backend internally
   *  stores entity_type but maps to `type` in the response). */
  top_entity_types: Array<{ type: string; count: number }>;
  /** Distinct users that anonymized at least one document in the last 7d. */
  active_users_7d: number;
  /** Server-side error rate as a percentage 0-100 (NOT a 0-1 fraction). */
  error_rate_percent: number;
}

export async function adminGetAnalytics(
  days: number = 30,
): Promise<AnalyticsSummary> {
  return request(`/api/admin/analytics?days=${days}`);
}

export interface AdminErrorItem {
  id: string;
  source: 'client' | 'server';
  severity: string;
  message: string;
  url: string | null;
  user_id: string | null;
  username: string | null;
  created_at: string;
  /** User-Agent string from the browser at the moment of failure (client
   *  errors) or from the request that triggered the server exception. */
  user_agent: string | null;
  /** JS stack trace (client) or Python traceback (server). May be null
   *  when severity is low and we didn't bother capturing one. */
  stack_trace: string | null;
}

export async function adminListErrors(
  severity?: string,
  limit: number = 100,
): Promise<AdminErrorItem[]> {
  // Both filters are optional. severity narrows to a single level; limit
  // caps the row count. The backend route honours either or both.
  const params = new URLSearchParams();
  if (severity) params.set('severity', severity);
  params.set('limit', String(limit));
  const response = await request<{
    items: Array<Partial<AdminErrorItem> & {
      id: string | number;
      timestamp?: string;
      page_url?: string | null;
      stack?: string | null;
    }>;
    total: number;
  }>(`/api/admin/errors?${params.toString()}`);
  return response.items.map((item) => ({
    id: String(item.id),
    source:
      item.source === 'server' || item.page_url?.startsWith('/api')
        ? 'server'
        : 'client',
    severity: item.severity ?? 'error',
    message: item.message ?? '',
    url: item.url ?? item.page_url ?? null,
    user_id: item.user_id ?? null,
    username: item.username ?? null,
    created_at: item.created_at ?? item.timestamp ?? new Date().toISOString(),
    user_agent: item.user_agent ?? null,
    stack_trace: item.stack_trace ?? item.stack ?? null,
  }));
}

// =================== Backward-compatible aliases ===================
//
// The admin pages under src/app/admin/ were authored against an earlier
// API naming convention (no `admin*` prefix). Rather than refactor every
// admin page, we re-export the canonical functions/types under the names
// the admin pages expect. This keeps both naming schemes valid so other
// callers (e.g. the FeedbackWidget, the CommandPalette) don't break.

export const getUsers = adminListUsers;
export const createUser = adminCreateUser;
export const updateUser = adminUpdateUser;
export const deleteUser = adminDeleteUser;
export const getErrors = adminListErrors;

/** GET /api/admin/analytics?from=YYYY-MM-DD&to=YYYY-MM-DD — admin page
 *  passes a date range (computed from the period selector). The backend
 *  also supports the older days=N form via adminGetAnalytics. */
export async function getAnalytics(
  from?: string,
  to?: string,
): Promise<AnalyticsSummary> {
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  const qs = params.toString();
  return request(`/api/admin/analytics${qs ? `?${qs}` : ''}`);
}

/** GET /api/admin/feedback?status=&limit= — admin sees all users' feedback,
 *  optionally filtered by status. The `'all'` sentinel value is the admin
 *  page's "no filter"; we map it to undefined here. */
export async function getFeedback(
  status?: FeedbackItem['status'] | 'all',
  limit?: number,
): Promise<AdminFeedbackItem[]> {
  const params = new URLSearchParams();
  if (status && status !== 'all') params.set('status', status);
  if (limit !== undefined) params.set('limit', String(limit));
  const qs = params.toString();
  const response = await request<{
    items: Array<Omit<AdminFeedbackItem, 'id'> & { id: string | number }>;
    total: number;
  }>(
    `/api/admin/feedback${qs ? `?${qs}` : ''}`,
  );
  return response.items.map((item) => ({
    ...item,
    id: String(item.id),
  }));
}

/** PATCH /api/admin/feedback/{id} — reply and/or change status. Both
 *  fields are optional in the patch object; the backend only updates
 *  what's present. */
export async function updateFeedback(
  id: string,
  patch: {
    admin_reply?: string;
    status?: FeedbackItem['status'];
  },
): Promise<AdminFeedbackItem> {
  return request(`/api/admin/feedback/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export type AdminUser = AdminUserItem;
export type AdminFeedback = AdminFeedbackItem;
export type AdminError = AdminErrorItem;

/** Payload for POST /api/admin/users (admin pages reference this name). */
export interface CreateUserPayload {
  username: string;
  password: string;
  email?: string;
  display_name?: string;
  role?: 'admin' | 'lawyer';
}

/** POST /api/admin/users/sync-ad — pull current AD membership and update
 *  local user records (role grants/revocations, deactivations). Admin only. */
export async function syncAD(): Promise<{
  created: number;
  updated: number;
  deactivated: number;
}> {
  return request('/api/admin/users/sync-ad', {
    method: 'POST',
  });
}

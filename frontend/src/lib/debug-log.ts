/**
 * Debug log helper — tees frontend diagnostic breadcrumbs to both the
 * browser console and a server-side JSONL file under `backend/logs/`.
 *
 * This exists ONLY to support iter3.2 root-cause diagnosis of the
 * selection → popover event chain. The user is not a developer and
 * cannot be asked to read DevTools console output, so we persist each
 * log point to a file that Claude can read directly from the project
 * directory.
 *
 * SECURITY MODEL
 * --------------
 * The VELUM security model forbids persisting original document text
 * or entity mapping data. This helper is the CHOKE POINT that enforces
 * that contract on the client side:
 *
 *   1. `logSel()` strips any key whose name implies text content
 *      (`text`, `sample`, `content`, `value`, `placeholder`, `mapping`)
 *      BEFORE sending the payload to the server.
 *   2. The server-side endpoint (`app/routers/debug.py`) performs a
 *      second scrubbing pass as defense-in-depth.
 *
 * The in-browser `console.info` call keeps whatever the caller passed,
 * because it is ephemeral and only visible on the user's local machine.
 * The file-log path is the only place where the contract matters.
 */

import { API_URL } from './api';

const FORBIDDEN_KEYS = new Set([
  'text',
  'sample',
  'content',
  'value',
  'placeholder',
  'mapping',
  'original',
  'plaintext',
  'plain_text',
]);

/**
 * Recursively strip any key whose name hints at document text. Drops
 * the key entirely rather than masking so the resulting payload can
 * never be used to reconstruct a selection.
 */
function scrub(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(scrub);
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      if (FORBIDDEN_KEYS.has(k.toLowerCase())) continue;
      out[k] = scrub(v);
    }
    return out;
  }
  return value;
}

/**
 * Opaque session id generated once per page load. All log entries
 * from the same frontend mount share this id, which lets Claude
 * distinguish a fresh diagnostic run from stale entries (if clearing
 * was skipped for any reason).
 */
const SESSION_ID =
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export function getDebugSessionId(): string {
  return SESSION_ID;
}

/**
 * Emit one diagnostic breadcrumb.
 *
 * Writes to the browser console (unchanged payload, for local debug)
 * AND fires a scrubbed copy at `POST /api/debug/selection-log` so
 * Claude can read it back from `backend/logs/selection-diagnostic.jsonl`.
 *
 * The POST is fire-and-forget: we deliberately do NOT await it, so the
 * instrumentation cannot block the selection pipeline even if the
 * backend is down or slow.
 */
export function logSel(label: string, data: Record<string, unknown> = {}): void {
  // eslint-disable-next-line no-console
  console.info(`[Velum/sel] ${label}`, data);

  try {
    const scrubbed = scrub(data);
    void fetch(`${API_URL}/api/debug/selection-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        label,
        data: scrubbed,
        session: SESSION_ID,
      }),
      // Keep the request alive if the page is navigating away.
      keepalive: true,
    }).catch(() => {
      /* swallow — diagnostics must not interfere with real work */
    });
  } catch {
    /* swallow — scrubbing or JSON serialization failure is non-fatal */
  }
}

/**
 * Reset the server-side log file at the start of a diagnostic run.
 *
 * Called once on SplitWorkspace mount so every fresh workspace session
 * starts with a clean JSONL file. Safe to call repeatedly — worst case
 * is a few wasted bytes on disk.
 */
export function clearSelectionLog(): void {
  try {
    void fetch(`${API_URL}/api/debug/selection-log/clear`, {
      method: 'POST',
      keepalive: true,
    }).catch(() => {
      /* swallow */
    });
  } catch {
    /* swallow */
  }
}

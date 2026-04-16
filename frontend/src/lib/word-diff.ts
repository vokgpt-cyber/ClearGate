/**
 * word-diff — pure LCS-based word-level diff used by the Compare view.
 *
 * Scope intentionally tiny: we tokenize both sides into (word | whitespace)
 * runs, run a plain LCS, and emit an inline HTML overlay where:
 *   - unchanged tokens render as-is
 *   - insertions (present on the right, missing on the left) wrap in
 *     `<ins class="cleargate-diff-ins">…</ins>`
 *   - deletions (present on the left, missing on the right) wrap in
 *     `<del class="cleargate-diff-del">…</del>`
 *
 * The caller is responsible for putting the returned HTML string inside
 * a container that preserves whitespace / line breaks (we emit <br> for
 * newlines ourselves so the overlay works inside any block element).
 *
 * Complexity is O(n*m) in tokens; fine for the 5-10k-word documents
 * CLEARGATE targets in Phase 1. If that ever becomes a bottleneck we swap
 * the core for Myers or histogram diff — the public surface stays.
 */

export type DiffOp =
  | { kind: 'eq'; text: string }
  | { kind: 'ins'; text: string }
  | { kind: 'del'; text: string };

// Split text into tokens: sequences of word chars, single whitespace
// characters, or single punctuation characters. Keeping whitespace as
// its own tokens makes the output preserve the original spacing.
const TOKEN_RE = /(\s+|[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_])/gu;

export function tokenize(text: string): string[] {
  if (!text) return [];
  return text.match(TOKEN_RE) ?? [];
}

/**
 * Compute word-level diff ops between two strings.
 * Adjacent ops of the same kind are coalesced for more compact output.
 */
export function diffWords(oldText: string, newText: string): DiffOp[] {
  const a = tokenize(oldText);
  const b = tokenize(newText);
  const n = a.length;
  const m = b.length;

  // LCS table (int16 is plenty for <32k tokens per side).
  const rows = n + 1;
  const cols = m + 1;
  const lcs = new Uint32Array(rows * cols);
  for (let i = 1; i <= n; i++) {
    const ai = a[i - 1];
    const rowOff = i * cols;
    const prevRow = (i - 1) * cols;
    for (let j = 1; j <= m; j++) {
      if (ai === b[j - 1]) {
        lcs[rowOff + j] = lcs[prevRow + (j - 1)] + 1;
      } else {
        const up = lcs[prevRow + j];
        const left = lcs[rowOff + (j - 1)];
        lcs[rowOff + j] = up >= left ? up : left;
      }
    }
  }

  // Walk back to build ops.
  const ops: DiffOp[] = [];
  let i = n;
  let j = m;
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) {
      ops.push({ kind: 'eq', text: a[i - 1] });
      i--;
      j--;
    } else if (lcs[(i - 1) * cols + j] >= lcs[i * cols + (j - 1)]) {
      ops.push({ kind: 'del', text: a[i - 1] });
      i--;
    } else {
      ops.push({ kind: 'ins', text: b[j - 1] });
      j--;
    }
  }
  while (i > 0) {
    ops.push({ kind: 'del', text: a[i - 1] });
    i--;
  }
  while (j > 0) {
    ops.push({ kind: 'ins', text: b[j - 1] });
    j--;
  }
  ops.reverse();

  // Coalesce adjacent ops of the same kind into single chunks so the
  // emitted HTML has far fewer wrapper elements.
  const out: DiffOp[] = [];
  for (const op of ops) {
    const last = out[out.length - 1];
    if (last && last.kind === op.kind) {
      last.text += op.text;
    } else {
      out.push({ ...op });
    }
  }
  return out;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * Render diff ops as inline HTML. Newlines become <br>; other
 * whitespace is preserved (caller should style the host with
 * `white-space: pre-wrap`).
 */
export function renderDiffHtml(ops: DiffOp[]): string {
  const parts: string[] = [];
  for (const op of ops) {
    const html = escapeHtml(op.text).replace(/\n/g, '<br>');
    if (op.kind === 'eq') {
      parts.push(html);
    } else if (op.kind === 'ins') {
      parts.push(`<ins class="cleargate-diff-ins">${html}</ins>`);
    } else {
      parts.push(`<del class="cleargate-diff-del">${html}</del>`);
    }
  }
  return parts.join('');
}

/** Convenience: diff + render in one call. */
export function diffWordsHtml(oldText: string, newText: string): string {
  return renderDiffHtml(diffWords(oldText, newText));
}

'use client';

/**
 * SplitWorkspace — two-pane interactive workspace.
 *
 * Iteration 3 scope (this file):
 *   1. Detection pass identical to iteration 2: render original +
 *      anonymized panes from the same DOCX, run `/anonymize` once the
 *      left pane's anchor map is ready, overlay the result.
 *   2. Each pane is wrapped in a `DocxPane` instance whose constructor
 *      snapshots the CLEAN post-render innerHTML. Every subsequent state
 *      change (accept / reject / change type / add / remove / filter
 *      toggle) calls `pane.rerender(entities, mode)`, which restores the
 *      clean HTML and re-applies the current filtered entity set in one
 *      shot. The DocxPane also owns anchor-map access — every selection
 *      handler reads through `pane.getAnchorMap()`, which always builds
 *      a fresh map against the live DOM, so stale-map bugs (the iter3.x
 *      IndexSizeError class) are structurally impossible by design.
 *   3. Click on any `<mark.cleargate-entity>` in either pane opens the
 *      EntityPopover with accept / reject / change type / remove actions.
 *   4. Hovering over a mark adds `.cleargate-entity--active` to every mark
 *      sharing the same `data-entity-id` in BOTH panes, so the user
 *      can see at a glance how a span maps across panes.
 *   5. Selecting text in the LEFT pane surfaces the SelectionToolbar:
 *      picking a type POSTs to the new `/entities` endpoint, receives
 *      a placeholder, and appends the new InteractiveEntity to state.
 *   6. EntityLegend is now interactive: clicking a chip hides/shows
 *      that type, "Only unreviewed" toggles the pending-only filter,
 *      and "Reset" clears every filter.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { DocxViewer } from './DocxViewer';
import { EntityLegend, type LegendStatus } from './EntityLegend';
import { EntityPopover, type EntityPopoverAnchor } from './EntityPopover';
import {
  SelectionToolbar,
  type SelectionInfo,
} from './SelectionToolbar';
import { DocxPane } from '@/lib/docx-pane';
import {
  groupEntityCounts,
  rightOffsetsToLeft,
  type InteractiveEntity,
  type OverlayEntity,
} from '@/lib/entity-overlay';
import { diffWords } from '@/lib/word-diff';
import {
  addCustomEntity,
  anonymizeText,
  API_URL,
  deanonymizeDocx,
  deepScanText,
  downloadBlob,
  exportAnonymizedDocx,
  exportDeanonymizedDocx,
  getCachedAnonymization,
  getDocumentWorkflow,
  importResponseDocx,
  setDocumentWorkflowStage,
  type DeanonymizeDocxResult,
  type Restoration,
  type WorkflowStage,
} from '@/lib/api';
import { useLocale } from '@/hooks/useLocale';
import type { EntityTypeCode } from '@/lib/entity-types';

interface SplitWorkspaceProps {
  documentId: string;
  documentName: string;
  onClose: () => void;
  onAppendFiles?: (files: File[]) => Promise<void> | void;
  /** Pre-existing entities for this session (from page-level cache).
   *  When non-empty, we skip the auto-anonymize step on mount and render
   *  these directly. Lets the user re-open a document without re-firing
   *  the anonymization pipeline. */
  initialEntities?: InteractiveEntity[];
  /** Notify the parent (page.tsx) that anonymization completed so it can
   *  cache the entity list under this sessionId. Caller stores the cache
   *  keyed by sessionId so a later doc switch restores from memory. */
  onAnonymizationComplete?: (sessionId: string, entities: InteractiveEntity[]) => void;
}

const ACTIVE_CLASS = 'cleargate-entity--active';

// Document zoom limits. Step is fine-grained enough that Ctrl+wheel
// feels smooth on a typical mouse, but coarse enough that the rounding
// to whole-percent display stays accurate.
const MIN_SCALE = 0.5;
const MAX_SCALE = 2.0;
const SCALE_STEP = 0.1;

type DeepScanSummary = {
  added: number;
  removed: number;
  suggestions: number;
};

type DeepScanAction = 'add' | 'remove';

type DeepScanLayer = {
  base: InteractiveEntity[];
  suggestions: InteractiveEntity[];
  removals: InteractiveEntity[];
  enabledSuggestionKeys: Set<string>;
  enabledRemovalKeys: Set<string>;
} | null;

type CompareMutation =
  | { kind: 'ins'; start: number; end: number; text: string }
  | { kind: 'move-ins'; start: number; end: number; text: string }
  | { kind: 'del'; at: number; text: string }
  | { kind: 'move-del'; at: number; text: string };

const entitySignature = (
  entity: Pick<InteractiveEntity, 'start' | 'end' | 'entity_type' | 'text'>,
) => `${entity.start}:${entity.end}:${entity.entity_type}:${entity.text}`;

function comparePosition(mutation: CompareMutation): number {
  return mutation.kind === 'ins' || mutation.kind === 'move-ins'
    ? mutation.start
    : mutation.at;
}

function diffMarkerClass(kind: CompareMutation['kind']): string {
  if (kind === 'ins') return 'cleargate-diff-ins';
  if (kind === 'del') return 'cleargate-diff-del';
  return 'cleargate-diff-move';
}

function wrapRangeWithDiffMarker(
  range: Range,
  kind: Extract<CompareMutation['kind'], 'ins' | 'move-ins'>,
): boolean {
  const doc = range.startContainer.ownerDocument;
  if (!doc) return false;
  const marker = doc.createElement(kind === 'ins' ? 'ins' : 'span');
  marker.className = diffMarkerClass(kind);
  if (kind === 'move-ins') marker.dataset.diffMove = 'to';
  const fragment = range.extractContents();
  marker.appendChild(fragment);
  range.insertNode(marker);
  return true;
}

function insertDeletedDiffMarker(
  container: HTMLElement,
  at: number,
  text: string,
  pane: DocxPane,
  kind: Extract<CompareMutation['kind'], 'del' | 'move-del'> = 'del',
): boolean {
  const map = pane.getAnchorMap();
  const pos = map.toDomPosition(Math.min(at, map.plainText.length));
  if (!pos) return false;
  const doc = container.ownerDocument;
  const marker = doc.createElement(kind === 'del' ? 'del' : 'span');
  marker.className = diffMarkerClass(kind);
  if (kind === 'move-del') marker.dataset.diffMove = 'from';
  marker.textContent = text;
  const range = doc.createRange();
  range.setStart(pos.node, pos.offset);
  range.collapse(true);
  range.insertNode(marker);
  return true;
}

function normalizeMovedText(text: string): string {
  return text
    .split(/\n+/)
    .map((line) => line.replace(/^\s*\d+(?:\.\d+)*\.?\s*/, ''))
    .join(' ')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function moveSimilarity(a: string, b: string): number {
  const aTokens = new Set(a.split(' ').filter((token) => token.length > 2));
  const bTokens = new Set(b.split(' ').filter((token) => token.length > 2));
  if (aTokens.size === 0 || bTokens.size === 0) return 0;
  let intersection = 0;
  for (const token of aTokens) {
    if (bTokens.has(token)) intersection++;
  }
  return intersection / Math.max(aTokens.size, bTokens.size);
}

const MOVE_BLOCK_MIN_NORMALIZED_LENGTH = 80;
const FUZZY_MOVE_MIN_NORMALIZED_LENGTH = 120;
const MOVE_BLOCK_MIN_TOKENS = 10;

type TextBlock = {
  text: string;
  start: number;
  end: number;
  index: number;
  normalized: string;
};

type RawTextLine = {
  text: string;
  start: number;
  end: number;
  trimmed: string;
  trimStart: number;
  trimEnd: number;
};

function splitTextLines(text: string): RawTextLine[] {
  const lines: RawTextLine[] = [];
  let start = 0;
  const parts = text.split('\n');
  for (const part of parts) {
    const end = start + part.length;
    const leading = part.match(/^\s*/)?.[0].length ?? 0;
    const trailing = part.match(/\s*$/)?.[0].length ?? 0;
    lines.push({
      text: part,
      start,
      end,
      trimmed: part.trim(),
      trimStart: start + leading,
      trimEnd: end - trailing,
    });
    start = end + 1;
  }
  return lines;
}

function isTopLevelNumberedLine(trimmed: string): boolean {
  return /^\d+\.(?!\d)\s+\S/u.test(trimmed) || /^\d+\.$/u.test(trimmed);
}

function isSubClauseLine(trimmed: string): boolean {
  return /^\d+\.\d+(?:\.\d+)*\s+\S/u.test(trimmed);
}

function normalizedTokenCount(normalized: string): number {
  return normalized.split(' ').filter(Boolean).length;
}

function pushLogicalMoveBlock(
  blocks: TextBlock[],
  text: string,
  lines: RawTextLine[],
  startLine: number,
  endLineExclusive: number,
) {
  const meaningfulLines = lines
    .slice(startLine, endLineExclusive)
    .filter((line) => line.trimmed.length > 0);
  if (meaningfulLines.length === 0) return;

  const blockStart = meaningfulLines[0].trimStart;
  const blockEnd = meaningfulLines[meaningfulLines.length - 1].trimEnd;
  if (blockEnd <= blockStart) return;

  const blockText = text.slice(blockStart, blockEnd);
  const normalized = normalizeMovedText(blockText);
  const hasSubClause = meaningfulLines.some((line) => isSubClauseLine(line.trimmed));
  const enoughBody =
    normalized.length >= MOVE_BLOCK_MIN_NORMALIZED_LENGTH &&
    normalizedTokenCount(normalized) >= MOVE_BLOCK_MIN_TOKENS;
  if (!hasSubClause || !enoughBody) return;

  blocks.push({
    text: blockText,
    start: blockStart,
    end: blockEnd,
    index: blocks.length,
    normalized,
  });
}

function collectTextBlocks(text: string): TextBlock[] {
  const blocks: TextBlock[] = [];
  const lines = splitTextLines(text);
  let index = 0;
  while (index < lines.length) {
    if (!isTopLevelNumberedLine(lines[index].trimmed)) {
      index++;
      continue;
    }
    const startLine = index;
    index++;
    while (
      index < lines.length &&
      !isTopLevelNumberedLine(lines[index].trimmed)
    ) {
      index++;
    }
    pushLogicalMoveBlock(blocks, text, lines, startLine, index);
  }
  return blocks;
}

function findMoveSourceAnchor(
  oldBlocks: TextBlock[],
  newByNorm: Map<string, TextBlock[]>,
  oldIndex: number,
  newTextLength: number,
): number {
  for (let i = oldIndex - 1; i >= 0; i--) {
    const block = oldBlocks[i];
    const newMatches = newByNorm.get(block.normalized);
    if (newMatches?.length === 1) {
      return Math.min(newMatches[0].end + 1, newTextLength);
    }
  }
  for (let i = oldIndex + 1; i < oldBlocks.length; i++) {
    const block = oldBlocks[i];
    const newMatches = newByNorm.get(block.normalized);
    if (newMatches?.length === 1) {
      return Math.max(0, newMatches[0].start - 1);
    }
  }
  return 0;
}

function hasOrderInversion(
  oldBlock: TextBlock,
  newBlock: TextBlock,
  oldBlocks: TextBlock[],
  oldByNorm: Map<string, TextBlock[]>,
  newByNorm: Map<string, TextBlock[]>,
): boolean {
  for (let i = oldBlock.index - 1; i >= 0; i--) {
    const previous = oldBlocks[i];
    if (oldByNorm.get(previous.normalized)?.length !== 1) continue;
    const previousNew = newByNorm.get(previous.normalized);
    if (previousNew?.length === 1) {
      return previousNew[0].index > newBlock.index;
    }
  }
  for (let i = oldBlock.index + 1; i < oldBlocks.length; i++) {
    const next = oldBlocks[i];
    if (oldByNorm.get(next.normalized)?.length !== 1) continue;
    const nextNew = newByNorm.get(next.normalized);
    if (nextNew?.length === 1) {
      return nextNew[0].index < newBlock.index;
    }
  }
  return false;
}

function overlapsRange(start: number, end: number, rangeStart: number, rangeEnd: number): boolean {
  return start < rangeEnd && end > rangeStart;
}

function isSubstantialMoveText(normalized: string, minLength = MOVE_BLOCK_MIN_NORMALIZED_LENGTH): boolean {
  return (
    normalized.length >= minLength &&
    normalizedTokenCount(normalized) >= MOVE_BLOCK_MIN_TOKENS
  );
}

function findMovedBlockRanges(
  oldText: string,
  newText: string,
  existingMutations: CompareMutation[],
): CompareMutation[] {
  const oldBlocks = collectTextBlocks(oldText);
  const newBlocks = collectTextBlocks(newText);
  const oldByNorm = new Map<string, TextBlock[]>();
  const newByNorm = new Map<string, TextBlock[]>();
  for (const block of oldBlocks) {
    oldByNorm.set(block.normalized, [...(oldByNorm.get(block.normalized) ?? []), block]);
  }
  for (const block of newBlocks) {
    newByNorm.set(block.normalized, [...(newByNorm.get(block.normalized) ?? []), block]);
  }

  const hasExistingMovedSource = (normalized: string) =>
    existingMutations.some((mutation) => (
      mutation.kind === 'move-del' &&
      normalizeMovedText(mutation.text) === normalized
    ));

  const candidates: Array<{ oldBlock: TextBlock; newBlock: TextBlock }> = [];
  for (const [normalized, oldMatches] of oldByNorm) {
    const newMatches = newByNorm.get(normalized);
    if (!newMatches || oldMatches.length !== 1 || newMatches.length !== 1) continue;
    const oldBlock = oldMatches[0];
    const newBlock = newMatches[0];
    const positionDelta = Math.abs(oldBlock.start - newBlock.start);
    if (
      positionDelta < 60 ||
      !hasOrderInversion(oldBlock, newBlock, oldBlocks, oldByNorm, newByNorm)
    ) {
      continue;
    }
    candidates.push({ oldBlock, newBlock });
  }

  const moves: CompareMutation[] = [];
  for (const { oldBlock, newBlock } of candidates) {
    moves.push({
      kind: 'move-ins',
      start: newBlock.start,
      end: newBlock.end,
      text: newBlock.text,
    });
    if (!hasExistingMovedSource(oldBlock.normalized)) {
      moves.push({
        kind: 'move-del',
        at: findMoveSourceAnchor(
          oldBlocks,
          newByNorm,
          oldBlock.index,
          newText.length,
        ),
        text: oldBlock.text,
      });
    }
  }
  return moves;
}

function filterMutationsCoveredBySemanticMoves(mutations: CompareMutation[]): CompareMutation[] {
  const moveInsertRanges = mutations
    .filter((mutation): mutation is Extract<CompareMutation, { kind: 'move-ins' }> =>
      mutation.kind === 'move-ins',
    )
    .map((mutation) => ({ start: mutation.start, end: mutation.end }));
  const moveSourceNorms = mutations
    .filter((mutation): mutation is Extract<CompareMutation, { kind: 'move-del' }> =>
      mutation.kind === 'move-del',
    )
    .map((mutation) => normalizeMovedText(mutation.text))
    .filter((normalized) => isSubstantialMoveText(normalized));

  if (moveInsertRanges.length === 0 && moveSourceNorms.length === 0) return mutations;

  return mutations.filter((mutation) => {
    if (mutation.kind === 'ins') {
      return !moveInsertRanges.some((range) =>
        overlapsRange(mutation.start, mutation.end, range.start, range.end),
      );
    }
    if (mutation.kind === 'del') {
      const normalized = normalizeMovedText(mutation.text);
      if (!normalized) return true;
      return !moveSourceNorms.some((sourceNorm) => (
        sourceNorm.includes(normalized) || normalized.includes(sourceNorm)
      ));
    }
    return true;
  });
}

function markLikelyMoves(mutations: CompareMutation[]): CompareMutation[] {
  const next = mutations.map((mutation) => ({ ...mutation }));
  const deletions = next
    .map((mutation, index) => ({ mutation, index }))
    .filter((item): item is { mutation: Extract<CompareMutation, { kind: 'del' }>; index: number } =>
      item.mutation.kind === 'del' &&
      isSubstantialMoveText(normalizeMovedText(item.mutation.text), FUZZY_MOVE_MIN_NORMALIZED_LENGTH),
    );
  const insertions = next
    .map((mutation, index) => ({ mutation, index }))
    .filter((item): item is { mutation: Extract<CompareMutation, { kind: 'ins' }>; index: number } =>
      item.mutation.kind === 'ins' &&
      isSubstantialMoveText(normalizeMovedText(item.mutation.text), FUZZY_MOVE_MIN_NORMALIZED_LENGTH),
    );
  const usedInsertions = new Set<number>();

  for (const deletion of deletions.sort(
    (a, b) => normalizeMovedText(b.mutation.text).length - normalizeMovedText(a.mutation.text).length,
  )) {
    const delNorm = normalizeMovedText(deletion.mutation.text);
    let bestIndex = -1;
    let bestScore = 0;
    for (const insertion of insertions) {
      if (usedInsertions.has(insertion.index)) continue;
      const insNorm = normalizeMovedText(insertion.mutation.text);
      const exact = delNorm === insNorm;
      const score = exact ? 1 : moveSimilarity(delNorm, insNorm);
      if (score > bestScore) {
        bestScore = score;
        bestIndex = insertion.index;
      }
    }
    if (bestIndex !== -1 && bestScore >= 0.82) {
      next[deletion.index] = { ...deletion.mutation, kind: 'move-del' };
      const insertion = next[bestIndex] as Extract<CompareMutation, { kind: 'ins' }>;
      next[bestIndex] = { ...insertion, kind: 'move-ins' };
      usedInsertions.add(bestIndex);
    }
  }

  return next;
}

function applyFormattedCompareDiff(
  pane: DocxPane,
  oldText: string,
  newText: string,
): number {
  const container = pane.getContainer();
  const mutations: CompareMutation[] = [];
  let oldOffset = 0;
  let newOffset = 0;

  for (const op of diffWords(oldText, newText)) {
    if (op.kind === 'eq') {
      oldOffset += op.text.length;
      newOffset += op.text.length;
    } else if (op.kind === 'ins') {
      if (op.text.trim()) {
        mutations.push({
          kind: 'ins',
          start: newOffset,
          end: newOffset + op.text.length,
          text: op.text,
        });
      }
      newOffset += op.text.length;
    } else {
      if (op.text.trim()) {
        mutations.push({ kind: 'del', at: newOffset, text: op.text });
      }
      oldOffset += op.text.length;
    }
  }

  mutations.push(...findMovedBlockRanges(oldText, newText, mutations));

  let applied = 0;
  const ordered = markLikelyMoves(filterMutationsCoveredBySemanticMoves(mutations)).sort(
    (a, b) => comparePosition(b) - comparePosition(a),
  );
  for (const mutation of ordered) {
    try {
      if (mutation.kind === 'ins' || mutation.kind === 'move-ins') {
        const map = pane.getAnchorMap();
        const range = map.toRange(mutation.start, mutation.end);
        if (range && wrapRangeWithDiffMarker(range, mutation.kind)) applied++;
      } else if (insertDeletedDiffMarker(container, mutation.at, mutation.text, pane, mutation.kind)) {
        applied++;
      }
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[Cleargate] compare marker skipped', mutation, e);
    }
  }
  return applied;
}

export function SplitWorkspace({
  documentId,
  documentName,
  onClose,
  onAppendFiles,
  // initialEntities + onAnonymizationComplete are part of the v0.4.0
  // page-level entity cache contract. They're optional so the component
  // still works for callers that don't care about cross-session caching;
  // the actual hydration / on-complete dispatch is hooked up inside the
  // detection effect (added in a follow-up patch).
  initialEntities = [],
  onAnonymizationComplete,
}: SplitWorkspaceProps) {
  const { t } = useLocale();

  // Pane containers + DocxPane wrappers. The DocxPane is the single
  // owner of the (cleanHtml, anchorMap) state for each pane; callers
  // can never get a stale anchor map because every read goes through
  // pane.getAnchorMap() which builds fresh against the live DOM.
  // The bare container ref is kept alongside because the wheel/zoom/
  // click handlers below need .contains() checks against a plain
  // HTMLElement and benefit from not going through a method call.
  const leftContainerRef = useRef<HTMLElement | null>(null);
  const rightContainerRef = useRef<HTMLElement | null>(null);
  const leftPaneRef = useRef<DocxPane | null>(null);
  const rightPaneRef = useRef<DocxPane | null>(null);
  // Holds the latest restoration list so handleAnonymizedReady (which
  // re-fires when the right pane reloads the deanonymized DOCX) can
  // apply overlays without relying on stale closure state.
  const restorationsRef = useRef<Restoration[]>([]);

  const [status, setStatus] = useState<LegendStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [entities, setEntities] = useState<InteractiveEntity[]>([]);
  const [progressValue, setProgressValue] = useState(0);

  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [onlyUnconfirmed, setOnlyUnconfirmed] = useState(false);

  const [popover, setPopover] = useState<EntityPopoverAnchor | null>(null);
  const [selection, setSelection] = useState<SelectionInfo | null>(null);
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);

  const [bothReady, setBothReady] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [deepScanBusy, setDeepScanBusy] = useState(false);
  const [deepScanError, setDeepScanError] = useState<string | null>(null);
  const [deepScanProgress, setDeepScanProgress] = useState(0);
  const [deepScanSummary, setDeepScanSummary] = useState<DeepScanSummary | null>(null);
  const [deepScanLayer, setDeepScanLayer] = useState<DeepScanLayer>(null);
  const [deepScanActive, setDeepScanActive] = useState(false);
  const restoreStartedRef = useRef(false);
  const workflowRestoreStartedRef = useRef(false);

  // Phase 1 round-trip: import response -> deanonymize -> export
  const responseFileRef = useRef<HTMLInputElement | null>(null);
  const appendFileRef = useRef<HTMLInputElement | null>(null);
  const [appendBusy, setAppendBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [responseImported, setResponseImported] = useState(false);
  const [responseViewActive, setResponseViewActive] = useState(false);
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage>('anonymized');
  const [deanonymizeBusy, setDeanonymizeBusy] = useState(false);
  const [manualResolutionBusy, setManualResolutionBusy] = useState(false);
  const [deanonymizeError, setDeanonymizeError] = useState<string | null>(null);
  const [deanonymizeResult, setDeanonymizeResult] =
    useState<DeanonymizeDocxResult | null>(null);
  const [exportDeanonymizedBusy, setExportDeanonymizedBusy] = useState(false);
  const [exportDeanonymizedError, setExportDeanonymizedError] =
    useState<string | null>(null);
  // Manual resolutions the user entered for unresolved placeholders.
  // Persisted in state so the export handler can re-send them.
  const [manualResolutions, setManualResolutions] = useState<
    Array<{ placeholder: string; value: string }>
  >([]);
  const [unresolvedValues, setUnresolvedValues] = useState<Record<string, string>>({});

  const cacheManualResolutions = useCallback(
    (resolutions: Array<{ placeholder: string; value: string }>) => {
      setManualResolutions(resolutions);
      setUnresolvedValues(
        Object.fromEntries(
          resolutions.map((resolution) => [
            resolution.placeholder,
            resolution.value,
          ]),
        ),
      );
    },
    [],
  );
  // URL override for right pane: after deanonymize, show the deanonymized doc
  const [rightPaneUrl, setRightPaneUrl] = useState<string | null>(null);
  const rightPaneUrlRef = useRef<string | null>(null);
  useEffect(() => {
    rightPaneUrlRef.current = rightPaneUrl;
  }, [rightPaneUrl]);

  // Compare-with-original mode (Word-style Track Changes).
  // When ON, the right pane's DOM is replaced in-place with a word-level
  // diff overlay. Toggling OFF restores the docx-preview render via
  // `pane.rerender(overlays, 'highlight')` using the stashed restorations.
  const [compareMode, setCompareMode] = useState(false);
  const compareModeRef = useRef(false);
  useEffect(() => {
    compareModeRef.current = compareMode;
  }, [compareMode]);

  // Synchronized document zoom (both panes scale together).
  // Implemented via the CSS `zoom` property on the docx-preview
  // container, NOT via `transform: scale()`. Two reasons:
  //   - `zoom` cooperates with the surrounding scroll container so
  //     scrollbars adapt automatically; `transform: scale` does not.
  //   - `zoom` does not change the underlying DOM, so the existing
  //     anchor maps and selection offsets remain valid as-is.
  const [docScale, setDocScale] = useState<number>(1);
  const [showZoomPill, setShowZoomPill] = useState(false);
  const zoomPillTimerRef = useRef<number | null>(null);
  const flashZoomPill = useCallback(() => {
    setShowZoomPill(true);
    if (zoomPillTimerRef.current !== null) {
      window.clearTimeout(zoomPillTimerRef.current);
    }
    zoomPillTimerRef.current = window.setTimeout(() => {
      setShowZoomPill(false);
      zoomPillTimerRef.current = null;
    }, 1100);
  }, []);
  const adjustScale = useCallback((delta: number) => {
    setDocScale((prev) => {
      const next = Math.round((prev + delta) * 100) / 100;
      return Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
    });
    flashZoomPill();
  }, [flashZoomPill]);
  const resetScale = useCallback(() => {
    setDocScale(1);
    flashZoomPill();
  }, [flashZoomPill]);

  // The entity set actually drawn on screen after filters are applied.
  const visibleEntities = useMemo(() => {
    return entities.filter((e) => {
      if (hiddenTypes.has(e.entity_type)) return false;
      if (onlyUnconfirmed && e.state !== 'pending') return false;
      return true;
    });
  }, [entities, hiddenTypes, onlyUnconfirmed]);

  // Mirror of visibleEntities in a ref so the mouseup-based selection
  // handler can read the latest list without re-attaching its
  // document-level event listeners on every filter/state change.
  const visibleEntitiesRef = useRef<InteractiveEntity[]>([]);
  useEffect(() => {
    visibleEntitiesRef.current = visibleEntities;
  }, [visibleEntities]);

  const counts = useMemo(() => groupEntityCounts(entities), [entities]);

  // ─── pane lifecycle ──────────────────────────────────────────────
  //
  // IMPORTANT: we flip `bothReady` to true from inside the ready
  // handlers AFTER checking that the OTHER pane is also ready. This
  // makes the "both panes rendered" transition explicit and removes
  // the race condition where the detection effect could fire against
  // stale refs (e.g. if a pane re-rendered between status updates).

  const markBothReadyIfPossible = useCallback(() => {
    if (
      leftContainerRef.current &&
      rightContainerRef.current &&
      leftPaneRef.current &&
      rightPaneRef.current
    ) {
      setBothReady(true);
    }
  }, []);

  const handleOriginalReady = useCallback(
    (container: HTMLElement) => {
      leftContainerRef.current = container;
      const pane = new DocxPane(container);
      leftPaneRef.current = pane;
      // eslint-disable-next-line no-console
      console.info('[Cleargate] original pane ready', {
        chars: pane.getPlainText().length,
      });
      markBothReadyIfPossible();
    },
    [markBothReadyIfPossible],
  );

  // Apply restoration-value overlays to the right pane by text-searching
  // its plain text for each real_value and building InteractiveEntity
  // ranges. Shared between the initial deanonymized-preview render and
  // the "exit compare mode" restore path.
  const applyRestorationOverlays = useCallback((pane: DocxPane) => {
    const restorations = restorationsRef.current;
    if (restorations.length === 0) return;
    const plain = pane.getPlainText();
    const overlays: InteractiveEntity[] = [];
    let idCounter = 0;
    // Sort by length DESC so longer strings match before substrings
    // (e.g. "Петров А. Н." before "Петров").
    const sorted = [...restorations].sort(
      (a, b) => b.real_value.length - a.real_value.length,
    );
    const claimed: Array<[number, number]> = [];
    const overlaps = (s: number, e: number) =>
      claimed.some(([cs, ce]) => s < ce && e > cs);
    for (const r of sorted) {
      if (!r.real_value) continue;
      let from = 0;
      while (from <= plain.length) {
        const idx = plain.indexOf(r.real_value, from);
        if (idx === -1) break;
        const end = idx + r.real_value.length;
        if (!overlaps(idx, end)) {
          overlays.push({
            id: `restoration-${idCounter++}`,
            text: r.real_value,
            entity_type: r.entity_type,
            start: idx,
            end,
            score: 1,
            state: 'accepted',
            metadata: { placeholder: r.placeholder },
          });
          claimed.push([idx, end]);
        }
        from = end;
      }
    }
    if (overlays.length > 0) {
      try {
        pane.rerender(overlays, { mode: 'highlight' });
        // eslint-disable-next-line no-console
        console.info('[Cleargate] restoration overlays applied', {
          count: overlays.length,
        });
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[Cleargate] restoration overlay render failed', e);
      }
    }
  }, []);

  const handleAnonymizedReady = useCallback(
    (container: HTMLElement) => {
      rightContainerRef.current = container;
      const pane = new DocxPane(container);
      rightPaneRef.current = pane;
      // eslint-disable-next-line no-console
      console.info('[Cleargate] anonymized pane ready');

      // If we just switched to the deanonymized preview, overlay the
      // restored values using the same interactive entity system as the
      // left pane.
      if (rightPaneUrlRef.current) {
        if (!compareModeRef.current) applyRestorationOverlays(pane);
      } else if (visibleEntitiesRef.current.length > 0) {
        pane.rerender(visibleEntitiesRef.current, { mode: 'placeholder' });
      }

      markBothReadyIfPossible();
    },
    [markBothReadyIfPossible, applyRestorationOverlays],
  );

  // Reset everything when the document changes.
  //
  // Thanks to `key={sessionId}` in the parent we now remount on every
  // document switch, so this effect is primarily a belt-and-braces
  // cleanup; keeping it makes hot reload during dev saner.
  useEffect(() => {
    setStatus('idle');
    setError(null);
    setEntities([]);
    setProgressValue(0);
    setHiddenTypes(new Set());
    setOnlyUnconfirmed(false);
    setPopover(null);
    setSelection(null);
    setBothReady(false);
    restoreStartedRef.current = false;
    workflowRestoreStartedRef.current = false;
    rightContainerRef.current?.classList.remove('cleargate-compare');
    leftContainerRef.current = null;
    rightContainerRef.current = null;
    leftPaneRef.current = null;
    rightPaneRef.current = null;
    restorationsRef.current = [];
    setDocScale(1);
    cacheManualResolutions([]);
    setCompareMode(false);
    setWorkflowStage('anonymized');
    setResponseImported(false);
    setResponseViewActive(false);
    setRightPaneUrl(null);
    setDeanonymizeResult(null);
    setDeanonymizeError(null);
    setManualResolutionBusy(false);
    setAppendBusy(false);
    setDeepScanBusy(false);
    setDeepScanError(null);
    setDeepScanProgress(0);
    setDeepScanSummary(null);
    setDeepScanLayer(null);
    setDeepScanActive(false);
    if (zoomPillTimerRef.current !== null) {
      window.clearTimeout(zoomPillTimerRef.current);
      zoomPillTimerRef.current = null;
    }
    setShowZoomPill(false);
  }, [documentId]);

  useEffect(() => {
    return () => {
      if (zoomPillTimerRef.current !== null) {
        window.clearTimeout(zoomPillTimerRef.current);
      }
    };
  }, []);

  // ─── document zoom: apply, wheel, keyboard ───────────────────────
  //
  // The zoom is applied imperatively so the DocxViewer does not need
  // to know about it. We re-apply on every change AND on every
  // bothReady transition because the underlying container element
  // gets replaced when a document switch remounts the panes.
  useEffect(() => {
    const apply = (el: HTMLElement | null) => {
      if (!el) return;
      // `zoom` is a non-standard CSS property that Chromium and
      // Firefox both implement; it does not appear in TypeScript's
      // CSSStyleDeclaration typings, so we set it via setProperty.
      el.style.setProperty('zoom', String(docScale));
    };
    apply(leftContainerRef.current);
    apply(rightContainerRef.current);
  }, [docScale, bothReady, rightPaneUrl]);

  // Ctrl + mouse wheel inside either pane changes the document zoom
  // without zooming the surrounding app chrome. preventDefault() is
  // required to suppress the browser's native page zoom; that needs
  // a non-passive listener.
  useEffect(() => {
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      const target = e.target as Node | null;
      const inLeft = target ? leftContainerRef.current?.contains(target) : false;
      const inRight = target ? rightContainerRef.current?.contains(target) : false;
      if (!inLeft && !inRight) return;
      e.preventDefault();
      adjustScale(e.deltaY < 0 ? SCALE_STEP : -SCALE_STEP);
    };
    document.addEventListener('wheel', onWheel, { passive: false });
    return () => document.removeEventListener('wheel', onWheel);
  }, [adjustScale]);

  // Ctrl+0 / Ctrl++ / Ctrl+- keyboard shortcuts. We listen at the
  // window level so they work no matter which element has focus,
  // but we only act when one of the docx panes is on screen.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      if (e.key === '0') {
        e.preventDefault();
        resetScale();
      } else if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        adjustScale(SCALE_STEP);
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        adjustScale(-SCALE_STEP);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [adjustScale, resetScale]);

  // ─── explicit rerender helper ─────────────────────────────────────
  //
  // Called directly by the detection effect and by every state-change
  // handler (accept / reject / add / …). Re-rendering is driven
  // imperatively instead of via a `[visibleEntities]` useEffect so we
  // control exactly when the panes are redrawn and avoid the subtle
  // effect-ordering race that used to require a manual reload.
  const rerenderBothPanes = useCallback(
    (entitiesToDraw: InteractiveEntity[]) => {
      const leftPane = leftPaneRef.current;
      const rightPane = rightPaneRef.current;
      if (!leftPane || !rightPane) {
        // eslint-disable-next-line no-console
        console.warn('[Cleargate] rerender skipped — panes not ready');
        return;
      }
      leftPane.rerender(entitiesToDraw, { mode: 'highlight' });
      if (rightPaneUrlRef.current) {
        if (compareModeRef.current) return;
        rightPane.rerender([], { mode: 'highlight' });
        applyRestorationOverlays(rightPane);
        return;
      }
      rightPane.rerender(entitiesToDraw, { mode: 'placeholder' });
    },
    [applyRestorationOverlays],
  );

  const toInteractiveEntities = useCallback((raw: OverlayEntity[]) => {
    return raw.map((e, idx) => ({
      ...e,
      id:
        (e.metadata?.id as string | undefined) ??
        `det-${idx}-${e.start}-${e.end}-${e.entity_type}`,
      state:
        (e.metadata?.state as InteractiveEntity['state'] | undefined) ??
        'pending',
    }));
  }, []);

  const applyEntities = useCallback(
    (nextEntities: InteractiveEntity[]) => {
      setEntities(nextEntities);
      setStatus(nextEntities.length > 0 ? 'detected' : 'idle');
      rerenderBothPanes(nextEntities);
    },
    [rerenderBothPanes],
  );

  const responsePreviewUrl = useCallback(
    () => `${API_URL}/api/documents/${encodeURIComponent(documentId)}/response-raw?t=${Date.now()}`,
    [documentId],
  );

  const leaveCompareMode = useCallback(() => {
    rightContainerRef.current?.classList.remove('cleargate-compare');
    setCompareMode(false);
  }, []);

  const showAnonymizedWorkflow = useCallback(async () => {
    leaveCompareMode();
    setResponseViewActive(false);
    setWorkflowStage('anonymized');
    setRightPaneUrl(null);
    setDeanonymizeError(null);
    try {
      const state = await setDocumentWorkflowStage(documentId, 'anonymized');
      setWorkflowStage(state.stage);
      setResponseImported(state.response_imported);
      cacheManualResolutions(state.manual_resolutions ?? []);
      if (state.deanonymize_result) {
        setDeanonymizeResult(state.deanonymize_result);
        restorationsRef.current = state.deanonymize_result.restorations ?? [];
      }
    } catch (e) {
      // Keep the visual rollback local even if persistence failed.
      // eslint-disable-next-line no-console
      console.warn('[Cleargate] workflow rollback persist failed', e);
    }
  }, [documentId, leaveCompareMode]);

  const showDeanonymizedWorkflow = useCallback(async () => {
    leaveCompareMode();
    setDeanonymizeError(null);
    try {
      const state = await setDocumentWorkflowStage(documentId, 'deanonymized');
      const result = state.deanonymize_result ?? deanonymizeResult;
      if (!result) {
        throw new Error('No saved deanonymization result');
      }
      setWorkflowStage(state.stage);
      setResponseImported(true);
      cacheManualResolutions(state.manual_resolutions ?? []);
      setDeanonymizeResult(result);
      restorationsRef.current = result.restorations ?? [];
      setResponseViewActive(true);
      setRightPaneUrl(responsePreviewUrl());
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[Cleargate] workflow restore failed', e);
      setDeanonymizeError(e instanceof Error ? e.message : String(e));
    }
  }, [
    deanonymizeResult,
    documentId,
    leaveCompareMode,
    responsePreviewUrl,
  ]);

  // ─── restore cached anonymization ────────────────────────────────
  useEffect(() => {
    if (!bothReady) return;
    if (restoreStartedRef.current) return;
    restoreStartedRef.current = true;

    if (initialEntities.length > 0) {
      applyEntities(initialEntities);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const cached = await getCachedAnonymization(documentId);
        if (cancelled || !cached) return;
        const interactive = toInteractiveEntities(
          (cached.entities as OverlayEntity[]) ?? [],
        );
        applyEntities(interactive);
        onAnonymizationComplete?.(documentId, interactive);
      } catch (e) {
        if (!cancelled) {
          // eslint-disable-next-line no-console
          console.warn('[Cleargate] cached anonymization restore failed', e);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    applyEntities,
    bothReady,
    documentId,
    initialEntities,
    onAnonymizationComplete,
    toInteractiveEntities,
  ]);

  // Restore persisted LLM-response/deanonymization view state after the
  // base anonymization overlays are available.
  useEffect(() => {
    if (!bothReady || status !== 'detected') return;
    if (workflowRestoreStartedRef.current) return;
    workflowRestoreStartedRef.current = true;

    let cancelled = false;
    (async () => {
      try {
        const state = await getDocumentWorkflow(documentId);
        if (cancelled || !state) return;
        setWorkflowStage(state.stage);
        setResponseImported(state.response_imported);
        cacheManualResolutions(state.manual_resolutions ?? []);
        if (state.deanonymize_result) {
          setDeanonymizeResult(state.deanonymize_result);
          restorationsRef.current = state.deanonymize_result.restorations ?? [];
        }
        if (state.stage === 'deanonymized' && state.deanonymized_available) {
          setResponseViewActive(true);
          setRightPaneUrl(responsePreviewUrl());
        } else {
          setResponseViewActive(false);
          setRightPaneUrl(null);
        }
      } catch (e) {
        if (!cancelled) {
          // eslint-disable-next-line no-console
          console.warn('[Cleargate] workflow state restore failed', e);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bothReady, documentId, responsePreviewUrl, status]);

  // ─── explicit detection ──────────────────────────────────────────
  const runAnonymization = useCallback(async () => {
    if (!bothReady || status === 'detecting') return;
    const leftPane = leftPaneRef.current;
    if (!leftPane) return;
    const plainText = leftPane.getPlainText();

    setStatus('detecting');
    setProgressValue(8);
    setError(null);
    setDeepScanLayer(null);
    setDeepScanActive(false);
    setDeepScanSummary(null);
    setDeepScanError(null);
    try {
      // eslint-disable-next-line no-console
      console.info('[Cleargate] anonymize start', {
        documentId,
        chars: plainText.length,
      });
      const response = await anonymizeText(documentId, plainText);
      // eslint-disable-next-line no-console
      console.info('[Cleargate] anonymize response', {
        entities: response.entities?.length ?? 0,
      });
      const interactive = toInteractiveEntities(
        (response.entities as OverlayEntity[]) ?? [],
      );
      setProgressValue(100);
      applyEntities(interactive);
      onAnonymizationComplete?.(documentId, interactive);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[Cleargate] anonymize failed', e);
      setError(e instanceof Error ? e.message : String(e));
      setStatus('error');
    }
  }, [
    applyEntities,
    bothReady,
    documentId,
    onAnonymizationComplete,
    status,
    toInteractiveEntities,
  ]);

  const mergeDeepScanSuggestions = useCallback(
    (base: InteractiveEntity[], suggestions: InteractiveEntity[]) => {
      const existing = new Set(base.map(entitySignature));
      return [
        ...base,
        ...suggestions.filter(
          (suggestion) => !existing.has(entitySignature(suggestion)),
        ),
      ].sort((a, b) => a.start - b.start);
    },
    [],
  );

  const activeDeepScanCounts = useCallback((layer: NonNullable<DeepScanLayer>) => ({
    added: layer.enabledSuggestionKeys.size,
    removed: layer.enabledRemovalKeys.size,
    suggestions: layer.suggestions.length + layer.removals.length,
  }), []);

  const buildDeepScanEntities = useCallback(
    (layer: NonNullable<DeepScanLayer>) => {
      const removalKeys = layer.enabledRemovalKeys;
      const enabledSuggestions = layer.suggestions.filter((suggestion) =>
        layer.enabledSuggestionKeys.has(entitySignature(suggestion)),
      );
      return mergeDeepScanSuggestions(
        layer.base.filter((entity) => !removalKeys.has(entitySignature(entity))),
        enabledSuggestions,
      );
    },
    [mergeDeepScanSuggestions],
  );

  const applyDeepScanLayer = useCallback(
    (layer: NonNullable<DeepScanLayer>, enabled: boolean) => {
      const next = enabled ? buildDeepScanEntities(layer) : layer.base;
      applyEntities(next);
      onAnonymizationComplete?.(documentId, next);
      setDeepScanSummary(enabled ? activeDeepScanCounts(layer) : {
        added: 0,
        removed: 0,
        suggestions: layer.suggestions.length + layer.removals.length,
      });
    },
    [
      activeDeepScanCounts,
      applyEntities,
      buildDeepScanEntities,
      documentId,
      onAnonymizationComplete,
    ],
  );

  const setDeepScanLayerEnabled = useCallback(
    (enabled: boolean) => {
      if (!deepScanLayer) return;
      setDeepScanActive(enabled);
      applyDeepScanLayer(deepScanLayer, enabled);
    },
    [
      applyDeepScanLayer,
      deepScanLayer,
    ],
  );

  const toggleDeepScanProposal = useCallback(
    (action: DeepScanAction, entity: InteractiveEntity) => {
      if (!deepScanLayer) return;
      const key = entitySignature(entity);
      const nextLayer: NonNullable<DeepScanLayer> = {
        ...deepScanLayer,
        enabledSuggestionKeys: new Set(deepScanLayer.enabledSuggestionKeys),
        enabledRemovalKeys: new Set(deepScanLayer.enabledRemovalKeys),
      };
      const target =
        action === 'add'
          ? nextLayer.enabledSuggestionKeys
          : nextLayer.enabledRemovalKeys;
      if (target.has(key)) {
        target.delete(key);
      } else {
        target.add(key);
      }
      setDeepScanLayer(nextLayer);
      if (deepScanActive) {
        applyDeepScanLayer(nextLayer, true);
      } else {
        setDeepScanSummary({
          added: 0,
          removed: 0,
          suggestions: nextLayer.suggestions.length + nextLayer.removals.length,
        });
      }
    },
    [applyDeepScanLayer, deepScanActive, deepScanLayer],
  );

  const runDeepScan = useCallback(async () => {
    if (!bothReady || deepScanBusy || status === 'detecting') return;
    if (deepScanLayer) {
      setDeepScanLayerEnabled(!deepScanActive);
      return;
    }
    const leftPane = leftPaneRef.current;
    if (!leftPane) return;
    const plainText = leftPane.getPlainText();

    setDeepScanBusy(true);
    setDeepScanError(null);
    setDeepScanSummary(null);
    setDeepScanProgress(7);
    try {
      // eslint-disable-next-line no-console
      console.info('[Cleargate] deep scan start', {
        documentId,
        chars: plainText.length,
        entities: entities.length,
      });
      const response = await deepScanText(documentId, plainText, entities);
      const suggestions = toInteractiveEntities(
        (response.suggestions as OverlayEntity[] | undefined) ?? [],
      ).map((entity) => ({
        ...entity,
        source_layer: 'deep_scan',
        metadata: {
          ...entity.metadata,
          deepScanAction: 'add',
        },
      }));
      const removals = toInteractiveEntities(
        (response.removals as OverlayEntity[] | undefined) ?? [],
      ).map((entity) => ({
        ...entity,
        metadata: {
          ...entity.metadata,
          deepScanAction: 'remove',
        },
      }));
      const layer: NonNullable<DeepScanLayer> = {
        base: entities,
        suggestions,
        removals,
        enabledSuggestionKeys: new Set(suggestions.map(entitySignature)),
        enabledRemovalKeys: new Set(removals.map(entitySignature)),
      };
      setDeepScanLayer(layer);
      setDeepScanActive(true);
      setDeepScanSummary(activeDeepScanCounts(layer));
      if (suggestions.length > 0 || removals.length > 0) {
        const merged = buildDeepScanEntities(layer);
        applyEntities(merged);
        onAnonymizationComplete?.(documentId, merged);
      }
      setDeepScanProgress(100);
      // eslint-disable-next-line no-console
      console.info('[Cleargate] deep scan response', {
        entities: response.entities?.length ?? 0,
        suggestions: suggestions.length,
        removals: removals.length,
      });
      await new Promise<void>((resolve) => {
        window.setTimeout(resolve, 700);
      });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[Cleargate] deep scan failed', e);
      setDeepScanError(e instanceof Error ? e.message : String(e));
      setDeepScanProgress(0);
    } finally {
      setDeepScanBusy(false);
    }
  }, [
    applyEntities,
    activeDeepScanCounts,
    bothReady,
    buildDeepScanEntities,
    deepScanActive,
    deepScanBusy,
    deepScanLayer,
    documentId,
    entities,
    onAnonymizationComplete,
    setDeepScanLayerEnabled,
    status,
    toInteractiveEntities,
  ]);

  useEffect(() => {
    if (status !== 'detecting') return;
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const eased = 92 - 84 * Math.exp(-elapsed / 9000);
      setProgressValue((prev) => Math.max(prev, Math.min(92, Math.round(eased))));
    }, 350);
    return () => window.clearInterval(id);
  }, [status]);

  useEffect(() => {
    if (!deepScanBusy) return;
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const eased = 94 - 87 * Math.exp(-elapsed / 14000);
      setDeepScanProgress((prev) => Math.max(prev, Math.min(94, Math.round(eased))));
    }, 350);
    return () => window.clearInterval(id);
  }, [deepScanBusy]);

  const deepScanSummaryLabel = useMemo(() => {
    if (!deepScanSummary) return null;
    if (deepScanSummary.added === 0 && deepScanSummary.removed === 0) {
      return t('workspace.deepScanNoChanges');
    }
    const prefix = deepScanActive
      ? t('workspace.deepScanApplied')
      : t('workspace.deepScanDisabled');
    return `${prefix}: +${deepScanSummary.added} / -${deepScanSummary.removed}`;
  }, [deepScanActive, deepScanSummary, t]);

  const deepScanReviewItems = useMemo(() => {
    if (!deepScanLayer) return [];
    return [
      ...deepScanLayer.suggestions.map((entity) => ({
        action: 'add' as const,
        entity,
        enabled: deepScanLayer.enabledSuggestionKeys.has(entitySignature(entity)),
      })),
      ...deepScanLayer.removals.map((entity) => ({
        action: 'remove' as const,
        entity,
        enabled: deepScanLayer.enabledRemovalKeys.has(entitySignature(entity)),
      })),
    ];
  }, [deepScanLayer]);

  // ─── rerender on filter / state changes (NOT initial detection) ──
  //
  // Once detection has completed, any subsequent filter toggle or
  // entity state change should redraw both panes. We skip this until
  // detection has actually produced entities to avoid racing with the
  // explicit rerender above.
  useEffect(() => {
    if (status !== 'detected') return;
    rerenderBothPanes(visibleEntities);
  }, [visibleEntities, status, rerenderBothPanes]);

  // ─── click → popover + hover sync ────────────────────────────────
  useEffect(() => {
    const leftContainer = leftContainerRef.current;
    const rightContainer = rightContainerRef.current;
    if (!leftContainer || !rightContainer) return;

    const findMark = (target: EventTarget | null): HTMLElement | null => {
      if (!(target instanceof Element)) return null;
      return target.closest('mark.cleargate-entity') as HTMLElement | null;
    };

    const handleClick = (e: MouseEvent) => {
      const mark = findMark(e.target);
      if (!mark) return;
      const id = mark.dataset.entityId;
      if (!id) return;
      const entity = entities.find((ent) => ent.id === id);
      if (!entity) return;
      e.stopPropagation();
      setPopover({ rect: mark.getBoundingClientRect(), entity });
    };

    const markActive = (id: string, on: boolean) => {
      for (const container of [leftContainer, rightContainer]) {
        const marks = container.querySelectorAll<HTMLElement>(
          `mark.cleargate-entity[data-entity-id="${CSS.escape(id)}"]`,
        );
        marks.forEach((m) => m.classList.toggle(ACTIVE_CLASS, on));
      }
    };

    let activeId: string | null = null;
    const handleOver = (e: MouseEvent) => {
      const mark = findMark(e.target);
      const id = mark?.dataset.entityId ?? null;
      if (id === activeId) return;
      if (activeId) markActive(activeId, false);
      activeId = id;
      if (activeId) markActive(activeId, true);
    };
    const handleOut = (e: MouseEvent) => {
      // Only clear when leaving the workspace entirely.
      const related = e.relatedTarget as Node | null;
      if (related && (leftContainer.contains(related) || rightContainer.contains(related))) {
        return;
      }
      if (activeId) markActive(activeId, false);
      activeId = null;
    };

    leftContainer.addEventListener('click', handleClick);
    rightContainer.addEventListener('click', handleClick);
    leftContainer.addEventListener('mouseover', handleOver);
    rightContainer.addEventListener('mouseover', handleOver);
    leftContainer.addEventListener('mouseout', handleOut);
    rightContainer.addEventListener('mouseout', handleOut);
    return () => {
      leftContainer.removeEventListener('click', handleClick);
      rightContainer.removeEventListener('click', handleClick);
      leftContainer.removeEventListener('mouseover', handleOver);
      rightContainer.removeEventListener('mouseover', handleOver);
      leftContainer.removeEventListener('mouseout', handleOut);
      rightContainer.removeEventListener('mouseout', handleOut);
    };
    // Re-bind when entities change so the click closure sees fresh data.
  }, [entities, visibleEntities]);

  // ─── text selection → SelectionToolbar ───────────────────────────
  //
  // Unified handler that works for BOTH panes. For the left pane we
  // can read offsets directly from leftMap. For the right pane we
  // read offsets from rightMap and then translate them back to the
  // left-pane coordinate system via rightOffsetsToLeft, so the
  // backend always sees a single source of truth.
  //
  // We trigger on mouseup (the only reliable "the user finished
  // selecting" signal) and use the mouseup's clientX/clientY as the
  // anchor for the floating toolbar — that's what "под курсором"
  // means to a user used to Google Docs / Harvey.AI-style tools.
  //
  // We deliberately do NOT listen for selectionchange any more: it
  // fires constantly during a drag and was the source of the
  // "toolbar never appears" bug in iteration 3.
  useEffect(() => {
    const processSelection = (anchorX: number, anchorY: number) => {
      const leftContainer = leftContainerRef.current;
      const rightContainer = rightContainerRef.current;
      if (!leftContainer || !rightContainer) {
        // eslint-disable-next-line no-console
        console.info('[Cleargate] selection: containers not ready');
        return;
      }

      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
        setSelection(null);
        setSelectionError(null);
        return;
      }

      const range = sel.getRangeAt(0);
      const text = range.toString();
      if (text.trim().length === 0) {
        setSelection(null);
        return;
      }

      // Which pane does the selection start in?
      const startNode =
        range.startContainer.nodeType === Node.TEXT_NODE
          ? range.startContainer.parentElement
          : (range.startContainer as Element);
      if (!startNode) {
        setSelection(null);
        return;
      }

      const inLeft = leftContainer.contains(startNode);
      const inRight = rightContainer.contains(startNode);
      if (!inLeft && !inRight) {
        // Selection is in the sidebar / legend / subheader / toolbar.
        setSelection(null);
        return;
      }

      // If the selection starts inside an existing entity mark, that is
      // a click/tap on the entity itself — belongs to the popover flow.
      if (startNode.closest('mark.cleargate-entity')) {
        setSelection(null);
        return;
      }

      // If the selection *partially* overlaps an entity (start or end
      // is inside a mark, but the selection doesn't fully enclose it),
      // block it.  However, if the selection fully *contains* every
      // intersected mark, we allow it — the user wants to extend the
      // anonymization to a wider span (e.g. "г. Москва" → full address).
      const endNode =
        range.endContainer.nodeType === Node.TEXT_NODE
          ? range.endContainer.parentElement
          : (range.endContainer as Element);
      const endsInMark = endNode?.closest('mark.cleargate-entity');
      if (endsInMark) {
        // Selection ends mid-entity — partial overlap.
        setSelection(null);
        setSelectionError(t('selection.crossesPlaceholder'));
        return;
      }

      const pane: 'left' | 'right' = inLeft ? 'left' : 'right';
      let leftOffsets: { start: number; end: number } | null = null;

      if (inLeft) {
        const leftPane = leftPaneRef.current;
        if (!leftPane) {
          // eslint-disable-next-line no-console
          console.warn('[Cleargate] selection: left pane not ready');
          return;
        }
        // Always-fresh map: leftPane.getAnchorMap() rebuilds against the
        // live DOM, so even if entity overlays were re-applied between
        // mouseup and now, the offsets we compute here are honest.
        leftOffsets = leftPane.getAnchorMap().rangeToOffsets(range);
      } else {
        const rightPane = rightPaneRef.current;
        if (!rightPane) {
          // eslint-disable-next-line no-console
          console.warn('[Cleargate] selection: right pane not ready');
          return;
        }
        const rightOffsets = rightPane.getAnchorMap().rangeToOffsets(range);
        if (!rightOffsets) {
          setSelection(null);
          return;
        }
        leftOffsets = rightOffsetsToLeft(
          rightOffsets.start,
          rightOffsets.end,
          visibleEntitiesRef.current,
        );
        if (!leftOffsets) {
          // eslint-disable-next-line no-console
          console.info(
            '[Cleargate] selection: right→left translation failed (touches placeholder)',
          );
          setSelection(null);
          setSelectionError(t('selection.crossesPlaceholder'));
          return;
        }
      }

      if (!leftOffsets || leftOffsets.start === leftOffsets.end) {
        setSelection(null);
        return;
      }

      setSelection({
        anchor: { x: anchorX, y: anchorY },
        text,
        start: leftOffsets.start,
        end: leftOffsets.end,
        pane,
      });
      setSelectionError(null);
    };

    const handleMouseUp = (e: MouseEvent) => {
      // Clicks inside the floating toolbar or entity popover are
      // user interactions with those controls — do NOT re-evaluate
      // the selection (which would clear the toolbar instantly).
      const target = e.target as Element | null;
      if (
        target?.closest?.('.cleargate-selection') ||
        target?.closest?.('.cleargate-popover')
      ) {
        return;
      }
      const { clientX, clientY } = e;
      // Let the browser finalise its selection state, then read it.
      setTimeout(() => processSelection(clientX, clientY), 0);
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      // Ignore keyboard events originating inside the toolbar
      // (e.g. typing in the custom-type input field).
      if ((e.target as Element)?.closest?.('.cleargate-selection')) return;
      if (e.key === 'Escape') {
        setSelection(null);
        setSelectionError(null);
        return;
      }
      // Keyboard selection (Shift + arrows). Anchor the toolbar on
      // the centre-bottom of the current selection rect since there
      // is no cursor position to use.
      if (e.shiftKey || e.key === 'Shift') {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return;
        const rect = sel.getRangeAt(0).getBoundingClientRect();
        setTimeout(
          () =>
            processSelection(rect.left + rect.width / 2, rect.bottom),
          0,
        );
      }
    };

    document.addEventListener('mouseup', handleMouseUp);
    document.addEventListener('keyup', handleKeyUp);
    return () => {
      document.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('keyup', handleKeyUp);
    };
  }, [t]);

  // ─── handlers ────────────────────────────────────────────────────

  const closePopover = useCallback(() => setPopover(null), []);

  const accept = useCallback((target: InteractiveEntity) => {
    setEntities((prev) =>
      prev.map((e) => (e.id === target.id ? { ...e, state: 'accepted' } : e)),
    );
    setPopover(null);
  }, []);

  const reject = useCallback((target: InteractiveEntity) => {
    setEntities((prev) =>
      prev.map((e) => (e.id === target.id ? { ...e, state: 'rejected' } : e)),
    );
    setPopover(null);
  }, []);

  const changeType = useCallback(
    async (target: InteractiveEntity, newType: string) => {
      setPopover(null);
      try {
        const result = await addCustomEntity(documentId, {
          text: target.text,
          entity_type: newType,
          start: target.start,
          end: target.end,
        });
        const updated: InteractiveEntity = {
          text: result.entity.text,
          entity_type: result.entity.entity_type,
          start: result.entity.start,
          end: result.entity.end,
          score: result.entity.score,
          source_layer: result.entity.source_layer,
          metadata: {
            ...result.entity.metadata,
            placeholder: result.placeholder,
          },
          id: result.id,
          state: target.state === 'rejected' ? 'pending' : target.state,
        };
        setEntities((prev) =>
          prev.map((e) => (e.id === target.id ? updated : e)),
        );
      } catch {
        setEntities((prev) =>
          prev.map((e) =>
            e.id === target.id
              ? {
                  ...e,
                  entity_type: newType,
                  metadata: {
                    ...(e.metadata ?? {}),
                    placeholder: undefined,
                  },
                }
              : e,
          ),
        );
      }
    },
    [documentId],
  );

  const remove = useCallback((target: InteractiveEntity) => {
    setEntities((prev) => prev.filter((e) => e.id !== target.id));
    setPopover(null);
  }, []);

  const toggleType = useCallback((code: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const toggleOnlyUnconfirmed = useCallback(
    () => setOnlyUnconfirmed((v) => !v),
    [],
  );

  const resetFilters = useCallback(() => {
    setHiddenTypes(new Set());
    setOnlyUnconfirmed(false);
  }, []);

  const addFromSelection = useCallback(
    async (info: SelectionInfo, entityType: EntityTypeCode | string) => {
      setSelectionBusy(true);
      setSelectionError(null);
      try {
        const result = await addCustomEntity(documentId, {
          text: info.text,
          entity_type: entityType,
          start: info.start,
          end: info.end,
        });
        const added: InteractiveEntity = {
          text: result.entity.text,
          entity_type: result.entity.entity_type,
          start: result.entity.start,
          end: result.entity.end,
          score: result.entity.score,
          source_layer: result.entity.source_layer,
          metadata: {
            ...result.entity.metadata,
            placeholder: result.placeholder,
          },
          id: result.id,
          state: 'custom',
        };
        // Remove any existing entities fully covered by the new selection
        // to prevent overlapping marks (e.g. "Москва" inside full address).
        setEntities((prev) => {
          const next = [
            ...prev.filter(
              (e) =>
                !(e.start >= added.start && e.end <= added.end && e.id !== added.id),
            ),
            added,
          ];
          setStatus('detected');
          rerenderBothPanes(next);
          onAnonymizationComplete?.(documentId, next);
          return next;
        });
        setSelection(null);
        // Clear the browser text selection so the toolbar disappears.
        window.getSelection()?.removeAllRanges();
      } catch (e) {
        setSelectionError(e instanceof Error ? e.message : String(e));
      } finally {
        setSelectionBusy(false);
      }
    },
    [documentId, onAnonymizationComplete, rerenderBothPanes],
  );

  const dismissSelection = useCallback(() => {
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  }, []);

  const handleAppendFiles = useCallback(
    async (files: File[]) => {
      if (!onAppendFiles || files.length === 0 || appendBusy) return;
      setAppendBusy(true);
      try {
        await onAppendFiles(files);
      } finally {
        setAppendBusy(false);
      }
    },
    [appendBusy, onAppendFiles],
  );

  // ─── export anonymized DOCX ──────────────────────────────────────
  //
  // Simple demo exporter: POST current entities to the backend, get
  // a fresh DOCX with placeholders substituted into the original
  // document, and trigger a browser download. The backend filters
  // out rejected entities server-side to match the right pane.
  const handleExport = useCallback(async () => {
    if (exportBusy) return;
    setExportBusy(true);
    setExportError(null);
    try {
      const { blob, filename } = await exportAnonymizedDocx(
        documentId,
        entities,
      );
      downloadBlob(blob, filename);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[Cleargate] export failed', e);
      setExportError(
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setExportBusy(false);
    }
  }, [documentId, entities, exportBusy]);

  // --- import LLM response .docx ---
  const handleImportResponse = useCallback(
    async (file: File) => {
      if (importBusy) return;
      setImportBusy(true);
      setImportError(null);
      try {
        const result = await importResponseDocx(documentId, file);
        // eslint-disable-next-line no-console
        console.info('[Cleargate] response imported', {
          chars: result.char_count,
          placeholders: result.placeholder_count,
        });
        leaveCompareMode();
        cacheManualResolutions([]);
        setResponseImported(true);
        setResponseViewActive(false);
        setWorkflowStage('llm_response');
        setRightPaneUrl(null);
        setDeanonymizeResult(null);

        // Auto-trigger deanonymization
        setDeanonymizeBusy(true);
        setDeanonymizeError(null);
        try {
          const dResult = await deanonymizeDocx(documentId);
          setDeanonymizeResult(dResult);
          // Stash restorations for handleAnonymizedReady to overlay once
          // the right pane finishes rendering the deanonymized DOCX.
          restorationsRef.current = dResult.restorations ?? [];
          // Switch right pane to show deanonymized document
          setWorkflowStage('deanonymized');
          setResponseViewActive(true);
          setRightPaneUrl(responsePreviewUrl());
          // eslint-disable-next-line no-console
          console.info('[Cleargate] deanonymize complete', {
            replacements: dResult.total_replacements,
            unresolved: dResult.total_unresolved,
          });
        } catch (e) {
          // eslint-disable-next-line no-console
          console.error('[Cleargate] deanonymize failed', e);
          setDeanonymizeError(
            e instanceof Error ? e.message : String(e),
          );
        } finally {
          setDeanonymizeBusy(false);
        }
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error('[Cleargate] import response failed', e);
        setImportError(e instanceof Error ? e.message : String(e));
      } finally {
        setImportBusy(false);
      }
    },
    [documentId, importBusy, leaveCompareMode, responsePreviewUrl],
  );

  // --- toggle Compare-with-original mode on the right pane ---
  //
  // ON: compute a word-level LCS diff between the left pane's plain
  // text (original) and the right pane's plain text (deanonymized
  // response), then apply markers inside the already-rendered DOCX DOM.
  // This preserves page geometry, paragraph formatting, tables, fonts,
  // and docx-preview's scroll behavior instead of replacing the pane
  // with a plain-text diff.
  const toggleCompareMode = useCallback(() => {
    const leftPane = leftPaneRef.current;
    const rightPane = rightPaneRef.current;
    if (!leftPane || !rightPane) return;
    const container = rightPane.getContainer();

    if (!compareMode) {
      // Entering compare mode: restore the clean DOCX render first,
      // then layer diff markers on top without deanonymization pills.
      const oldText = leftPane.getPlainText();
      const newText = rightPane.getPlainText();
      rightPane.rerender([], { mode: 'highlight' });
      container.classList.add('cleargate-compare');
      const markerCount = applyFormattedCompareDiff(rightPane, oldText, newText);
      setCompareMode(true);
      // eslint-disable-next-line no-console
      console.info('[Cleargate] compare mode ON', {
        oldChars: oldText.length,
        newChars: newText.length,
        markers: markerCount,
      });
    } else {
      // Leaving compare mode: restore the deanonymized preview by
      // replaying the highlight overlays on top of the clean snapshot.
      container.classList.remove('cleargate-compare');
      rightPane.rerender([], { mode: 'highlight' });
      applyRestorationOverlays(rightPane);
      setCompareMode(false);
      // eslint-disable-next-line no-console
      console.info('[Cleargate] compare mode OFF');
    }
  }, [compareMode, applyRestorationOverlays]);

  // --- export deanonymized .docx ---
  const handleExportDeanonymized = useCallback(async () => {
    if (exportDeanonymizedBusy) return;
    setExportDeanonymizedBusy(true);
    setExportDeanonymizedError(null);
    try {
      const { blob, filename } = await exportDeanonymizedDocx(documentId, manualResolutions);
      downloadBlob(blob, filename);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[Cleargate] export deanonymized failed', e);
      setExportDeanonymizedError(
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setExportDeanonymizedBusy(false);
    }
  }, [documentId, exportDeanonymizedBusy, manualResolutions]);

  const hasSavedResponse = responseImported && deanonymizeResult !== null;
  const importResponseLabel = responseImported
    ? t('workspace.replaceResponse')
    : t('workspace.importResponse');
  const importResponseTitle =
    importError ??
    (importBusy
      ? t('workspace.importResponseBusy')
      : deanonymizeBusy
        ? t('workspace.deanonymizeBusy')
        : importResponseLabel);
  const deepScanButtonLabel = deepScanLayer
    ? deepScanActive
      ? t('workspace.deepScanDisable')
      : t('workspace.deepScanEnable')
    : t('workspace.deepScan');
  const deepScanButtonTitle = deepScanLayer
    ? deepScanActive
      ? t('workspace.deepScanDisableHint')
      : t('workspace.deepScanEnableHint')
    : t('workspace.deepScanHint');

  return (
    <div className="cleargate-workspace">
      <div className="cleargate-workspace__subheader">
        <div className="cleargate-workspace__doc-title">
          <span className="cleargate-workspace__doc-name" title={documentName}>
            {documentName}
          </span>
        </div>
        <div className="cleargate-workspace__actions">
          {onAppendFiles && !responseViewActive && (
            <>
              <button
                type="button"
                className="cleargate-workspace__append-docs"
                onClick={() => appendFileRef.current?.click()}
                disabled={appendBusy || status === 'detecting'}
                title={t('workspace.appendDocuments')}
              >
                {appendBusy ? t('empty.working') : t('workspace.appendDocuments')}
              </button>
              <input
                ref={appendFileRef}
                type="file"
                accept=".docx,.pdf,.txt"
                multiple
                style={{ display: 'none' }}
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  if (files.length > 0) void handleAppendFiles(files);
                  e.target.value = '';
                }}
              />
            </>
          )}
          <button
            type="button"
            className="cleargate-workspace__export"
            onClick={handleExport}
            disabled={exportBusy || !bothReady || entities.length === 0}
            title={
              exportError ??
              (exportBusy
                ? t('workspace.exportDocxBusy')
                : t('workspace.exportDocx'))
            }
          >
            {exportBusy
              ? t('workspace.exportDocxBusy')
              : t('workspace.exportDocx')}
          </button>
          {!responseViewActive && (
            deepScanBusy ? (
              <div
                className="cleargate-workspace__deep-progress"
                role="progressbar"
                aria-label={t('workspace.deepScanBusy')}
                aria-valuenow={deepScanProgress}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span className="cleargate-workspace__deep-progress-label">
                  {t('workspace.deepScanBusy')}
                </span>
                <span className="cleargate-workspace__deep-progress-track">
                  <span
                    className="cleargate-workspace__deep-progress-fill"
                    style={{ width: `${deepScanProgress}%` }}
                  />
                </span>
              </div>
            ) : (
              <button
                type="button"
                className={`cleargate-workspace__deep-scan ${
                  deepScanActive ? 'is-active' : ''
                }`}
                onClick={runDeepScan}
                disabled={
                  !bothReady ||
                  entities.length === 0 ||
                  status === 'detecting'
                }
                aria-pressed={deepScanLayer ? deepScanActive : undefined}
                title={deepScanButtonTitle}
              >
                {deepScanButtonLabel}
              </button>
            )
          )}
          {deepScanError && !responseViewActive && !deepScanBusy && (
            <span className="cleargate-workspace__action-error" role="status">
              {t('workspace.deepScanError')}
            </span>
          )}
          {deepScanSummaryLabel && !responseViewActive && !deepScanBusy && !deepScanError && (
            <span className="cleargate-workspace__deep-summary" role="status">
              {deepScanSummaryLabel}
            </span>
          )}
          {/* Phase 1 round-trip: import response */}
          <button
            type="button"
            className="cleargate-workspace__import-response"
            onClick={() => responseFileRef.current?.click()}
            disabled={
              importBusy ||
              deanonymizeBusy ||
              manualResolutionBusy ||
              !bothReady ||
              entities.length === 0
            }
            title={importResponseTitle}
          >
            {importBusy
              ? t('workspace.importResponseBusy')
              : deanonymizeBusy
                ? t('workspace.deanonymizeBusy')
                : importResponseLabel}
          </button>
          <input
            ref={responseFileRef}
            type="file"
            accept=".docx"
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleImportResponse(file);
              e.target.value = '';
            }}
          />

          {/* Compare-with-original toggle (Word-style Track Changes) */}
          {hasSavedResponse && (
            <button
              type="button"
              className="cleargate-workspace__workflow-toggle"
              onClick={
                responseViewActive
                  ? showAnonymizedWorkflow
                  : showDeanonymizedWorkflow
              }
              disabled={deanonymizeBusy || manualResolutionBusy}
              aria-pressed={workflowStage === 'deanonymized' && responseViewActive}
              title={
                responseViewActive
                  ? t('workspace.workflowBackToAnonymized')
                  : t('workspace.workflowReturnToResponse')
              }
            >
              {responseViewActive
                ? t('workspace.workflowBackToAnonymized')
                : t('workspace.workflowReturnToResponse')}
            </button>
          )}

          {responseViewActive && hasSavedResponse && (
            <button
              type="button"
              className="cleargate-workspace__compare"
              onClick={toggleCompareMode}
              disabled={deanonymizeBusy || manualResolutionBusy}
              aria-pressed={compareMode}
              title={
                compareMode
                  ? t('workspace.compareToggleOff')
                  : t('workspace.compareToggleOn')
              }
            >
              {compareMode
                ? t('workspace.compareToggleOff')
                : t('workspace.compareToggleOn')}
            </button>
          )}

          {/* Phase 1 round-trip: export deanonymized */}
          {responseViewActive && hasSavedResponse && (
            <button
              type="button"
              className="cleargate-workspace__export-deanonymized"
              onClick={handleExportDeanonymized}
              disabled={exportDeanonymizedBusy || deanonymizeBusy || manualResolutionBusy}
              title={
                exportDeanonymizedError ??
                (exportDeanonymizedBusy
                  ? t('workspace.exportDeanonymizedBusy')
                  : t('workspace.exportDeanonymized'))
              }
            >
              {exportDeanonymizedBusy
                ? t('workspace.exportDeanonymizedBusy')
                : t('workspace.exportDeanonymized')}
            </button>
          )}

          <button
            type="button"
            className="cleargate-workspace__close"
            onClick={onClose}
            title={t('workspace.close')}
          >
            {t('workspace.close')}
          </button>
        </div>
      </div>

      <div className="cleargate-workspace__split">
        <DocxViewer
          documentId={documentId}
          label={t('editor.original')}
          onReady={handleOriginalReady}
          className="cleargate-workspace__pane"
        />
        <div className="cleargate-workspace__divider" aria-hidden />
        <DocxViewer
          documentId={documentId}
          label={rightPaneUrl ? t('workspace.deanonymizedPreview') : t('editor.anonymized')}
          onReady={handleAnonymizedReady}
          className="cleargate-workspace__pane"
          urlOverride={rightPaneUrl}
        />
        {!responseViewActive && (
          <div
            className={`cleargate-workspace__anonymize-panel ${
              status === 'detecting' ? 'is-detecting' : ''
            } ${entities.length > 0 ? 'is-hidden' : ''}`}
          >
            {status === 'detecting' ? (
              <div className="cleargate-workspace__progress-card" role="status">
                <div className="cleargate-workspace__progress-title">
                  {t('workspace.anonymizing')}
                </div>
                <div
                  className="cleargate-workspace__progress-track"
                  aria-label={t('workspace.progressLabel')}
                  aria-valuenow={progressValue}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  role="progressbar"
                >
                  <div
                    className="cleargate-workspace__progress-fill"
                    style={{ width: `${progressValue}%` }}
                  />
                </div>
                <div className="cleargate-workspace__progress-note">
                  {t('workspace.progressNote')}
                </div>
              </div>
            ) : (
              <div className="cleargate-workspace__start-card">
                <button
                  type="button"
                  className="cleargate-workspace__start-button"
                  onClick={runAnonymization}
                  disabled={!bothReady}
                >
                  {t('workspace.startAnonymize')}
                </button>
                {error && (
                  <div className="cleargate-workspace__start-error">{error}</div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        className={`cleargate-workspace__zoom-toast ${
          showZoomPill ? 'is-visible' : ''
        }`}
        onClick={resetScale}
        title={t('workspace.resetZoom')}
        aria-label={`${t('workspace.zoomLevel')} ${Math.round(docScale * 100)}%`}
      >
        {Math.round(docScale * 100)}%
      </button>

      {!responseViewActive && deepScanLayer && deepScanReviewItems.length > 0 && (
        <section className="cleargate-workspace__deep-review" aria-label={t('workspace.deepScanReviewTitle')}>
          <div className="cleargate-workspace__deep-review-head">
            <span>{t('workspace.deepScanReviewTitle')}</span>
            <span>{deepScanSummaryLabel}</span>
          </div>
          <div className="cleargate-workspace__deep-review-list">
            {deepScanReviewItems.map(({ action, entity, enabled }) => {
              const key = entitySignature(entity);
              return (
                <label
                  key={`${action}-${key}`}
                  className={`cleargate-workspace__deep-review-item is-${action} ${
                    enabled ? 'is-enabled' : ''
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={() => toggleDeepScanProposal(action, entity)}
                  />
                  <span className="cleargate-workspace__deep-review-action">
                    {action === 'add'
                      ? t('workspace.deepScanAdd')
                      : t('workspace.deepScanRemove')}
                  </span>
                  <span className="cleargate-workspace__deep-review-type">
                    {entity.entity_type}
                  </span>
                  <span className="cleargate-workspace__deep-review-text" title={entity.text}>
                    {entity.text}
                  </span>
                </label>
              );
            })}
          </div>
        </section>
      )}

      {!responseViewActive && (
        <EntityLegend
          counts={counts}
          totalEntities={entities.length}
          visibleEntities={visibleEntities.length}
          hiddenTypes={hiddenTypes}
          onlyUnconfirmed={onlyUnconfirmed}
          status={status}
          error={error}
          onToggleType={toggleType}
          onToggleOnlyUnconfirmed={toggleOnlyUnconfirmed}
          onResetFilters={resetFilters}
        />
      )}

      {/* Unresolved placeholders panel with manual input */}
      {!compareMode && deanonymizeResult && deanonymizeResult.total_unresolved > 0 && (
        <div className="cleargate-workspace__unresolved">
          <div className="cleargate-workspace__unresolved-header">
            {t('workspace.unresolvedTitle')} ({deanonymizeResult.total_unresolved})
          </div>
          <p className="cleargate-workspace__unresolved-hint">
            {t('workspace.unresolvedHint')}
          </p>
          <ul className="cleargate-workspace__unresolved-list">
            {deanonymizeResult.unresolved.map((u, i) => (
              <li key={`${u.normalized}-${i}`} className="cleargate-workspace__unresolved-item">
                <code>{u.normalized}</code>
                <span>{' \u2192 '}</span>
                <input
                  type="text"
                  className="cleargate-workspace__unresolved-input"
                  placeholder={t('workspace.unresolvedValue')}
                  value={unresolvedValues[u.normalized] ?? ''}
                  onChange={(event) => {
                    const value = event.currentTarget.value;
                    setUnresolvedValues((current) => ({
                      ...current,
                      [u.normalized]: value,
                    }));
                  }}
                />
              </li>
            ))}
          </ul>
          {deanonymizeError && (
            <div className="cleargate-workspace__unresolved-error">
              {deanonymizeError}
            </div>
          )}
          <button
            type="button"
            className="cleargate-workspace__unresolved-apply"
            onClick={() => {
              const nextManual = new Map(
                manualResolutions.map((resolution) => [
                  resolution.placeholder,
                  resolution.value,
                ]),
              );
              for (const unresolved of deanonymizeResult.unresolved) {
                const value = (unresolvedValues[unresolved.normalized] ?? '').trim();
                if (value) {
                  nextManual.set(unresolved.normalized, value);
                }
              }
              const resolutions = Array.from(nextManual.entries()).map(
                ([placeholder, value]) => ({ placeholder, value }),
              );
              if (resolutions.length === 0) return;
              cacheManualResolutions(resolutions);
              setManualResolutionBusy(true);
              setDeanonymizeError(null);
              deanonymizeDocx(documentId, resolutions)
                .then((dResult) => {
                  setDeanonymizeResult(dResult);
                  restorationsRef.current = dResult.restorations ?? [];
                  // Refresh right pane preview with cache-busting timestamp
                  setWorkflowStage('deanonymized');
                  setResponseImported(true);
                  setResponseViewActive(true);
                  setRightPaneUrl(responsePreviewUrl());
                })
                .catch((e) => {
                  console.error('[Cleargate] apply resolutions failed', e);
                  setDeanonymizeError(
                    e instanceof Error ? e.message : String(e),
                  );
                })
                .finally(() => setManualResolutionBusy(false));
            }}
            disabled={manualResolutionBusy}
          >
            {manualResolutionBusy
              ? t('workspace.unresolvedApplying')
              : t('workspace.unresolvedApply')}
          </button>
        </div>
      )}

      {/* Deanonymize stats */}
      {!compareMode && deanonymizeResult && (
        <div className="cleargate-workspace__deanonymize-stats">
          <span>{t('workspace.replacementsDone')}: {deanonymizeResult.total_replacements}</span>
          {deanonymizeResult.total_unresolved > 0 && (
            <span> | {t('workspace.unresolvedCount')}: {deanonymizeResult.total_unresolved}</span>
          )}
        </div>
      )}

      <EntityPopover
        anchor={popover}
        onAccept={accept}
        onReject={reject}
        onChangeType={changeType}
        onRemove={remove}
        onClose={closePopover}
      />

      <SelectionToolbar
        selection={selection}
        busy={selectionBusy}
        error={selectionError}
        onAddEntity={(info, type) => addFromSelection(info, type)}
        onDismiss={dismissSelection}
      />
    </div>
  );
}

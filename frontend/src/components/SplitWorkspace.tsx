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
  importResponseDocx,
  type DeanonymizeDocxResult,
  type Restoration,
} from '@/lib/api';
import { useLocale } from '@/hooks/useLocale';
import type { EntityTypeCode } from '@/lib/entity-types';

interface SplitWorkspaceProps {
  documentId: string;
  documentName: string;
  onClose: () => void;
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

type CompareMutation =
  | { kind: 'ins'; start: number; end: number; text: string }
  | { kind: 'del'; at: number; text: string };

const entitySignature = (
  entity: Pick<InteractiveEntity, 'start' | 'end' | 'entity_type' | 'text'>,
) => `${entity.start}:${entity.end}:${entity.entity_type}:${entity.text}`;

function comparePosition(mutation: CompareMutation): number {
  return mutation.kind === 'ins' ? mutation.start : mutation.at;
}

function wrapRangeWithDiffMarker(range: Range, kind: 'ins' | 'del'): boolean {
  const doc = range.startContainer.ownerDocument;
  if (!doc) return false;
  const marker = doc.createElement(kind);
  marker.className =
    kind === 'ins' ? 'cleargate-diff-ins' : 'cleargate-diff-del';
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
): boolean {
  const map = pane.getAnchorMap();
  const pos = map.toDomPosition(Math.min(at, map.plainText.length));
  if (!pos) return false;
  const doc = container.ownerDocument;
  const marker = doc.createElement('del');
  marker.className = 'cleargate-diff-del';
  marker.textContent = text;
  const range = doc.createRange();
  range.setStart(pos.node, pos.offset);
  range.collapse(true);
  range.insertNode(marker);
  return true;
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

  let applied = 0;
  const ordered = mutations.sort(
    (a, b) => comparePosition(b) - comparePosition(a),
  );
  for (const mutation of ordered) {
    try {
      if (mutation.kind === 'ins') {
        const map = pane.getAnchorMap();
        const range = map.toRange(mutation.start, mutation.end);
        if (range && wrapRangeWithDiffMarker(range, 'ins')) applied++;
      } else if (insertDeletedDiffMarker(container, mutation.at, mutation.text, pane)) {
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
  const [deepScanSuggestions, setDeepScanSuggestions] = useState<InteractiveEntity[]>([]);
  const restoreStartedRef = useRef(false);

  // Phase 1 round-trip: import response -> deanonymize -> export
  const responseFileRef = useRef<HTMLInputElement | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [responseImported, setResponseImported] = useState(false);
  const [deanonymizeBusy, setDeanonymizeBusy] = useState(false);
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
  // URL override for right pane: after deanonymize, show the deanonymized doc
  const [rightPaneUrl, setRightPaneUrl] = useState<string | null>(null);

  // Compare-with-original mode (Word-style Track Changes).
  // When ON, the right pane's DOM is replaced in-place with a word-level
  // diff overlay. Toggling OFF restores the docx-preview render via
  // `pane.rerender(overlays, 'highlight')` using the stashed restorations.
  const [compareMode, setCompareMode] = useState(false);

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
      applyRestorationOverlays(pane);

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
    rightContainerRef.current?.classList.remove('cleargate-compare');
    leftContainerRef.current = null;
    rightContainerRef.current = null;
    leftPaneRef.current = null;
    rightPaneRef.current = null;
    restorationsRef.current = [];
    setDocScale(1);
    setManualResolutions([]);
    setCompareMode(false);
    setDeepScanBusy(false);
    setDeepScanError(null);
    setDeepScanProgress(0);
    setDeepScanSummary(null);
    setDeepScanSuggestions([]);
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
  const rerenderBothPanes = useCallback((entitiesToDraw: InteractiveEntity[]) => {
    const leftPane = leftPaneRef.current;
    const rightPane = rightPaneRef.current;
    if (!leftPane || !rightPane) {
      // eslint-disable-next-line no-console
      console.warn('[Cleargate] rerender skipped — panes not ready');
      return;
    }
    leftPane.rerender(entitiesToDraw, { mode: 'highlight' });
    rightPane.rerender(entitiesToDraw, { mode: 'placeholder' });
  }, []);

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

  // ─── explicit detection ──────────────────────────────────────────
  const runAnonymization = useCallback(async () => {
    if (!bothReady || status === 'detecting') return;
    const leftPane = leftPaneRef.current;
    if (!leftPane) return;
    const plainText = leftPane.getPlainText();

    setStatus('detecting');
    setProgressValue(8);
    setError(null);
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

  const runDeepScan = useCallback(async () => {
    if (!bothReady || deepScanBusy || status === 'detecting') return;
    const leftPane = leftPaneRef.current;
    if (!leftPane) return;
    const plainText = leftPane.getPlainText();

    setDeepScanBusy(true);
    setDeepScanError(null);
    setDeepScanSummary(null);
    setDeepScanSuggestions([]);
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
      );
      setDeepScanSuggestions(suggestions);
      setDeepScanSummary({
        added: 0,
        removed: 0,
        suggestions: response.suggestion_count ?? suggestions.length,
      });
      setDeepScanProgress(100);
      // eslint-disable-next-line no-console
      console.info('[Cleargate] deep scan response', {
        entities: response.entities?.length ?? 0,
        suggestions: suggestions.length,
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
    bothReady,
    deepScanBusy,
    documentId,
    entities,
    onAnonymizationComplete,
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
    if (deepScanSummary.suggestions > 0) {
      return `${t('workspace.deepScanSuggestions')}: ${deepScanSummary.suggestions}`;
    }
    if (deepScanSummary.added === 0 && deepScanSummary.removed === 0) {
      return t('workspace.deepScanNoChanges');
    }
    return `${t('workspace.deepScanDone')}: +${deepScanSummary.added} / -${deepScanSummary.removed}`;
  }, [deepScanSummary, t]);

  const applyDeepScanSuggestions = useCallback(() => {
    if (deepScanSuggestions.length === 0) return;
    const existing = new Set(entities.map(entitySignature));
    const toAdd = deepScanSuggestions.filter(
      (suggestion) => !existing.has(entitySignature(suggestion)),
    );
    if (toAdd.length === 0) {
      setDeepScanSuggestions([]);
      return;
    }
    const merged = [...entities, ...toAdd].sort((a, b) => a.start - b.start);
    applyEntities(merged);
    onAnonymizationComplete?.(documentId, merged);
    setDeepScanSuggestions([]);
    setDeepScanSummary({ added: toAdd.length, removed: 0, suggestions: 0 });
  }, [
    applyEntities,
    deepScanSuggestions,
    documentId,
    entities,
    onAnonymizationComplete,
  ]);

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
    (target: InteractiveEntity, newType: string) => {
      setEntities((prev) =>
        prev.map((e) =>
          e.id === target.id ? { ...e, entity_type: newType } : e,
        ),
      );
      setPopover(null);
    },
    [],
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
        setResponseImported(true);

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
          setRightPaneUrl(
            `${API_URL}/api/documents/${encodeURIComponent(documentId)}/response-raw?t=${Date.now()}`,
          );
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
    [documentId, importBusy],
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
      // then layer restoration highlights and diff markers on top.
      const oldText = leftPane.getPlainText();
      const newText = rightPane.getPlainText();
      rightPane.rerender([], { mode: 'highlight' });
      applyRestorationOverlays(rightPane);
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

  return (
    <div className="cleargate-workspace">
      <div className="cleargate-workspace__subheader">
        <div className="cleargate-workspace__doc-title">
          <span className="cleargate-workspace__doc-name" title={documentName}>
            {documentName}
          </span>
        </div>
        <div className="cleargate-workspace__actions">
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
          {!responseImported && (
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
                className="cleargate-workspace__deep-scan"
                onClick={runDeepScan}
                disabled={
                  !bothReady ||
                  entities.length === 0 ||
                  status === 'detecting'
                }
                title={t('workspace.deepScanHint')}
              >
                {t('workspace.deepScan')}
              </button>
            )
          )}
          {deepScanError && !deepScanBusy && (
            <span className="cleargate-workspace__action-error" role="status">
              {t('workspace.deepScanError')}
            </span>
          )}
          {deepScanSummaryLabel && !deepScanBusy && !deepScanError && (
            <span className="cleargate-workspace__deep-summary" role="status">
              {deepScanSummaryLabel}
            </span>
          )}
          {deepScanSuggestions.length > 0 && !deepScanBusy && (
            <div className="cleargate-workspace__deep-suggestions" role="status">
              <span>{t('workspace.deepScanReview')}</span>
              <button
                type="button"
                className="cleargate-workspace__deep-suggestions-apply"
                onClick={applyDeepScanSuggestions}
              >
                {t('workspace.deepScanApply')}
              </button>
              <button
                type="button"
                className="cleargate-workspace__deep-suggestions-dismiss"
                onClick={() => {
                  setDeepScanSuggestions([]);
                  setDeepScanSummary(null);
                }}
                aria-label={t('workspace.deepScanDismiss')}
                title={t('workspace.deepScanDismiss')}
              >
                x
              </button>
            </div>
          )}
          {/* Phase 1 round-trip: import response */}
          <button
            type="button"
            className="cleargate-workspace__import-response"
            onClick={() => responseFileRef.current?.click()}
            disabled={importBusy || deanonymizeBusy || !bothReady || entities.length === 0}
            title={
              importError ??
              (importBusy
                ? t('workspace.importResponseBusy')
                : deanonymizeBusy
                  ? t('workspace.deanonymizeBusy')
                  : t('workspace.importResponse'))
            }
          >
            {importBusy
              ? t('workspace.importResponseBusy')
              : deanonymizeBusy
                ? t('workspace.deanonymizeBusy')
                : t('workspace.importResponse')}
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
          {responseImported && (
            <button
              type="button"
              className="cleargate-workspace__compare"
              onClick={toggleCompareMode}
              disabled={deanonymizeBusy}
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
          {responseImported && (
            <button
              type="button"
              className="cleargate-workspace__export-deanonymized"
              onClick={handleExportDeanonymized}
              disabled={exportDeanonymizedBusy || deanonymizeBusy}
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
        {!responseImported && (
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

      {!responseImported && (
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
      {deanonymizeResult && deanonymizeResult.total_unresolved > 0 && (
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
                  data-placeholder={u.normalized}
                  defaultValue=""
                />
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="cleargate-workspace__unresolved-apply"
            onClick={() => {
              const inputs = document.querySelectorAll<HTMLInputElement>(
                '.cleargate-workspace__unresolved-input',
              );
              const resolutions: Array<{ placeholder: string; value: string }> = [];
              inputs.forEach((input) => {
                const val = input.value.trim();
                const ph = input.dataset.placeholder;
                if (val && ph) resolutions.push({ placeholder: ph, value: val });
              });
              if (resolutions.length === 0) return;
              setManualResolutions(resolutions);
              setDeanonymizeBusy(true);
              setDeanonymizeError(null);
              deanonymizeDocx(documentId, resolutions)
                .then((dResult) => {
                  setDeanonymizeResult(dResult);
                  restorationsRef.current = dResult.restorations ?? [];
                  // Refresh right pane preview with cache-busting timestamp
                  setRightPaneUrl(
                    `${API_URL}/api/documents/${encodeURIComponent(documentId)}/response-raw?t=${Date.now()}`,
                  );
                })
                .catch((e) => {
                  console.error('[Cleargate] apply resolutions failed', e);
                  setDeanonymizeError(
                    e instanceof Error ? e.message : String(e),
                  );
                })
                .finally(() => setDeanonymizeBusy(false));
            }}
          >
            {t('workspace.unresolvedApply')}
          </button>
        </div>
      )}

      {/* Deanonymize stats */}
      {deanonymizeResult && (
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

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
 *   3. Click on any `<mark.velum-entity>` in either pane opens the
 *      EntityPopover with accept / reject / change type / remove actions.
 *   4. Hovering over a mark adds `.velum-entity--active` to every mark
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
import {
  addCustomEntity,
  anonymizeText,
  downloadBlob,
  exportAnonymizedDocx,
} from '@/lib/api';
import { useLocale } from '@/hooks/useLocale';
import type { EntityTypeCode } from '@/lib/entity-types';

interface SplitWorkspaceProps {
  documentId: string;
  documentName: string;
  onClose: () => void;
}

const ACTIVE_CLASS = 'velum-entity--active';

// Document zoom limits. Step is fine-grained enough that Ctrl+wheel
// feels smooth on a typical mouse, but coarse enough that the rounding
// to whole-percent display stays accurate.
const MIN_SCALE = 0.5;
const MAX_SCALE = 2.0;
const SCALE_STEP = 0.1;

export function SplitWorkspace({
  documentId,
  documentName,
  onClose,
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

  const [status, setStatus] = useState<LegendStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [entities, setEntities] = useState<InteractiveEntity[]>([]);

  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [onlyUnconfirmed, setOnlyUnconfirmed] = useState(false);

  const [popover, setPopover] = useState<EntityPopoverAnchor | null>(null);
  const [selection, setSelection] = useState<SelectionInfo | null>(null);
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);

  const [bothReady, setBothReady] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const detectionStartedRef = useRef(false);

  // Synchronized document zoom (both panes scale together).
  // Implemented via the CSS `zoom` property on the docx-preview
  // container, NOT via `transform: scale()`. Two reasons:
  //   - `zoom` cooperates with the surrounding scroll container so
  //     scrollbars adapt automatically; `transform: scale` does not.
  //   - `zoom` does not change the underlying DOM, so the existing
  //     anchor maps and selection offsets remain valid as-is.
  const [docScale, setDocScale] = useState<number>(1);
  const adjustScale = useCallback((delta: number) => {
    setDocScale((prev) => {
      const next = Math.round((prev + delta) * 100) / 100;
      return Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
    });
  }, []);
  const resetScale = useCallback(() => setDocScale(1), []);

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
      console.info('[Velum] original pane ready', {
        chars: pane.getPlainText().length,
      });
      markBothReadyIfPossible();
    },
    [markBothReadyIfPossible],
  );

  const handleAnonymizedReady = useCallback(
    (container: HTMLElement) => {
      rightContainerRef.current = container;
      rightPaneRef.current = new DocxPane(container);
      // eslint-disable-next-line no-console
      console.info('[Velum] anonymized pane ready');
      markBothReadyIfPossible();
    },
    [markBothReadyIfPossible],
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
    setHiddenTypes(new Set());
    setOnlyUnconfirmed(false);
    setPopover(null);
    setSelection(null);
    setBothReady(false);
    detectionStartedRef.current = false;
    leftContainerRef.current = null;
    rightContainerRef.current = null;
    leftPaneRef.current = null;
    rightPaneRef.current = null;
    setDocScale(1);
  }, [documentId]);

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
  }, [docScale, bothReady]);

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
      console.warn('[Velum] rerender skipped — panes not ready');
      return;
    }
    leftPane.rerender(entitiesToDraw, { mode: 'highlight' });
    rightPane.rerender(entitiesToDraw, { mode: 'placeholder' });
  }, []);

  // ─── initial detection ───────────────────────────────────────────
  //
  // Fires exactly once per document (guarded by detectionStartedRef).
  // We trigger it from `bothReady` rather than from `readyTick` to
  // guarantee refs were observed as populated atomically.
  useEffect(() => {
    if (!bothReady) return;
    if (detectionStartedRef.current) return;
    detectionStartedRef.current = true;

    const leftPane = leftPaneRef.current;
    if (!leftPane) return;
    const plainText = leftPane.getPlainText();

    let cancelled = false;
    setStatus('detecting');
    setError(null);

    (async () => {
      try {
        // eslint-disable-next-line no-console
        console.info('[Velum] anonymize start', {
          documentId,
          chars: plainText.length,
        });
        const response = await anonymizeText(documentId, plainText);
        // eslint-disable-next-line no-console
        console.info('[Velum] anonymize response', {
          entities: response.entities?.length ?? 0,
        });
        if (cancelled) return;
        const raw = (response.entities as OverlayEntity[]) ?? [];
        const interactive: InteractiveEntity[] = raw.map((e, idx) => ({
          ...e,
          id:
            (e.metadata?.id as string | undefined) ??
            `det-${idx}-${e.start}-${e.end}-${e.entity_type}`,
          state: 'pending',
        }));
        setEntities(interactive);
        setStatus('detected');
        // Explicit rerender with the fresh entity list — do not wait
        // for the `[visibleEntities]` effect to fire. This is the key
        // fix for "только после повторной загрузки документа".
        rerenderBothPanes(interactive);
      } catch (e) {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.error('[Velum] anonymize failed', e);
        setError(e instanceof Error ? e.message : String(e));
        setStatus('error');
        // Allow the user to retry via the legend "retry" button.
        detectionStartedRef.current = false;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bothReady, documentId, rerenderBothPanes]);

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
      return target.closest('mark.velum-entity') as HTMLElement | null;
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
          `mark.velum-entity[data-entity-id="${CSS.escape(id)}"]`,
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
        console.info('[Velum] selection: containers not ready');
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

      // Selections that start inside an existing entity mark belong to
      // the popover flow, not the "add new entity" flow.
      if (startNode.closest('mark.velum-entity')) {
        setSelection(null);
        return;
      }

      const pane: 'left' | 'right' = inLeft ? 'left' : 'right';
      let leftOffsets: { start: number; end: number } | null = null;

      if (inLeft) {
        const leftPane = leftPaneRef.current;
        if (!leftPane) {
          // eslint-disable-next-line no-console
          console.warn('[Velum] selection: left pane not ready');
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
          console.warn('[Velum] selection: right pane not ready');
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
            '[Velum] selection: right→left translation failed (touches placeholder)',
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
        target?.closest?.('.velum-selection') ||
        target?.closest?.('.velum-popover')
      ) {
        return;
      }
      const { clientX, clientY } = e;
      // Let the browser finalise its selection state, then read it.
      setTimeout(() => processSelection(clientX, clientY), 0);
    };

    const handleKeyUp = (e: KeyboardEvent) => {
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
    async (info: SelectionInfo, entityType: EntityTypeCode) => {
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
        setEntities((prev) => [...prev, added]);
        setSelection(null);
        // Clear the browser text selection so the toolbar disappears.
        window.getSelection()?.removeAllRanges();
      } catch (e) {
        setSelectionError(e instanceof Error ? e.message : String(e));
      } finally {
        setSelectionBusy(false);
      }
    },
    [documentId],
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
      console.error('[Velum] export failed', e);
      setExportError(
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setExportBusy(false);
    }
  }, [documentId, entities, exportBusy]);

  return (
    <div className="velum-workspace">
      <div className="velum-workspace__subheader">
        <div className="velum-workspace__doc-title">
          <span className="velum-workspace__doc-icon" aria-hidden>
            ¶
          </span>
          <span className="velum-workspace__doc-name" title={documentName}>
            {documentName}
          </span>
          <button
            type="button"
            className="velum-workspace__scale-indicator"
            onClick={resetScale}
            title={t('workspace.resetZoom')}
            aria-label={`${t('workspace.zoomLevel')} ${Math.round(docScale * 100)}%`}
          >
            {Math.round(docScale * 100)}%
          </button>
        </div>
        <div className="velum-workspace__actions">
          <button
            type="button"
            className="velum-workspace__export"
            onClick={handleExport}
            disabled={exportBusy || !bothReady}
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
          <button
            type="button"
            className="velum-workspace__close"
            onClick={onClose}
            title={t('workspace.close')}
          >
            {t('workspace.close')}
          </button>
        </div>
      </div>

      <div className="velum-workspace__split">
        <DocxViewer
          documentId={documentId}
          label={t('editor.original')}
          onReady={handleOriginalReady}
          className="velum-workspace__pane"
        />
        <div className="velum-workspace__divider" aria-hidden />
        <DocxViewer
          documentId={documentId}
          label={t('editor.anonymized')}
          onReady={handleAnonymizedReady}
          className="velum-workspace__pane"
        />
      </div>

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

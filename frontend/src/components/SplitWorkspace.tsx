'use client';

/**
 * SplitWorkspace — two-pane interactive workspace.
 *
 * Iteration 3 scope (this file):
 *   1. Detection pass identical to iteration 2: render original +
 *      anonymized panes from the same DOCX, run `/anonymize` once the
 *      left pane's anchor map is ready, overlay the result.
 *   2. After the first render, we snapshot the CLEAN innerHTML of each
 *      pane. Every subsequent state change (accept / reject / change
 *      type / add / remove / filter toggle) calls `rerenderPaneFromClean`
 *      which restores the clean HTML, rebuilds the anchor map, and
 *      re-applies the current filtered entity set. This is cheap for
 *      contract-sized documents and much easier to reason about than
 *      surgical DOM patches.
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
import {
  buildDocxAnchorMap,
  type DocxAnchorMap,
} from '@/lib/docx-anchor-map';
import {
  groupEntityCounts,
  rerenderPaneFromClean,
  rightOffsetsToLeft,
  type InteractiveEntity,
  type OverlayEntity,
} from '@/lib/entity-overlay';
import { addCustomEntity, anonymizeText } from '@/lib/api';
import { useLocale } from '@/hooks/useLocale';
import type { EntityTypeCode } from '@/lib/entity-types';

interface SplitWorkspaceProps {
  documentId: string;
  documentName: string;
  onClose: () => void;
}

const ACTIVE_CLASS = 'velum-entity--active';

export function SplitWorkspace({
  documentId,
  documentName,
  onClose,
}: SplitWorkspaceProps) {
  const { t } = useLocale();

  // Pane containers and their clean (pre-overlay) HTML snapshots.
  const leftContainerRef = useRef<HTMLElement | null>(null);
  const rightContainerRef = useRef<HTMLElement | null>(null);
  const leftCleanHtmlRef = useRef<string | null>(null);
  const rightCleanHtmlRef = useRef<string | null>(null);
  const leftMapRef = useRef<DocxAnchorMap | null>(null);
  const rightMapRef = useRef<DocxAnchorMap | null>(null);

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
  const detectionStartedRef = useRef(false);

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
      leftCleanHtmlRef.current != null &&
      rightCleanHtmlRef.current != null &&
      leftMapRef.current &&
      rightMapRef.current
    ) {
      setBothReady(true);
    }
  }, []);

  const handleOriginalReady = useCallback(
    (container: HTMLElement) => {
      leftContainerRef.current = container;
      leftCleanHtmlRef.current = container.innerHTML;
      leftMapRef.current = buildDocxAnchorMap(container);
      // eslint-disable-next-line no-console
      console.info('[Velum] original pane ready', {
        chars: leftMapRef.current.plainText.length,
      });
      markBothReadyIfPossible();
    },
    [markBothReadyIfPossible],
  );

  const handleAnonymizedReady = useCallback(
    (container: HTMLElement) => {
      rightContainerRef.current = container;
      rightCleanHtmlRef.current = container.innerHTML;
      rightMapRef.current = buildDocxAnchorMap(container);
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
    leftCleanHtmlRef.current = null;
    rightCleanHtmlRef.current = null;
    leftMapRef.current = null;
    rightMapRef.current = null;
  }, [documentId]);

  // ─── explicit rerender helper ─────────────────────────────────────
  //
  // Called directly by the detection effect and by every state-change
  // handler (accept / reject / add / …). Re-rendering is driven
  // imperatively instead of via a `[visibleEntities]` useEffect so we
  // control exactly when the panes are redrawn and avoid the subtle
  // effect-ordering race that used to require a manual reload.
  const rerenderBothPanes = useCallback((entitiesToDraw: InteractiveEntity[]) => {
    const leftContainer = leftContainerRef.current;
    const rightContainer = rightContainerRef.current;
    const leftClean = leftCleanHtmlRef.current;
    const rightClean = rightCleanHtmlRef.current;
    if (
      !leftContainer ||
      !rightContainer ||
      leftClean == null ||
      rightClean == null
    ) {
      // eslint-disable-next-line no-console
      console.warn('[Velum] rerender skipped — panes not ready');
      return;
    }

    const left = rerenderPaneFromClean(
      leftContainer,
      leftClean,
      buildDocxAnchorMap,
      entitiesToDraw,
      { mode: 'highlight' },
    );
    leftMapRef.current = left.anchorMap;

    const right = rerenderPaneFromClean(
      rightContainer,
      rightClean,
      buildDocxAnchorMap,
      entitiesToDraw,
      { mode: 'placeholder' },
    );
    rightMapRef.current = right.anchorMap;
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

    const leftMap = leftMapRef.current;
    if (!leftMap) return;

    let cancelled = false;
    setStatus('detecting');
    setError(null);

    (async () => {
      try {
        // eslint-disable-next-line no-console
        console.info('[Velum] anonymize start', {
          documentId,
          chars: leftMap.plainText.length,
        });
        const response = await anonymizeText(documentId, leftMap.plainText);
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
        // eslint-disable-next-line no-console
        console.info('[Velum] selection: starts inside existing mark — popover flow');
        setSelection(null);
        return;
      }

      const pane: 'left' | 'right' = inLeft ? 'left' : 'right';
      let leftOffsets: { start: number; end: number } | null = null;

      if (inLeft) {
        const leftMap = leftMapRef.current;
        if (!leftMap) {
          // eslint-disable-next-line no-console
          console.warn('[Velum] selection: left anchor map missing');
          return;
        }
        leftOffsets = leftMap.rangeToOffsets(range);
      } else {
        const rightMap = rightMapRef.current;
        if (!rightMap) {
          // eslint-disable-next-line no-console
          console.warn('[Velum] selection: right anchor map missing');
          return;
        }
        const rightOffsets = rightMap.rangeToOffsets(range);
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

      // eslint-disable-next-line no-console
      console.info('[Velum] selection captured', {
        pane,
        leftStart: leftOffsets.start,
        leftEnd: leftOffsets.end,
        text: text.slice(0, 40),
      });

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
        </div>
        <button
          type="button"
          className="velum-workspace__close"
          onClick={onClose}
          title={t('workspace.close')}
        >
          {t('workspace.close')}
        </button>
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

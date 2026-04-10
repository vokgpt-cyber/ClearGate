/**
 * Entity overlay — apply detected entity highlights on top of a
 * rendered docx-preview container.
 *
 * We support two modes:
 *
 *   - `highlight`  (left pane)   — wraps each entity's text in-place
 *                                  inside a `<mark class="velum-entity
 *                                  velum-entity--{type}">`. Text content
 *                                  is preserved.
 *
 *   - `placeholder` (right pane) — replaces each entity's range with a
 *                                  `<mark>` element containing the
 *                                  placeholder token (e.g. `[ЛИЦО_1]`)
 *                                  instead of the original text.
 *
 * Both modes walk the entities in **reverse text order** so that
 * mutations at later offsets never invalidate the ranges of earlier
 * entities we still need to process.
 *
 * Entities are matched to DOM ranges via the DocxAnchorMap built from
 * the freshly-rendered container. We do NOT rebuild the anchor map
 * after mutations because we only need it for this single pass.
 */

import type { DocxAnchorMap } from './docx-anchor-map';
import { entityClassName, getEntityTypeInfo } from './entity-types';

/** Minimal shape of an entity record we need from the backend. */
export interface OverlayEntity {
  text: string;
  entity_type: string;
  start: number;
  end: number;
  score: number;
  source_layer?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Lifecycle state of an entity inside the interactive workspace:
 *
 *  - `pending`  — detected by the NER pipeline, not yet reviewed.
 *  - `accepted` — user explicitly confirmed this is a real entity.
 *  - `rejected` — user chose "Do not anonymize" for this span.
 *                 Still highlighted on the left (dashed/grey) so the
 *                 user can see what was skipped, but NOT replaced on
 *                 the right pane.
 *  - `custom`   — user manually added this entity via text selection.
 */
export type EntityState = 'pending' | 'accepted' | 'rejected' | 'custom';

/** An entity that carries a stable id + lifecycle state. */
export interface InteractiveEntity extends OverlayEntity {
  id: string;
  state: EntityState;
}

export interface AppliedEntity {
  entity: OverlayEntity;
  marks: HTMLElement[];
}

export interface ApplyEntitiesOptions {
  /**
   * How to render each entity.
   *
   * - `highlight`   keeps original text, wraps it in a `<mark>`.
   * - `placeholder` replaces the range with the entity's placeholder.
   */
  mode: 'highlight' | 'placeholder';
  /**
   * Called once per successfully applied entity. Useful for diagnostics
   * and for the interactive layer in future iterations.
   */
  onApplied?: (entity: OverlayEntity, marks: HTMLElement[]) => void;
}

/**
 * Apply a list of detected entities to a rendered container.
 *
 * Returns the entities that were successfully applied, each with the
 * `<mark>` elements they produced. Entities whose range could not be
 * resolved (e.g. due to a plain-text mismatch) are silently skipped —
 * we log a single console warning with the count.
 */
export function applyEntities(
  container: HTMLElement,
  anchorMap: DocxAnchorMap,
  entities: OverlayEntity[],
  options: ApplyEntitiesOptions,
): AppliedEntity[] {
  if (entities.length === 0) return [];

  // Process in reverse start-offset order so DOM mutations at later
  // offsets never invalidate the still-live ranges of earlier ones.
  const sorted = [...entities].sort((a, b) => b.start - a.start);

  const applied: AppliedEntity[] = [];
  let skipped = 0;

  for (const entity of sorted) {
    const range = anchorMap.toRange(entity.start, entity.end);
    if (!range) {
      skipped++;
      continue;
    }

    // Sanity check: the range's text should match the backend's
    // `entity.text`. If it doesn't, the plain-text alignment between
    // backend and frontend has drifted and we'd be highlighting the
    // wrong span. Better to skip than to mislead the user.
    const rangeText = range.toString();
    if (!textsMatch(rangeText, entity.text)) {
      skipped++;
      // eslint-disable-next-line no-console
      console.warn(
        '[Velum] entity text mismatch — skipping',
        { expected: entity.text, got: rangeText, start: entity.start, end: entity.end },
      );
      continue;
    }

    let marks: HTMLElement[] = [];
    try {
      if (options.mode === 'highlight') {
        marks = wrapRangeWithMark(range, entity);
      } else {
        marks = replaceRangeWithPlaceholder(range, entity);
      }
    } catch (e) {
      skipped++;
      // eslint-disable-next-line no-console
      console.warn('[Velum] failed to apply entity', entity, e);
      continue;
    }

    if (marks.length === 0) {
      skipped++;
      continue;
    }

    applied.push({ entity, marks });
    options.onApplied?.(entity, marks);
  }

  if (skipped > 0) {
    // eslint-disable-next-line no-console
    console.warn(`[Velum] ${skipped} of ${entities.length} entities could not be applied`);
  }

  // Return in original (ascending) order for predictable downstream use.
  applied.sort(
    (a, b) => a.entity.start - b.entity.start,
  );
  return applied;
}

/**
 * Tests whether the DOM-extracted range text matches the backend's
 * entity text, tolerating whitespace-only differences (Word runs
 * sometimes split on NBSP or soft hyphens that docx-preview renders
 * slightly differently from python-docx).
 */
function textsMatch(domText: string, backendText: string): boolean {
  if (domText === backendText) return true;
  const normalize = (s: string) =>
    s.replace(/\s+/g, ' ').replace(/[\u00a0\u200b-\u200d\ufeff]/g, '').trim();
  return normalize(domText) === normalize(backendText);
}

/**
 * Wrap a range with a `<mark>` element while preserving the original
 * DOM children. Handles the case where the range spans multiple Text
 * nodes (common inside Word runs with inline formatting).
 *
 * Uses Range.extractContents() to pull the fragment out, wraps it in a
 * single `<mark>`, then reinserts. The mark may therefore contain
 * multiple span/run children with their own classes — that's fine,
 * they keep their own styling.
 */
function wrapRangeWithMark(range: Range, entity: OverlayEntity): HTMLElement[] {
  const doc = range.startContainer.ownerDocument;
  if (!doc) return [];

  const mark = doc.createElement('mark');
  mark.className = composeEntityClass(entity);
  applyEntityDataset(mark, entity);

  const fragment = range.extractContents();
  mark.appendChild(fragment);
  range.insertNode(mark);

  return [mark];
}

/**
 * Replace the range contents with a `<mark>` whose text is the
 * entity's placeholder token (e.g. `[ЛИЦО_1]`). Used on the
 * anonymized pane.
 */
function replaceRangeWithPlaceholder(
  range: Range,
  entity: OverlayEntity,
): HTMLElement[] {
  const doc = range.startContainer.ownerDocument;
  if (!doc) return [];

  const placeholder =
    (entity.metadata?.placeholder as string | undefined) ??
    fallbackPlaceholder(entity);

  const mark = doc.createElement('mark');
  mark.className = `${composeEntityClass(entity)} velum-entity--placeholder`;
  applyEntityDataset(mark, entity);
  mark.textContent = placeholder;

  range.deleteContents();
  range.insertNode(mark);

  return [mark];
}

function applyEntityDataset(mark: HTMLElement, entity: OverlayEntity): void {
  mark.dataset.entityType = entity.entity_type;
  mark.dataset.entityStart = String(entity.start);
  mark.dataset.entityEnd = String(entity.end);
  if (entity.metadata?.placeholder) {
    mark.dataset.placeholder = String(entity.metadata.placeholder);
  }
  if (entity.source_layer) {
    mark.dataset.source = entity.source_layer;
  }
  // Stable id + lifecycle state (iteration 3). Falls back gracefully
  // for plain OverlayEntity records that don't carry these fields.
  const interactive = entity as Partial<InteractiveEntity>;
  if (interactive.id) {
    mark.dataset.entityId = interactive.id;
  } else if (entity.metadata?.id) {
    mark.dataset.entityId = String(entity.metadata.id);
  }
  if (interactive.state) {
    mark.dataset.entityState = interactive.state;
  }
  const info = getEntityTypeInfo(entity.entity_type);
  mark.title = `${info.labelRu}${
    entity.metadata?.placeholder ? ` → ${entity.metadata.placeholder}` : ''
  }`;
}

/**
 * Compose the full CSS class for a mark: base type colour + state
 * modifier if present. State modifiers (`--rejected`, `--accepted`,
 * `--custom`) drive the visual distinction between pipeline-detected
 * entities, user-confirmed ones, rejections, and manual additions.
 */
function composeEntityClass(entity: OverlayEntity): string {
  const base = entityClassName(entity.entity_type);
  const state = (entity as Partial<InteractiveEntity>).state;
  return state && state !== 'pending' ? `${base} velum-entity--${state}` : base;
}

/** Produce a placeholder when the backend didn't supply one. */
function fallbackPlaceholder(entity: OverlayEntity): string {
  const info = getEntityTypeInfo(entity.entity_type);
  return `[${info.labelRu.toUpperCase()}]`;
}

/**
 * Remove every `.velum-entity` mark from a container, unwrapping the
 * children back into the surrounding DOM. Used when re-applying
 * entities after a re-render.
 */
export function clearEntityMarks(container: HTMLElement): void {
  const marks = container.querySelectorAll<HTMLElement>('mark.velum-entity');
  for (const mark of marks) {
    const parent = mark.parentNode;
    if (!parent) continue;
    while (mark.firstChild) {
      parent.insertBefore(mark.firstChild, mark);
    }
    parent.removeChild(mark);
  }
}

/**
 * Aggregate entity counts by type. Returned map is keyed by entity
 * code and preserves insertion order.
 */
export function groupEntityCounts(
  entities: OverlayEntity[],
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const e of entities) {
    counts.set(e.entity_type, (counts.get(e.entity_type) ?? 0) + 1);
  }
  return counts;
}

export interface RerenderResult {
  /**
   * Anchor map built AFTER entity application — references the
   * post-mutation Text nodes, which is what the selection handler
   * needs for Range→offset lookups. See the comment in
   * `rerenderPaneFromClean` below for the full rationale.
   */
  anchorMap: DocxAnchorMap;
  /** Entities actually applied after filtering and DOM mutation. */
  applied: AppliedEntity[];
}

/**
 * Completely rerender a pane from clean HTML + a fresh entity list.
 *
 * This is the iteration-3 workhorse: whenever the user accepts /
 * rejects / changes type / adds or removes an entity, or toggles a
 * filter, we do NOT try to surgically patch the existing DOM. Instead
 * we blow away the innerHTML, restore the clean (pre-overlay) HTML,
 * rebuild the anchor map, and re-apply the filtered entity set. This
 * is simpler to reason about, idempotent, and cheap enough for
 * contract-sized documents.
 *
 * Rejected entities are still overlaid in `highlight` mode (so the
 * user sees what will NOT be anonymized), but skipped entirely in
 * `placeholder` mode (so the right pane keeps the original text).
 *
 * ANCHOR MAP LIFECYCLE — the subtle bit
 * -------------------------------------
 * `applyEntities` needs an anchor map to translate each entity's
 * plain-text `[start, end)` into a DOM Range. That map MUST be built
 * on the pristine (pre-mark) DOM, because the plain-text offsets were
 * computed against pristine text.
 *
 * However, wrapping a range with `<mark>` (or replacing it with a
 * placeholder) SPLITS Text nodes. The Text nodes referenced by the
 * initial map's `nodeToSegment` lookup table are now either truncated
 * or live alongside brand-new sibling Text nodes that the map has
 * never seen. If we returned the initial map, every subsequent
 * user-selection that started inside one of those post-mutation Text
 * nodes would miss the map lookup and `rangeToOffsets` would return
 * `null` → the selection toolbar would never fire. (This was the
 * root cause of the iter3.1/3.2 "popover never appears" bug.)
 *
 * Fix: after `applyEntities` runs, rebuild the anchor map on the now-
 * mutated container. The plain text is identical for `highlight` mode
 * (marks preserve text content) and intentionally different for
 * `placeholder` mode (marks contain the `[LICO_1]` substitute, which
 * is exactly what the right-pane selection handler wants to see).
 * Either way, the returned map references the Text nodes that are
 * actually live in the DOM, so selection → Range → offset lookups
 * work reliably.
 */
export function rerenderPaneFromClean(
  container: HTMLElement,
  cleanHtml: string,
  buildAnchorMap: (container: HTMLElement) => DocxAnchorMap,
  entities: InteractiveEntity[],
  options: ApplyEntitiesOptions,
): RerenderResult {
  // Reset DOM.
  container.innerHTML = cleanHtml;
  // Pristine map — used ONLY to resolve pre-mutation entity offsets.
  const pristineMap = buildAnchorMap(container);

  const visible =
    options.mode === 'placeholder'
      ? entities.filter((e) => e.state !== 'rejected')
      : entities;

  const applied = applyEntities(container, pristineMap, visible, options);

  // Rebuild the anchor map against the post-mutation DOM so that the
  // selection handler's Range→offset lookups land on the correct Text
  // nodes. This is the map we return and that callers store in their
  // refs.
  const anchorMap = buildAnchorMap(container);
  return { anchorMap, applied };
}

/**
 * Translate offsets in the RIGHT (anonymized) pane's plain text back to
 * offsets in the ORIGINAL (left) text. Used when the user selects text
 * in the anonymized pane to add a custom entity: we need to know where
 * that span lives in the left-pane coordinate system so the backend
 * always sees a single source of truth.
 *
 * Model: the right pane is the left pane with every non-rejected
 * entity's original span replaced by its placeholder token. The plain
 * text therefore alternates between 1:1 untouched segments and
 * placeholder regions. We walk the substitution list in order,
 * accumulating running left and right cursors, until we locate the
 * segment containing the selection.
 *
 * Returns `null` if the selection touches or crosses a placeholder —
 * we can't cleanly anonymize across an already-anonymized span.
 */
export function rightOffsetsToLeft(
  rightStart: number,
  rightEnd: number,
  renderedEntities: InteractiveEntity[],
): { start: number; end: number } | null {
  if (rightEnd < rightStart) return null;

  // Only non-rejected entities are replaced in the right pane.
  const subs = renderedEntities
    .filter((e) => e.state !== 'rejected')
    .sort((a, b) => a.start - b.start);

  let leftCursor = 0;
  let rightCursor = 0;

  for (const e of subs) {
    // Untouched segment [leftCursor, e.start) maps 1:1 to
    // [rightCursor, rightCursor + untouchedLen) in right-space.
    const untouchedLen = e.start - leftCursor;
    const segRightStart = rightCursor;
    const segRightEnd = rightCursor + untouchedLen;

    // Fully contained in this untouched segment — clean 1:1 map.
    if (rightStart >= segRightStart && rightEnd <= segRightEnd) {
      return {
        start: leftCursor + (rightStart - segRightStart),
        end: leftCursor + (rightEnd - segRightStart),
      };
    }

    // Selection straddles the border between untouched text and the
    // placeholder that follows it — reject.
    if (
      rightStart >= segRightStart &&
      rightStart < segRightEnd &&
      rightEnd > segRightEnd
    ) {
      return null;
    }

    // Advance past this untouched segment and the placeholder.
    const placeholderLen = placeholderLengthOf(e);
    leftCursor = e.end;
    rightCursor = segRightEnd + placeholderLen;

    // Selection entirely inside the placeholder — reject (placeholder
    // clicks should use the popover flow instead).
    if (rightStart >= segRightEnd && rightEnd <= rightCursor) {
      return null;
    }

    // Selection starts inside the placeholder and continues past it —
    // reject.
    if (rightStart >= segRightEnd && rightStart < rightCursor) {
      return null;
    }
  }

  // Tail: whatever comes after the last substitution maps 1:1.
  if (rightStart >= rightCursor) {
    return {
      start: leftCursor + (rightStart - rightCursor),
      end: leftCursor + (rightEnd - rightCursor),
    };
  }

  return null;
}

function placeholderLengthOf(e: InteractiveEntity): number {
  const p = e.metadata?.placeholder as string | undefined;
  if (p && p.length > 0) return p.length;
  // Fallback matches applyEntities fallbackPlaceholder shape.
  return e.end - e.start;
}

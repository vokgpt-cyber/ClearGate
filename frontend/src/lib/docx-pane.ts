/**
 * DocxPane — encapsulates the (container, cleanHtml, anchorMap) triple
 * behind a single object whose `getAnchorMap()` always returns a freshly
 * built map. This makes it impossible for callers to hold a stale
 * AnchorMap reference, which was the root cause of the recurring
 * IndexSizeError / "popover never appears" bug class in iter3.x.
 *
 * The class is intentionally tiny — it is a guard rail, not an
 * abstraction layer. All the heavy lifting still lives in
 * `docx-anchor-map` (offset ↔ DOM translation) and `entity-overlay`
 * (`rerenderPaneFromClean`). DocxPane just hides the references that
 * could go stale.
 *
 * Lifecycle:
 *   1. `DocxViewer` finishes rendering and fires `onReady(container)`.
 *   2. The owner (`SplitWorkspace`) constructs `new DocxPane(container)`.
 *      The constructor snapshots `container.innerHTML` as the immutable
 *      clean baseline.
 *   3. The owner calls `pane.rerender(entities, options)` whenever the
 *      entity list changes (initial detection, accept/reject/add/remove,
 *      filter toggle). Each rerender restores the clean snapshot and
 *      re-applies the overlay in one shot.
 *   4. The owner reads selection offsets via
 *      `pane.getAnchorMap().rangeToOffsets(range)` — always against the
 *      live DOM, never against a cached map.
 *   5. The DocxPane instance is replaced (not mutated) when the
 *      underlying document changes; the parent's `key={documentId}`
 *      remount + the document-change `useEffect` cleanup ensure the old
 *      instance is dropped.
 */

import {
  buildDocxAnchorMap,
  type DocxAnchorMap,
} from './docx-anchor-map';
import {
  rerenderPaneFromClean,
  type AppliedEntity,
  type ApplyEntitiesOptions,
  type InteractiveEntity,
} from './entity-overlay';

export interface DocxPaneRerenderResult {
  /** Entities actually drawn after filtering / DOM mutation. */
  applied: AppliedEntity[];
}

/**
 * Owns one rendered docx-preview container plus the immutable clean
 * HTML snapshot taken right after the renderer signalled `onReady`.
 *
 * Anyone who needs an anchor map MUST go through `getAnchorMap()`,
 * which always builds a fresh map against the current DOM. There is
 * no public field that exposes a cached map — by construction.
 */
export class DocxPane {
  private readonly container: HTMLElement;
  private readonly cleanHtml: string;

  constructor(container: HTMLElement) {
    this.container = container;
    // Snapshot the pristine post-render DOM. Subsequent `rerender`
    // calls will restore from this snapshot before applying overlays.
    this.cleanHtml = container.innerHTML;
  }

  /**
   * Underlying container element. Use sparingly — only for use cases
   * that genuinely need it (event delegation, `.contains()` checks,
   * imperative style.zoom assignment). Do NOT mutate its DOM directly;
   * go through `rerender()` instead.
   */
  getContainer(): HTMLElement {
    return this.container;
  }

  /**
   * Always builds a fresh anchor map against the current DOM. Callers
   * MUST NOT cache the return value across DOM mutations — store the
   * `DocxPane` instead and call this method again when needed. This is
   * the whole point of the class: by routing every read through this
   * method we make stale-map bugs structurally impossible.
   */
  getAnchorMap(): DocxAnchorMap {
    return buildDocxAnchorMap(this.container);
  }

  /** Convenience for callers that only need the plain text. */
  getPlainText(): string {
    return this.getAnchorMap().plainText;
  }

  /**
   * Restore the clean HTML snapshot and re-apply the entity overlay
   * in one shot. This is the ONLY method that mutates the DOM owned
   * by this pane.
   */
  rerender(
    entities: InteractiveEntity[],
    options: ApplyEntitiesOptions,
  ): DocxPaneRerenderResult {
    const result = rerenderPaneFromClean(
      this.container,
      this.cleanHtml,
      buildDocxAnchorMap,
      entities,
      options,
    );
    return { applied: result.applied };
  }
}

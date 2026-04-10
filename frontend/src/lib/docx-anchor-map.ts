/**
 * DocxAnchorMap — bridges plain text and rendered DOCX DOM.
 *
 * docx-preview renders a DOCX file into a DOM tree with paragraphs, runs,
 * tables, lists, etc. To later overlay entity highlights onto that tree,
 * we need a way to translate a character offset in the flat plain text
 * (which is what the NER pipeline operates on) into a concrete DOM
 * position (text node + offset inside that node) and vice versa.
 *
 * This utility walks the rendered container once, produces:
 *   - a `plainText` string that is the concatenation of all visible text
 *     in document order, with `\n` inserted between block-level elements
 *   - a list of `segments`, each mapping a contiguous range of the
 *     plain-text string to a specific `Text` DOM node
 *
 * From that, callers can:
 *   - look up a DOM position for any plain-text offset
 *   - construct a `Range` spanning any `[start, end)` plain-text range
 *
 * This is used by Iteration 2 (overlay highlighting), but we build it in
 * Iteration 1 so the infrastructure is ready and testable.
 */

/**
 * Leaf block-level tags that insert a paragraph separator between them.
 *
 * Only tags that actually carry text go here. Container tags such as
 * `<section>` (docx-preview's page wrapper), `<article>`, `<table>`, `<tr>`,
 * `<ul>`/`<ol>` etc. are intentionally *excluded* — walking them as blocks
 * would pull in the whitespace that browsers create between their child
 * elements (e.g. the indentation between `<section>` and `<p>` in the
 * rendered DOM) and pollute the plain text stream.
 */
const BLOCK_TAGS = new Set([
  'P',
  'LI',
  'TH',
  'TD',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'BLOCKQUOTE',
  'CAPTION',
]);

export interface AnchorSegment {
  /** The Text DOM node this segment points to. */
  node: Text;
  /** Inclusive start offset in the flat plain text. */
  plainStart: number;
  /** Exclusive end offset in the flat plain text. */
  plainEnd: number;
}

export interface DocxAnchorMap {
  /** Concatenated plain text in document order. */
  plainText: string;
  /** Segments in ascending plain-text order. */
  segments: AnchorSegment[];
  /**
   * Resolve a plain-text offset to a `{node, offset}` pair.
   * Returns `null` if the offset is out of range.
   */
  toDomPosition(offset: number): { node: Text; offset: number } | null;
  /**
   * Build a DOM Range for a `[start, end)` plain-text range.
   * Returns `null` if either boundary cannot be resolved.
   */
  toRange(start: number, end: number): Range | null;
  /**
   * Convert a DOM Range (e.g. from a user selection) into a
   * `[start, end)` pair in plain-text space. Returns `null` if either
   * endpoint is not inside a known text segment.
   */
  rangeToOffsets(range: Range): { start: number; end: number } | null;
}

/**
 * Build a DocxAnchorMap from a rendered docx-preview container element.
 */
export function buildDocxAnchorMap(container: HTMLElement): DocxAnchorMap {
  const segments: AnchorSegment[] = [];
  let plain = '';

  // Collect block-level elements in document order.
  const blocks: HTMLElement[] = [];
  const elementWalker = document.createTreeWalker(
    container,
    NodeFilter.SHOW_ELEMENT,
    null,
  );
  let current: Node | null = elementWalker.currentNode;
  while (current) {
    if (
      current.nodeType === Node.ELEMENT_NODE &&
      BLOCK_TAGS.has((current as HTMLElement).tagName)
    ) {
      blocks.push(current as HTMLElement);
    }
    current = elementWalker.nextNode();
  }

  // Keep only "leaf" blocks — those that do not contain another block from
  // our list. This is a safety net against container blocks (e.g. a `<td>`
  // that wraps a nested `<p>`) whose direct-child whitespace would
  // otherwise leak into the plain-text stream.
  const blockSelector = Array.from(BLOCK_TAGS)
    .map((tag) => tag.toLowerCase())
    .join(',');
  const leafBlocks =
    blockSelector.length > 0
      ? blocks.filter((block) => !block.querySelector(blockSelector))
      : blocks;

  // Fallback: if the renderer used unknown tags, walk the whole container
  // as a single block so we still get a usable map.
  const targets = leafBlocks.length > 0 ? leafBlocks : [container];
  const blockSet = new Set(targets);

  for (let b = 0; b < targets.length; b++) {
    const block = targets[b];

    const textWalker = document.createTreeWalker(
      block,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          // Skip text inside nested blocks that are in our list to
          // avoid double-counting (we'll visit them as their own block).
          let parent = node.parentElement;
          while (parent && parent !== block) {
            if (BLOCK_TAGS.has(parent.tagName) && blockSet.has(parent)) {
              return NodeFilter.FILTER_REJECT;
            }
            parent = parent.parentElement;
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      },
    );

    let textNode = textWalker.nextNode() as Text | null;
    while (textNode) {
      const text = textNode.data;
      if (text.length > 0) {
        const start = plain.length;
        plain += text;
        const end = plain.length;
        segments.push({ node: textNode, plainStart: start, plainEnd: end });
      }
      textNode = textWalker.nextNode() as Text | null;
    }

    // Paragraph separator after each block except the last.
    if (b < targets.length - 1) {
      plain += '\n';
    }
  }

  // Node → segment index (for fast Range→offset lookup).
  const nodeToSegment = new Map<Text, number>();
  for (let i = 0; i < segments.length; i++) {
    nodeToSegment.set(segments[i].node, i);
  }

  return {
    plainText: plain,
    segments,
    toDomPosition(offset: number) {
      return resolveOffset(segments, offset);
    },
    toRange(start: number, end: number) {
      if (start > end) return null;
      const startPos = resolveOffset(segments, start);
      const endPos = resolveOffset(segments, end);
      if (!startPos || !endPos) return null;
      const range = document.createRange();
      range.setStart(startPos.node, startPos.offset);
      range.setEnd(endPos.node, endPos.offset);
      return range;
    },
    rangeToOffsets(range: Range) {
      return rangeToPlainOffsets(range, segments, nodeToSegment);
    },
  };
}

/**
 * Translate a DOM Range into plain-text offsets. Handles the common
 * case where the range endpoints are directly inside a tracked Text
 * node, and the "container = element" case (e.g. a range starts at the
 * beginning of a `<p>` rather than inside one of its text children) by
 * descending to the closest text segment.
 */
function rangeToPlainOffsets(
  range: Range,
  segments: AnchorSegment[],
  nodeToSegment: Map<Text, number>,
): { start: number; end: number } | null {
  const startOffset = nodeToPlainOffset(
    range.startContainer,
    range.startOffset,
    segments,
    nodeToSegment,
    'start',
  );
  const endOffset = nodeToPlainOffset(
    range.endContainer,
    range.endOffset,
    segments,
    nodeToSegment,
    'end',
  );
  if (startOffset == null || endOffset == null) return null;
  if (endOffset < startOffset) return null;
  return { start: startOffset, end: endOffset };
}

function nodeToPlainOffset(
  node: Node,
  offsetInNode: number,
  segments: AnchorSegment[],
  nodeToSegment: Map<Text, number>,
  side: 'start' | 'end',
): number | null {
  // Text node case — direct segment lookup.
  if (node.nodeType === Node.TEXT_NODE) {
    const seg = nodeToSegment.get(node as Text);
    if (seg == null) return null;
    return segments[seg].plainStart + offsetInNode;
  }

  // Element case — DOM gives us an offset among child nodes. Dig into
  // the closest child that has a mapped text segment.
  if (node.nodeType === Node.ELEMENT_NODE) {
    const el = node as Element;
    const children = el.childNodes;
    if (side === 'start') {
      // Find the first text descendant at or after offsetInNode whose
      // segment we know about.
      for (let i = offsetInNode; i < children.length; i++) {
        const off = firstTextSegmentOffset(children[i], segments, nodeToSegment);
        if (off != null) return off;
      }
      // Empty or past the end — fall back to previous child's end.
      for (let i = Math.min(offsetInNode, children.length) - 1; i >= 0; i--) {
        const off = lastTextSegmentOffset(children[i], segments, nodeToSegment);
        if (off != null) return off;
      }
    } else {
      // Walk backwards for the end side, then forwards as fallback.
      for (let i = offsetInNode - 1; i >= 0; i--) {
        const off = lastTextSegmentOffset(children[i], segments, nodeToSegment);
        if (off != null) return off;
      }
      for (let i = offsetInNode; i < children.length; i++) {
        const off = firstTextSegmentOffset(children[i], segments, nodeToSegment);
        if (off != null) return off;
      }
    }
  }

  return null;
}

function firstTextSegmentOffset(
  node: Node,
  segments: AnchorSegment[],
  nodeToSegment: Map<Text, number>,
): number | null {
  if (node.nodeType === Node.TEXT_NODE) {
    const seg = nodeToSegment.get(node as Text);
    if (seg != null) return segments[seg].plainStart;
    return null;
  }
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
  let n = walker.nextNode();
  while (n) {
    const seg = nodeToSegment.get(n as Text);
    if (seg != null) return segments[seg].plainStart;
    n = walker.nextNode();
  }
  return null;
}

function lastTextSegmentOffset(
  node: Node,
  segments: AnchorSegment[],
  nodeToSegment: Map<Text, number>,
): number | null {
  if (node.nodeType === Node.TEXT_NODE) {
    const seg = nodeToSegment.get(node as Text);
    if (seg != null) return segments[seg].plainEnd;
    return null;
  }
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
  let n = walker.nextNode();
  let last: Text | null = null;
  while (n) {
    if (nodeToSegment.has(n as Text)) last = n as Text;
    n = walker.nextNode();
  }
  if (last) {
    const seg = nodeToSegment.get(last);
    if (seg != null) return segments[seg].plainEnd;
  }
  return null;
}

/**
 * Binary-search for the segment containing `offset`.
 *
 * Offsets that land exactly on a segment's `plainEnd` (i.e. on the
 * synthetic `\n` separator we inserted between block-level segments) are
 * resolved to the end of that preceding segment. This is what callers want
 * when building a range that ends at a block boundary, and it matches the
 * natural interpretation for the very last segment too.
 */
function resolveOffset(
  segments: AnchorSegment[],
  offset: number,
): { node: Text; offset: number } | null {
  if (segments.length === 0) return null;

  let lo = 0;
  let hi = segments.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const seg = segments[mid];
    if (offset < seg.plainStart) {
      hi = mid - 1;
    } else if (offset > seg.plainEnd) {
      lo = mid + 1;
    } else if (offset === seg.plainEnd) {
      // Exactly on a boundary — anchor to the end of this segment.
      return { node: seg.node, offset: seg.node.data.length };
    } else {
      return { node: seg.node, offset: offset - seg.plainStart };
    }
  }

  return null;
}

/** Small convenience for iteration-1 diagnostics. */
export function summariseAnchorMap(map: DocxAnchorMap): {
  plainLength: number;
  segmentCount: number;
  firstChars: string;
} {
  return {
    plainLength: map.plainText.length,
    segmentCount: map.segments.length,
    firstChars: map.plainText.slice(0, 120),
  };
}

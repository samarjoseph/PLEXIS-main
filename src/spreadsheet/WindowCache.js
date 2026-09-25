/**
 * WindowCache — row-indexed, invalidation-aware cache for dataset rows.
 *
 * Architecture:
 *   - Rows are stored by absolute index: Map(rowIndex → rowData)
 *   - Network requests are tracked by offset to prevent duplicate fetches
 *   - Invalidated on sort/filter/search via version bump + clear
 *   - Evicts oldest rows when MAX_CACHE_ROWS is exceeded
 *
 * _row_idx contract (Phase 9 — Locate fix):
 *   Each fetched row now contains `_row_idx` = the original DataFrame index
 *   (absolute, pre-sort, pre-filter). This never changes regardless of view state.
 *   The cache provides findDisplayIndexByRowIdx() to translate from
 *   original index → current display index for virtualized Locate.
 *
 * This cache is the contract between the virtual renderer and the network layer.
 * The renderer asks "give me row N" — cache either answers or signals a fetch.
 */

import { MAX_CACHE_ROWS, FETCH_WINDOW } from './constants.js';

export class WindowCache {
  constructor() {
    /** @type {Map<number, Object>} rowIndex → row data object */
    this.rows = new Map();
    /** @type {Set<number>} offsets currently being fetched (prevent duplicate requests) */
    this.pendingOffsets = new Set();
    /** Monotonically increasing — bumped on every invalidation so stale responses can be detected */
    this.version = 0;
  }

  /** True if a specific row index is cached. */
  hasRow(rowIndex) {
    return this.rows.has(rowIndex);
  }

  /** Get cached row data, or null if not loaded. */
  getRow(rowIndex) {
    return this.rows.get(rowIndex) ?? null;
  }

  /**
   * Store a fetched window of rows.
   * @param {number} offset - Starting row index of the window
   * @param {Object[]} data - Array of row data objects (each has _row_idx)
   */
  setWindow(offset, data) {
    data.forEach((row, i) => {
      this.rows.set(offset + i, row);
    });
    this.pendingOffsets.delete(offset);

    // Evict oldest rows if cache exceeds MAX_CACHE_ROWS
    if (this.rows.size > MAX_CACHE_ROWS) {
      const keys = Array.from(this.rows.keys()).sort((a, b) => a - b);
      const toEvict = keys.slice(0, this.rows.size - MAX_CACHE_ROWS);
      toEvict.forEach(k => this.rows.delete(k));
    }
  }

  /**
   * Mark a fetch offset as pending so we don't issue duplicate requests.
   * @param {number} offset
   */
  markPending(offset) {
    this.pendingOffsets.add(offset);
  }

  /** True if a fetch is already in-flight for this offset. */
  isPending(offset) {
    return this.pendingOffsets.has(offset);
  }

  /**
   * Find the first missing (and not pending) window offset for a given row range.
   * Returns null if all rows in the range are cached or pending.
   *
   * @param {number} startRow
   * @param {number} endRow
   * @returns {number|null} offset to fetch, or null
   */
  firstMissingWindow(startRow, endRow) {
    for (let r = startRow; r <= endRow; r++) {
      if (!this.rows.has(r)) {
        // Align to FETCH_WINDOW boundary for cache efficiency
        const windowOffset = Math.floor(r / FETCH_WINDOW) * FETCH_WINDOW;
        if (!this.pendingOffsets.has(windowOffset)) {
          return windowOffset;
        }
        // Skip ahead to next window boundary
        r = windowOffset + FETCH_WINDOW - 1;
      }
    }
    return null;
  }

  /**
   * Invalidate the entire cache.
   * Called when sort/filter/search changes the result set.
   * @returns {number} new version number
   */
  invalidate() {
    this.rows.clear();
    this.pendingOffsets.clear();
    this.version++;
    return this.version;
  }

  /**
   * Find the display index (position in sorted/filtered view) for an original
   * DataFrame row index (_row_idx).
   *
   * Used by Locate to translate evidence rowIndices (original, absolute)
   * to the correct display position in the current virtualized view.
   *
   * Returns the display index if found in cache, or null if not yet loaded.
   *
   * @param {number} originalRowIdx - The _row_idx value (original DataFrame index)
   * @returns {number|null} displayIndex or null if not in cache
   */
  findDisplayIndexByRowIdx(originalRowIdx) {
    for (const [displayIndex, row] of this.rows) {
      if (row?._row_idx === originalRowIdx) {
        return displayIndex;
      }
    }
    return null;
  }

  /**
   * Build a Map of originalRowIdx → displayIndex from all cached rows.
   * Useful for bulk Locate when highlighting multiple rows.
   *
   * @returns {Map<number, number>} originalRowIdx → displayIndex
   */
  buildRowIdxMap() {
    const map = new Map();
    for (const [displayIndex, row] of this.rows) {
      if (row?._row_idx !== undefined) {
        map.set(row._row_idx, displayIndex);
      }
    }
    return map;
  }

  /** Number of cached rows (for debugging). */
  get size() {
    return this.rows.size;
  }
}

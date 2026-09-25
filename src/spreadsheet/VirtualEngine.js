/**
 * VirtualEngine — pure functions for virtual scrolling calculations.
 *
 * No React, no side effects. All functions are deterministic given the same input.
 *
 * Architecture note:
 *   The virtual engine is the mathematical core of the spreadsheet renderer.
 *   It answers: "given scrollTop, viewportHeight, and totalRows, which rows
 *   should be rendered and at what pixel offsets?"
 *
 * This is intentionally separated from React so it can be:
 *   - Unit tested in isolation
 *   - Reused by future AI operations that need viewport awareness
 *   - Replaced with a more sophisticated engine (e.g. variable row heights)
 */

import { ROW_HEIGHT, HEADER_HEIGHT, OVERSCAN, FETCH_WINDOW } from './constants.js';

/**
 * Calculate the range of row indices that should be rendered.
 *
 * @param {number} scrollTop    - Current scroll position
 * @param {number} clientHeight - Viewport height (excluding header)
 * @param {number} totalRows    - Total rows in the dataset/view
 * @returns {{ startRow: number, endRow: number, firstVisible: number, lastVisible: number }}
 */
export function calculateVisibleRange(scrollTop, clientHeight, totalRows) {
  if (totalRows === 0) return { startRow: 0, endRow: 0, firstVisible: 0, lastVisible: 0 };

  // Account for sticky header height
  const bodyScrollTop = Math.max(0, scrollTop - HEADER_HEIGHT);

  const firstVisible = Math.floor(bodyScrollTop / ROW_HEIGHT);
  const lastVisible  = Math.min(
    totalRows - 1,
    Math.ceil((bodyScrollTop + clientHeight) / ROW_HEIGHT),
  );

  const startRow = Math.max(0, firstVisible - OVERSCAN);
  const endRow   = Math.min(totalRows - 1, lastVisible + OVERSCAN);

  return { startRow, endRow, firstVisible, lastVisible };
}

/**
 * Given a row index, determine which fetch window (offset, limit) contains it.
 * Windows are aligned to FETCH_WINDOW boundaries for cache coherence.
 *
 * @param {number} rowIndex
 * @returns {{ offset: number, limit: number }}
 */
export function rowToWindow(rowIndex) {
  const offset = Math.floor(rowIndex / FETCH_WINDOW) * FETCH_WINDOW;
  return { offset, limit: FETCH_WINDOW };
}

/**
 * Calculate the pixel offset (top) for a given row index.
 * This determines where the row sits in the virtual coordinate space.
 *
 * @param {number} rowIndex
 * @returns {number} pixel offset from top of grid body
 */
export function rowToPixel(rowIndex) {
  return rowIndex * ROW_HEIGHT;
}

/**
 * Calculate the total virtual height of the grid body (excluding header).
 * The scroll container gets this height so the scrollbar represents ALL rows.
 *
 * @param {number} totalRows
 * @returns {number} total height in pixels
 */
export function totalGridHeight(totalRows) {
  return totalRows * ROW_HEIGHT;
}

/**
 * Calculate the scroll position needed to bring a row into view.
 *
 * @param {number} rowIndex
 * @param {number} scrollTop      - Current scroll position
 * @param {number} clientHeight   - Viewport height
 * @returns {number|null} target scrollTop, or null if already visible
 */
export function scrollTopForRow(rowIndex, scrollTop, clientHeight) {
  const rowTop    = HEADER_HEIGHT + rowToPixel(rowIndex);
  const rowBottom = rowTop + ROW_HEIGHT;
  const viewTop   = scrollTop;
  const viewBottom = scrollTop + clientHeight;

  if (rowTop < viewTop + HEADER_HEIGHT) {
    // Row is above viewport
    return rowTop - HEADER_HEIGHT;
  }
  if (rowBottom > viewBottom) {
    // Row is below viewport
    return rowBottom - clientHeight;
  }
  return null; // Already visible
}

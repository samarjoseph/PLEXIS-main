/**
 * Spreadsheet Constants
 * Single source of truth for all layout dimensions and tuning values.
 * Changing ROW_HEIGHT here affects both the virtual engine and the CSS.
 */

export const ROW_HEIGHT        = 32;   // px — fixed row height for deterministic virtualization
export const HEADER_HEIGHT     = 32;   // px — column header row height
export const ROW_NUM_WIDTH     = 56;   // px — row number gutter width
export const DEFAULT_COL_WIDTH = 140;  // px — default column width
export const MIN_COL_WIDTH     = 48;   // px — minimum resizable width
export const OVERSCAN          = 6;    // rows above/below viewport to render
export const FETCH_WINDOW      = 120;  // rows fetched per network request
export const MAX_CACHE_ROWS    = 3000; // maximum rows kept in window cache
export const DEBOUNCE_SEARCH   = 280;  // ms — search input debounce
export const DEBOUNCE_SCROLL   = 16;   // ms — scroll handler throttle (~60fps)

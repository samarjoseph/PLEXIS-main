/**
 * SpreadsheetState — clean state model and future AI contract.
 *
 * PURPOSE:
 *   This module documents the canonical spreadsheet state shape.
 *   It is the boundary between the spreadsheet UI and future AI integration.
 *
 * CURRENT STATUS:
 *   Phase 1 — Foundation only.
 *   The state is maintained locally in the Spreadsheet component.
 *   It is NOT sent to any AI yet.
 *
 * FUTURE AI CONTRACT:
 *   In Phase 2 (AI Mode), this state will be serialized and sent to the AI agent
 *   via the WorkspaceContext snapshot API. The agent will return SpreadsheetCommands.
 *
 * DO NOT add AI logic here yet. Only state shape and documentation.
 */

/**
 * @typedef {Object} CellAddress
 * @property {number} rowIndex    - 0-indexed row in current view
 * @property {string} columnName  - Column name (not index, for stability across reorders)
 */

/**
 * @typedef {Object} CellRange
 * @property {CellAddress} anchor - Start of selection
 * @property {CellAddress} focus  - End/current of selection (may equal anchor)
 */

/**
 * @typedef {Object} ViewportState
 * @property {number} firstVisibleRow    - First row index visible in viewport
 * @property {number} lastVisibleRow     - Last row index visible in viewport
 * @property {number} firstVisibleCol    - First visible column index
 * @property {number} lastVisibleCol     - Last visible column index
 * @property {number} scrollTop          - Current scroll top (px)
 * @property {number} scrollLeft         - Current scroll left (px)
 */

/**
 * @typedef {Object} ColumnMeta
 * @property {string}  name    - Column name
 * @property {string}  dtype   - Pandas dtype string (object, int64, float64, etc.)
 * @property {number}  width   - Current display width in px
 * @property {boolean} hidden  - Whether column is hidden by user
 * @property {boolean} pinned  - Whether column is pinned (frozen) — Phase 2+
 */

/**
 * @typedef {Object} SpreadsheetSelection
 * @property {CellAddress|null}   activeCell      - The single focused cell
 * @property {CellRange|null}     range           - Selected rectangular range
 * @property {number[]}           selectedRows    - Full-row selections (by row index)
 * @property {string[]}           selectedColumns - Full-column selections (by column name)
 */

/**
 * @typedef {Object} SortState
 * @property {string} column    - Column name
 * @property {'asc'|'desc'} direction
 */

/**
 * @typedef {Object} FilterState
 * @property {string} column
 * @property {string} operator  - 'contains' | 'equals' | 'gt' | 'lt' | etc.
 * @property {string} value
 */

/**
 * @typedef {Object} SearchState
 * @property {string}   query           - Current search string
 * @property {number}   totalMatches    - Total matching rows (from backend)
 * @property {number[]} matchingRows    - Row indices of matches in current view
 * @property {number}   currentMatch    - Index into matchingRows (for navigation)
 */

/**
 * The canonical spreadsheet state.
 * This is the complete description of the spreadsheet at any given moment.
 *
 * @typedef {Object} SpreadsheetState
 * @property {string|null}          datasetId
 * @property {number}               totalRows
 * @property {number}               totalColumns
 * @property {ColumnMeta[]}         columns
 * @property {ViewportState}        viewport
 * @property {SpreadsheetSelection} selection
 * @property {SortState|null}       sort
 * @property {FilterState[]}        filters
 * @property {SearchState}          search
 * @property {boolean}              isLoading
 * @property {string|null}          error
 */

/**
 * Create an initial empty spreadsheet state.
 * @returns {SpreadsheetState}
 */
export function createInitialState() {
  return {
    datasetId: null,
    totalRows: 0,
    totalColumns: 0,
    columns: [],

    viewport: {
      firstVisibleRow: 0,
      lastVisibleRow: 0,
      firstVisibleCol: 0,
      lastVisibleCol: 0,
      scrollTop: 0,
      scrollLeft: 0,
    },

    selection: {
      activeCell: null,
      range: null,
      selectedRows: [],
      selectedColumns: [],
    },

    sort: null,
    filters: [],

    search: {
      query: '',
      totalMatches: 0,
      matchingRows: [],
      currentMatch: -1,
    },

    isLoading: false,
    error: null,
  };
}

/**
 * Build a serializable snapshot of the current spreadsheet state for AI context.
 * Future AI Mode will call this to get context before generating commands.
 *
 * @param {SpreadsheetState} state
 * @returns {Object} JSON-safe snapshot
 */
export function buildStateSnapshot(state) {
  return {
    datasetId: state.datasetId,
    totalRows: state.totalRows,
    totalColumns: state.totalColumns,
    columnNames: state.columns.map(c => c.name),
    viewport: { ...state.viewport },
    activeCell: state.selection.activeCell,
    selectedRows: state.selection.selectedRows,
    selectedColumns: state.selection.selectedColumns,
    sort: state.sort,
    filters: state.filters,
    search: { query: state.search.query, totalMatches: state.search.totalMatches },
  };
}

// ─── Future Command Contract (Phase 2) ────────────────────────────────────────
//
// When AI Mode is implemented, the agent will issue SpreadsheetCommands.
// The spreadsheet will execute them deterministically.
//
// Example command types (DO NOT IMPLEMENT YET):
//
//   { type: 'SORT',      payload: { column, direction } }
//   { type: 'FILTER',    payload: { column, operator, value } }
//   { type: 'HIGHLIGHT', payload: { rowIndices, columnNames, color } }
//   { type: 'NAVIGATE',  payload: { rowIndex, columnName } }
//   { type: 'SELECT',    payload: { range: CellRange } }
//   { type: 'SEARCH',    payload: { query } }
//   { type: 'FOCUS',     payload: { rowIndices } }
//   { type: 'CLEAR',     payload: { target: 'highlights' | 'selection' | 'filters' } }
//
// Each command is pure: it transforms SpreadsheetState → SpreadsheetState.
// No mutation. No side effects in the command itself.
// ─────────────────────────────────────────────────────────────────────────────

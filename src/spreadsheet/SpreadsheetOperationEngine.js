/**
 * SpreadsheetOperationEngine — deterministic frontend operation executor.
 *
 * Architecture:
 *   LLM produces a structured operation.
 *   This engine validates + executes it.
 *   The engine NEVER interprets natural language.
 *   The engine NEVER mutates the original dataset.
 *   The engine ONLY interacts with the spreadsheet via callbacks + EventBus.
 *
 * Frontend operations (no backend required):
 *   HIGHLIGHT, NAVIGATE, SELECT_ROWS, FOCUS, CLEAR, SORT, FILTER, SEARCH,
 *   EXPLAIN_ROW, UNDO
 *
 * Backend analytical operations (call /api/spreadsheet/operate):
 *   TOP_N, BOTTOM_N, FIND_DUPLICATES, FIND_MISSING, FIND_OUTLIERS, AGGREGATE
 *
 * @module SpreadsheetOperationEngine
 */

import { EventBus } from '../events/EventBus.js';
import { Events } from '../events/Events.js';
import { PlexisAPI } from '../api.js';

// ─── Target resolution ───────────────────────────────────────────────────────

export const OperationTarget = Object.freeze({
  ORIGINAL_DATASET:   'ORIGINAL_DATASET',
  CURRENT_WORKSPACE:  'CURRENT_WORKSPACE',
  SELECTED_ROWS:      'SELECTED_ROWS',
  CURRENT_VIEW:       'CURRENT_VIEW',
  PREVIOUS_OPERATION: 'PREVIOUS_OPERATION',
});

// ─── Frontend-only operations ────────────────────────────────────────────────

const FRONTEND_OPS = new Set([
  'HIGHLIGHT', 'NAVIGATE', 'SELECT_ROWS', 'FOCUS',
  'CLEAR', 'SORT', 'FILTER', 'SEARCH', 'EXPLAIN_ROW', 'UNDO',
]);

// ─── Backend analytical operations ───────────────────────────────────────────

const BACKEND_OPS = new Set([
  'TOP_N', 'BOTTOM_N', 'FIND_DUPLICATES', 'FIND_MISSING',
  'FIND_OUTLIERS', 'AGGREGATE', 'GROUP',
]);

// ─── Engine class ─────────────────────────────────────────────────────────────

export class SpreadsheetOperationEngine {
  /**
   * @param {object} callbacks — spreadsheet state setters
   * @param {Function} callbacks.setSort
   * @param {Function} callbacks.setFilter
   * @param {Function} callbacks.setSearch
   * @param {Function} callbacks.setHighlightedRows   (Map<number, {color, pulse}>)
   * @param {Function} callbacks.setSelectedRows       (Set<number>)
   * @param {Function} callbacks.setFocusMode          (bool)
   * @param {Function} callbacks.jumpToRow             (rowIndex: number)
   * @param {Function} callbacks.clearHighlights
   * @param {Function} callbacks.onUndo                () => void
   * @param {string}   datasetId
   * @param {string[]} columnNames
   */
  constructor(callbacks, datasetId, columnNames) {
    this._cb          = callbacks;
    this._datasetId   = datasetId;
    this._columnNames = columnNames || [];
  }

  /**
   * Validate and execute a structured operation.
   * Returns { success, resultSummary, error, rowIndices }
   */
  async execute(op) {
    if (!op || !op.type) {
      return { success: false, error: 'No operation type specified.' };
    }

    const type = op.type.toUpperCase();

    // ── Validate column exists (for column-specific ops) ──────────────────
    const colRequiredOps = ['SORT', 'FILTER', 'TOP_N', 'BOTTOM_N', 'FIND_DUPLICATES', 'FIND_MISSING', 'FIND_OUTLIERS'];
    if (colRequiredOps.includes(type) && op.column) {
      const col = op.column;
      if (!this._columnNames.includes(col)) {
        return {
          success: false,
          error: `Column "${col}" not found. Available columns: ${this._columnNames.join(', ')}`,
        };
      }
    }

    // ── Frontend operations ───────────────────────────────────────────────
    if (FRONTEND_OPS.has(type)) {
      return this._executeFrontend(type, op);
    }

    // ── Backend analytical operations ─────────────────────────────────────
    if (BACKEND_OPS.has(type)) {
      return this._executeBackend(type, op);
    }

    return { success: false, error: `Unknown operation type: "${type}"` };
  }

  // ─── Frontend execution ─────────────────────────────────────────────────

  _executeFrontend(type, op) {
    const cb = this._cb;

    switch (type) {
      case 'SORT': {
        cb.setSort({ col: op.column, dir: op.direction || op.order || 'asc' });
        return { success: true, resultSummary: `Sorted by ${op.column} ${op.direction || 'asc'}` };
      }

      case 'FILTER': {
        cb.setFilter([{ col: op.column, operator: op.operator || '=', val: op.value }]);
        return { success: true, resultSummary: `Filtered: ${op.column} ${op.operator} ${op.value}` };
      }

      case 'SEARCH': {
        cb.setSearch(op.query || op.value || '');
        return { success: true, resultSummary: `Searching for "${op.query || op.value}"` };
      }

      case 'NAVIGATE': {
        const row = op.row ?? op.rowIndex ?? op.row_index;
        if (row == null) return { success: false, error: 'NAVIGATE requires a row index.' };
        cb.jumpToRow(Number(row));
        return { success: true, resultSummary: `Navigated to row ${Number(row) + 1}` };
      }

      case 'HIGHLIGHT': {
        const indices = op.rows || op.rowIndices || op.row_indices || [];
        const map = new Map();
        indices.forEach(i => map.set(i, { color: op.color || '#f59e0b', pulse: op.pulse ?? true }));
        cb.setHighlightedRows(map);
        // Navigate to first highlighted row
        if (indices.length > 0) cb.jumpToRow(indices[0]);
        return { success: true, rowIndices: indices, resultSummary: `${indices.length} rows highlighted` };
      }

      case 'SELECT_ROWS': {
        const indices = op.rows || op.rowIndices || op.row_indices || [];
        cb.setSelectedRows(new Set(indices));
        if (indices.length > 0) cb.jumpToRow(indices[0]);
        return { success: true, rowIndices: indices, resultSummary: `${indices.length} rows selected` };
      }

      case 'FOCUS': {
        const indices = op.rows || op.rowIndices || [];
        const map = new Map();
        indices.forEach(i => map.set(i, { color: '#7c3aed', pulse: true }));
        cb.setHighlightedRows(map);
        cb.setFocusMode(true);
        if (indices.length > 0) cb.jumpToRow(indices[0]);
        return { success: true, rowIndices: indices, resultSummary: `Focus: ${indices.length} rows` };
      }

      case 'CLEAR': {
        cb.clearHighlights();
        cb.setFocusMode?.(false);
        cb.setFilter?.([]);
        cb.setSort?.(null);
        cb.setSearch?.('');
        return { success: true, resultSummary: 'Workspace cleared' };
      }

      case 'UNDO': {
        cb.onUndo?.();
        return { success: true, resultSummary: 'Undone' };
      }

      case 'EXPLAIN_ROW': {
        const row = op.row ?? op.rowIndex ?? op.row_index;
        EventBus.emit(Events.WORKSPACE_ACTION_REQUESTED, {
          type: 'explain_row',
          row_indices: row != null ? [row] : [],
          prefilledQuestion: op.prefilledQuestion || `Explain row ${row != null ? row + 1 : ''}`,
        });
        return { success: true, resultSummary: 'Explanation requested' };
      }

      default:
        return { success: false, error: `Unhandled frontend op: ${type}` };
    }
  }

  // ─── Backend analytical execution ────────────────────────────────────────

  async _executeBackend(type, op) {

    let apiOp;
    switch (type) {
      case 'TOP_N':
        apiOp = {
          operation: 'TOP_N',
          column: op.column,
          n: op.n ?? 10,
          order: op.order || op.direction || 'desc',
        };
        break;
      case 'BOTTOM_N':
        apiOp = {
          operation: 'BOTTOM_N',
          column: op.column,
          n: op.n ?? 10,
          order: 'asc',
        };
        break;
      case 'FIND_DUPLICATES':
        apiOp = {
          operation: 'FIND_DUPLICATES',
          columns: op.columns || (op.column ? [op.column] : []),
        };
        break;
      case 'FIND_MISSING':
        apiOp = {
          operation: 'FIND_MISSING',
          columns: op.columns || (op.column ? [op.column] : []),
        };
        break;
      case 'FIND_OUTLIERS':
        apiOp = {
          operation: 'FIND_OUTLIERS',
          column: op.column,
          method: op.method || 'iqr',
        };
        break;
      case 'AGGREGATE':
        apiOp = {
          operation: 'AGGREGATE',
          column: op.column,
          func: op.func || op.function || 'mean',
          group_by: op.groupBy || op.group_by,
        };
        break;
      default:
        apiOp = { operation: type, ...op };
    }

    try {
      const result = await PlexisAPI.operateSpreadsheet(this._datasetId, apiOp);

      if (!result.success && !result.row_indices) {
        return { success: false, error: result.error || 'Operation failed.' };
      }

      // Apply result as HIGHLIGHT on the frontend — Plexis purple with per-column glow
      const rowIndices = result.row_indices || [];
      const resultColumn = op.column || (op.columns && op.columns[0]) || null;
      if (rowIndices.length > 0) {
        const map = new Map();
        rowIndices.forEach(i => map.set(i, {
          color: 'purple',
          pulse: rowIndices.length === 1,  // pulse only for single result
          columnNames: resultColumn ? [resultColumn] : [],
        }));
        this._cb.setHighlightedRows(map);
        // Wait a tick so React can flush the highlight before scrolling
        requestAnimationFrame(() => this._cb.jumpToRow(rowIndices[0]));
      }

      return {
        success: true,
        rowIndices,
        resultColumn,
        resultSummary: result.summary || `${rowIndices.length} rows`,
        stats: result.column_stats,
      };
    } catch (err) {
      return { success: false, error: `Backend error: ${err.message}` };
    }
  }
}

/**
 * Build the full spreadsheet context payload for the AI.
 * This is sent to /api/spreadsheet/interpret alongside the user's query.
 */
export function buildSpreadsheetContext({
  datasetId,
  filename,
  totalRows,
  totalColumns,
  columnNames,
  sort,
  filters,
  search,
  activeCell,
  selectedRows,
  selectedCols,
  highlightedRows,
  operationHistory,
  currentOpIndex,
  viewportStart,
  viewportEnd,
}) {
  return {
    dataset: {
      id: datasetId,
      filename: filename || '',
      totalRows: totalRows || 0,
      totalColumns: totalColumns || 0,
      columnNames: columnNames || [],
    },
    view: {
      sort: sort || null,
      filters: filters || [],
      search: search || null,
      viewportFirstRow: viewportStart ?? 0,
      viewportLastRow: viewportEnd ?? 0,
    },
    selection: {
      activeCell: activeCell || null,
      selectedRows: selectedRows ? Array.from(selectedRows) : [],
      selectedCols: selectedCols ? Array.from(selectedCols) : [],
    },
    highlights: {
      count: highlightedRows?.size ?? 0,
      rowIndices: highlightedRows ? Array.from(highlightedRows.keys()).slice(0, 100) : [],
    },
    operationHistory: {
      total: operationHistory?.length ?? 0,
      currentIndex: currentOpIndex ?? -1,
      recent: (operationHistory || []).slice(-3).map(op => ({
        type: op.type,
        params: op.params,
        resultSummary: op.result?.resultSummary,
      })),
    },
    referenceContext: {
      target: selectedRows?.size > 0 ? 'SELECTED_ROWS'
            : (sort || filters?.length > 0 || search) ? 'CURRENT_WORKSPACE'
            : 'ORIGINAL_DATASET',
    },
  };
}

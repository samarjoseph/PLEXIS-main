/**
 * WorkspaceInterpreter — frontend mirror of backend/workspace/interpreter.py
 *
 * Converts WorkspaceState into a compact natural language summary.
 * Used to build the workspace_state payload sent to /api/ask.
 *
 * Both implementations MUST remain semantically equivalent.
 * If you change the interpretation logic, update both files.
 *
 * Usage:
 *   import { interpret } from '../utils/WorkspaceInterpreter';
 *   const summary = interpret(workspaceState);
 *   // → "Viewing 8,472 rows, filtered by Country equals 'India', sorted by Revenue descending."
 */

/**
 * @param {Object} workspaceState - WorkspaceContext state snapshot
 * @returns {string} Natural language summary
 */
export function interpret(workspaceState) {
  if (!workspaceState) return '';

  const isOpen = workspaceState.isOpen;
  if (!isOpen) return 'The dataset workspace is closed.';

  const parts = [];

  // Total rows
  const totalRows = workspaceState.totalRows;
  if (totalRows) {
    parts.push(`Viewing ${totalRows.toLocaleString()} rows`);
  } else {
    parts.push('Viewing dataset');
  }

  // Active filters
  const filters = workspaceState.filters || [];
  if (filters.length > 0) {
    const filterParts = filters.map((f) => {
      const op = opLabel(f.op || 'eq');
      return `${f.col} ${op} "${f.val}"`;
    });
    parts.push(`filtered by ${filterParts.join(', ')}`);
  }

  // Sort
  const sort = workspaceState.sort;
  if (sort?.col) {
    const dir = sort.dir === 'desc' ? 'descending' : 'ascending';
    parts.push(`sorted by ${sort.col} ${dir}`);
  }

  // Search
  const search = workspaceState.search || '';
  if (search) {
    parts.push(`searching for "${search}"`);
  }

  // Row selection
  const selection = workspaceState.selection || {};
  const selectedRows = selection.rows || [];
  const selectedCols = selection.columns || [];
  if (selectedRows.length > 0) {
    const count = selectedRows.length;
    parts.push(`${count} row${count > 1 ? 's' : ''} selected`);
    if (selectedCols.length > 0) {
      parts.push(`focusing on columns: ${selectedCols.slice(0, 5).join(', ')}`);
    }
  }

  // Active evidence highlight
  const activeEvidence = workspaceState.activeEvidence;
  if (activeEvidence?.description) {
    parts.push(`currently highlighting: ${activeEvidence.description}`);
  }

  // Scroll offset
  const currentOffset = workspaceState.currentOffset || 0;
  if (currentOffset > 0) {
    parts.push(`viewing from row ${currentOffset.toLocaleString()}`);
  }

  if (parts.length === 0) return 'The dataset workspace is open.';
  return parts.join(', ') + '.';
}

function opLabel(op) {
  const labels = {
    eq: 'equals',
    neq: 'does not equal',
    gt: 'greater than',
    gte: 'greater than or equal to',
    lt: 'less than',
    lte: 'less than or equal to',
    contains: 'contains',
    starts: 'starts with',
    ends: 'ends with',
  };
  return labels[op] || op;
}

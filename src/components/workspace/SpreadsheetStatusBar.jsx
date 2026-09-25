/**
 * SpreadsheetStatusBar — 26px bar showing live spreadsheet state.
 *
 * Shows: ready state | row/col counts | selected cell | highlighted count | current operation
 */
import React from 'react';

function fmtNum(n) {
  return typeof n === 'number' ? n.toLocaleString() : n ?? '—';
}

function cellLabel(cell) {
  if (!cell) return null;
  const colIdx = cell.colIndex;
  const col = colIdx < 26
    ? String.fromCharCode(65 + colIdx)
    : String.fromCharCode(64 + Math.floor(colIdx / 26)) + String.fromCharCode(65 + (colIdx % 26));
  return `${col}${cell.rowIndex + 1}`;
}

export default function SpreadsheetStatusBar({
  totalRows,
  totalColumns,
  activeCell,
  selectedRows,       // Set<number>
  selectedCols,       // Set<number>
  highlightedRows,    // Map<number, {...}>
  isAiLoading,
  operationLabel,     // e.g. "Operation 3 of 5"
  onOperationClick,
  isReady,
}) {
  const selLabel = (() => {
    if (selectedRows?.size > 0 && selectedCols?.size > 0) {
      return `${selectedRows.size}R × ${selectedCols.size}C`;
    }
    if (selectedRows?.size > 0) return `${selectedRows.size} row${selectedRows.size > 1 ? 's' : ''}`;
    if (selectedCols?.size > 0) return `${selectedCols.size} col${selectedCols.size > 1 ? 's' : ''}`;
    if (activeCell) return cellLabel(activeCell);
    return null;
  })();

  const highlightCount = highlightedRows?.size ?? 0;

  return (
    <div className="ssg-status-bar" role="status" aria-label="Spreadsheet status">
      <div className={`ssg-status-item ${isReady ? 'ssg-status-item--ready' : ''}`}>
        {isAiLoading ? '✨ Thinking…' : isReady ? '● Ready' : '○ Loading'}
      </div>

      {totalRows > 0 && (
        <div className="ssg-status-item">
          {fmtNum(totalRows)} rows
        </div>
      )}

      {totalColumns > 0 && (
        <div className="ssg-status-item">
          {fmtNum(totalColumns)} cols
        </div>
      )}

      {selLabel && (
        <div className="ssg-status-item ssg-status-item--active">
          {selLabel}
        </div>
      )}

      {highlightCount > 0 && (
        <div className="ssg-status-item" style={{ color: '#fbbf24' }}>
          ✦ {fmtNum(highlightCount)} highlighted
        </div>
      )}

      {operationLabel && (
        <div
          className="ssg-status-item ssg-status-item--op"
          onClick={onOperationClick}
          role="button"
          tabIndex={0}
          onKeyDown={e => e.key === 'Enter' && onOperationClick?.()}
          title="Click to view operation details"
        >
          ✨ {operationLabel}
        </div>
      )}
    </div>
  );
}

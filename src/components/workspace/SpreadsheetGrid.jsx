/**
 * SpreadsheetGrid — virtual row renderer with sticky headers and row numbers.
 *
 * Architecture:
 *   Single overflow:auto container with:
 *   - Column headers: position:sticky top:0
 *   - Row numbers: position:sticky left:0 (inside each row)
 *   - Grid body: position:relative, height = totalRows * ROW_HEIGHT
 *   - Rendered rows: position:absolute, top = rowIndex * ROW_HEIGHT
 *   - Top/bottom spacers are NOT used — rows are absolutely positioned directly
 *
 *   This means the scrollbar ALWAYS represents the full dataset.
 *   Scrolling to the bottom of a 10,000-row dataset reaches row 10,000.
 *   Only startRow…endRow are in the DOM (determined by VirtualEngine).
 *
 * Props:
 *   - All state comes from Spreadsheet.jsx via props (no context access)
 *   - Callbacks are stable useCallback references
 */
import React, { memo, useCallback } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import {
  ROW_HEIGHT, HEADER_HEIGHT, ROW_NUM_WIDTH, DEFAULT_COL_WIDTH,
} from '../../spreadsheet/constants.js';
import { rowToPixel, totalGridHeight } from '../../spreadsheet/VirtualEngine.js';

// ─── SpreadsheetCell ─────────────────────────────────────────────────────────

const SpreadsheetCell = memo(function SpreadsheetCell({
  value, colWidth, isSelected, isActive, isColSelected, isHighlighted,
  onClick, colName,
}) {
  const cls = [
    'ssg-cell',
    isSelected    ? 'ssg-cell--selected'     : '',
    isActive      ? 'ssg-cell--active'       : '',
    isColSelected ? 'ssg-cell--col-selected' : '',
    isHighlighted ? 'ssg-cell--highlighted'  : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={cls}
      style={{ width: colWidth, height: ROW_HEIGHT }}
      onClick={onClick}
      title={value != null ? String(value) : ''}
    >
      {value == null ? (
        <span className="ssg-cell__null">—</span>
      ) : (
        <span className="ssg-cell__value">{String(value)}</span>
      )}
    </div>
  );
});

// ─── SpreadsheetRow ───────────────────────────────────────────────────────────

const SpreadsheetRow = memo(function SpreadsheetRow({
  rowIndex, absoluteTop, rowData, visibleCols, colWidths,
  isRowSelected, isFaded, highlight,
  activeCell, anchorCell, selectedCellSet, selectedCols,
  onCellClick, onRowNumClick, onContextMenu,
  currentOffset,
}) {
  const rowClass = [
    'ssg-row',
    isRowSelected ? 'ssg-row--selected' : '',
    highlight     ? `ssg-row--highlight ssg-row--highlight-${highlight.color}` : '',
    highlight?.pulse ? 'ssg-row--pulse' : '',
    isFaded       ? 'ssg-row--faded' : '',
  ].filter(Boolean).join(' ');

  const rowStyle = {
    top: absoluteTop,
    height: ROW_HEIGHT,
    ...(highlight ? { '--ssg-highlight-color': highlight.color } : {}),
  };

  return (
    <div
      className={rowClass}
      style={rowStyle}
      onContextMenu={(e) => onContextMenu(e, rowIndex, rowData)}
    >
      {/* Row number — sticky left, click to select row */}
      <div
        className="ssg-row-num"
        style={{ width: ROW_NUM_WIDTH, height: ROW_HEIGHT }}
        onClick={(e) => onRowNumClick(rowIndex, e)}
      >
        {currentOffset + rowIndex + 1}
      </div>

      {/* Data cells */}
      {visibleCols.map((col, colIndex) => {
        const cellKey = `${rowIndex}:${colIndex}`;
        return (
          <SpreadsheetCell
            key={col.name}
            value={rowData ? rowData[col.name] : null}
            colWidth={col.width}
            isSelected={selectedCellSet.has(cellKey)}
            isActive={
              activeCell?.rowIndex === rowIndex &&
              activeCell?.colIndex === colIndex
            }
            isColSelected={selectedCols.has(col.name)}
            isHighlighted={highlight?.columnNames?.includes(col.name) ?? false}
            onClick={(e) => onCellClick(rowIndex, colIndex, e)}
            colName={col.name}
          />
        );
      })}
    </div>
  );
});

// ─── ColumnHeader ─────────────────────────────────────────────────────────────

const ColumnHeader = memo(function ColumnHeader({
  col, colIndex, sort, selectedCols, onHeaderClick, onHeaderContextMenu, onResizeStart,
}) {
  const isSorted   = sort?.col === col.name;
  const isSelected = selectedCols.has(col.name);

  return (
    <div
      id={`ssg-col-${col.name}`}
      className={[
        'ssg-col-header',
        isSorted   ? 'ssg-col-header--sorted'   : '',
        isSelected ? 'ssg-col-header--selected' : '',
      ].filter(Boolean).join(' ')}
      style={{ width: col.width, height: HEADER_HEIGHT }}
      onClick={(e) => onHeaderClick(col.name, colIndex, e)}
      onContextMenu={(e) => onHeaderContextMenu(e, col.name)}
      title={`${col.name}  |  ${col.dtype || ''}\nClick to sort  ·  Shift+click to select column  ·  Right-click to hide`}
    >
      <span className="ssg-col-label">{col.name}</span>
      {isSorted && (
        sort.dir === 'asc'
          ? <ChevronUp  size={12} className="ssg-sort-icon" />
          : <ChevronDown size={12} className="ssg-sort-icon" />
      )}
      <div
        className="ssg-resize-handle"
        onMouseDown={(e) => onResizeStart(e, col.name)}
      />
    </div>
  );
});

// ─── SpreadsheetGrid (main export) ────────────────────────────────────────────

export default function SpreadsheetGrid({
  // Data
  totalRows,
  visibleCols,
  getRow,
  currentOffset,

  // Virtual range
  startRow,
  endRow,

  // Scroll container ref (owned by Spreadsheet.jsx)
  scrollRef,
  onScroll,
  onKeyDown,

  // View controls
  sort,
  selectedCols,

  // Selection state
  activeCell,
  anchorCell,
  selectedCellSet,
  selectedRows,

  // Evidence
  highlightedRows,
  focusModeEnabled,

  // Callbacks
  onCellClick,
  onRowNumClick,
  onContextMenu,
  onHeaderClick,
  onHeaderContextMenu,
  onResizeStart,
}) {
  // Total content width: row-num gutter + all visible columns
  const totalWidth = ROW_NUM_WIDTH + visibleCols.reduce((sum, c) => sum + c.width, 0);
  const gridBodyHeight = totalGridHeight(totalRows);

  // Render the range [startRow … endRow]
  const renderedRows = [];
  for (let i = startRow; i <= endRow; i++) {
    const rowData   = getRow(i);
    const highlight = highlightedRows.get(i);
    const isRowSel  = selectedRows.has(i);
    const isFaded   = focusModeEnabled && !highlight && !isRowSel;

    renderedRows.push(
      <SpreadsheetRow
        key={i}
        rowIndex={i}
        absoluteTop={rowToPixel(i)}
        rowData={rowData}
        visibleCols={visibleCols}
        colWidths={null}
        isRowSelected={isRowSel}
        isFaded={isFaded}
        highlight={highlight}
        activeCell={activeCell}
        anchorCell={anchorCell}
        selectedCellSet={selectedCellSet}
        selectedCols={selectedCols}
        onCellClick={onCellClick}
        onRowNumClick={onRowNumClick}
        onContextMenu={onContextMenu}
        currentOffset={currentOffset}
      />
    );
  }

  return (
    <div
      className="ssg-grid"
      ref={scrollRef}
      onScroll={onScroll}
      onKeyDown={onKeyDown}
      tabIndex={0}
      role="grid"
      aria-label="Dataset spreadsheet"
      aria-rowcount={totalRows}
    >
      <div
        className="ssg-grid__content"
        style={{ width: totalWidth, minWidth: '100%' }}
      >
        {/* ── Sticky column header row ─────────────────────────────────── */}
        <div className="ssg-grid__header">
          {/* Corner cell */}
          <div
            className="ssg-corner"
            style={{ width: ROW_NUM_WIDTH, height: HEADER_HEIGHT }}
          />

          {/* Column headers */}
          {visibleCols.map((col, colIndex) => (
            <ColumnHeader
              key={col.name}
              col={col}
              colIndex={colIndex}
              sort={sort}
              selectedCols={selectedCols}
              onHeaderClick={onHeaderClick}
              onHeaderContextMenu={onHeaderContextMenu}
              onResizeStart={onResizeStart}
            />
          ))}
        </div>

        {/* ── Virtual body ─────────────────────────────────────────────── */}
        <div
          className="ssg-grid__body"
          style={{ height: gridBodyHeight }}
        >
          {renderedRows}
        </div>
      </div>
    </div>
  );
}

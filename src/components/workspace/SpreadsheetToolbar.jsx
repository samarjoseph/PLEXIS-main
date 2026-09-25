/**
 * SpreadsheetToolbar — the control bar above the spreadsheet grid.
 *
 * Primary AI interaction: "Ask Agent" input replaces the search box as the primary control.
 * Secondary: Ctrl+F opens a find bar for deterministic text search.
 *
 * Contains:
 *   - Cell reference box (shows active cell address, e.g. "A42")
 *   - Dataset dimensions + filename
 *   - Active sort/filter badges (clickable to clear)
 *   - Evidence chip
 *   - Selection info
 *   - [Ask Agent] input — primary AI interaction
 *   - [✨ AI MODE] toggle
 *   - View mode switcher: [▣ Side-by-side] [▣ Pop-up]
 *   - Loading spinner
 *   - Close button
 *
 * Ctrl+F opens a separate find bar row (secondary, deterministic search).
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  X, RefreshCw, ChevronUp, ChevronDown, Eye,
  ArrowUpDown, Filter, Eraser, Copy, Check,
  Search, ArrowUp, LayoutPanelLeft, Maximize2,
} from 'lucide-react';
import PlexisLogo from '../brand/PlexisLogo';
import { DEBOUNCE_SEARCH } from '../../spreadsheet/constants.js';

export default function SpreadsheetToolbar({
  // Dataset info
  totalRows,
  totalColumns,
  filename,
  isLoading,

  // Active cell
  activeCell,
  visibleCols,
  columnNames,

  // Sort / filter / search
  sort,
  filters,
  search,
  searchResultCount,
  searchResultIndex,

  // Selection
  selectedRows,
  selectedCols,
  copyFlash,

  // Evidence
  activeEvidence,
  hiddenColCount,

  // AI
  onAskAgent,       // (query: string) => void
  isAiLoading,      // bool
  aiModeEnabled,    // bool
  onToggleAiMode,   // () => void

  // View mode
  viewMode,         // 'side_by_side' | 'popup'
  onViewModeChange, // (mode) => void

  // Find bar (Ctrl+F)
  findBarOpen,
  onFindBarOpen,
  onFindBarClose,
  findQuery,
  onFindChange,
  onFindNav,        // ('prev'|'next') => void

  // Callbacks
  onSortClear,
  onFiltersClear,
  onCopy,
  onShowAllColumns,
  onClearHighlights,
  onClose,
}) {
  const [agentInput, setAgentInput] = useState('');
  const agentInputRef = useRef(null);
  const [findInput, setFindInput] = useState(findQuery || '');
  const findDebounceRef = useRef(null);
  const findInputRef = useRef(null);

  // Sync find input when cleared externally
  useEffect(() => { setFindInput(findQuery || ''); }, [findQuery]);

  // Focus find input when bar opens
  useEffect(() => {
    if (findBarOpen) findInputRef.current?.focus();
  }, [findBarOpen]);

  const handleAgentSubmit = useCallback(() => {
    const q = agentInput.trim();
    if (!q || isAiLoading) return;
    onAskAgent?.(q);
    setAgentInput('');
  }, [agentInput, isAiLoading, onAskAgent]);

  const handleAgentKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleAgentSubmit();
    }
  }, [handleAgentSubmit]);

  const handleFindInput = useCallback((e) => {
    const val = e.target.value;
    setFindInput(val);
    clearTimeout(findDebounceRef.current);
    findDebounceRef.current = setTimeout(() => onFindChange?.(val), DEBOUNCE_SEARCH);
  }, [onFindChange]);

  const handleFindClear = useCallback(() => {
    setFindInput('');
    onFindChange?.('');
  }, [onFindChange]);

  // Active cell label, e.g. "B42"
  const activeCellLabel = (() => {
    if (!activeCell) return '';
    const c = activeCell.colIndex;
    const col = c < 26
      ? String.fromCharCode(65 + c)
      : String.fromCharCode(64 + Math.floor(c / 26)) + String.fromCharCode(65 + (c % 26));
    return `${col}${activeCell.rowIndex + 1}`;
  })();

  // Range label when multi-select
  const rangeCellLabel = (() => {
    if (!activeCell) return activeCellLabel;
    if (selectedRows?.size > 1) return `Rows ${Math.min(...selectedRows) + 1}–${Math.max(...selectedRows) + 1}`;
    if (selectedCols?.size > 1) return `Cols ${selectedCols.size}`;
    return activeCellLabel;
  })();

  // Selection summary
  const selectionLabel = (() => {
    if (selectedRows?.size > 0 && selectedCols?.size > 0) {
      return `${selectedRows.size}R × ${selectedCols.size}C`;
    }
    if (selectedRows?.size > 0) return `${selectedRows.size} row${selectedRows.size > 1 ? 's' : ''} selected`;
    if (selectedCols?.size > 0) return `${selectedCols.size} col${selectedCols.size > 1 ? 's' : ''} selected`;
    return null;
  })();

  const hasData = totalRows > 0;

  return (
    <>
      {/* ── Main toolbar row ── */}
      <div className="ssg-toolbar">
        <div className="ssg-toolbar__left">

          {/* Cell reference box */}
          <div className="ssg-cell-ref" title="Active cell reference">
            {rangeCellLabel || ''}
          </div>

          <div className="ssg-toolbar__sep" />

          {/* Dataset dimensions */}
          {hasData && (
            <span
              className={`ssg-toolbar__dims${isLoading ? ' ssg-toolbar__dims--loading' : ''}`}
              title={filename ? `File: ${filename}` : undefined}
            >
              {totalRows.toLocaleString()} × {totalColumns.toLocaleString()}
              {filename ? ` — ${filename}` : ''}
            </span>
          )}

          {/* Active sort badge */}
          {sort && (
            <button
              type="button"
              className="ssg-toolbar__badge ssg-toolbar__badge--sort"
              onClick={onSortClear}
              title={`Sorted by ${sort.col} ${sort.dir} · Click to clear`}
            >
              <ArrowUpDown size={10} />
              {sort.col} {sort.dir === 'asc' ? '↑' : '↓'}
              <X size={9} />
            </button>
          )}

          {/* Active filter badge */}
          {filters?.length > 0 && (
            <button
              type="button"
              className="ssg-toolbar__badge ssg-toolbar__badge--filter"
              onClick={onFiltersClear}
              title={`${filters.length} filter(s) active · Click to clear`}
            >
              <Filter size={10} />
              {filters.length} filter{filters.length > 1 ? 's' : ''}
              <X size={9} />
            </button>
          )}

          {/* Find results badge */}
          {search && searchResultCount > 0 && (
            <span className="ssg-toolbar__badge ssg-toolbar__badge--search">
              <Search size={10} />
              {searchResultCount.toLocaleString()} result{searchResultCount !== 1 ? 's' : ''}
            </span>
          )}

          {/* Hidden columns indicator */}
          {hiddenColCount > 0 && (
            <button
              type="button"
              className="ssg-hidden-cols-btn"
              onClick={onShowAllColumns}
              title={`${hiddenColCount} column(s) hidden — click to show all`}
            >
              <Eye size={11} />
              {hiddenColCount} hidden
            </button>
          )}

          {/* Evidence chip */}
          {activeEvidence && (
            <div className="ssg-evidence-chip" title={activeEvidence.description}>
              <span className="ssg-evidence-dot" />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {activeEvidence.description}
              </span>
              <button
                type="button"
                className="ssg-evidence-clear"
                onClick={onClearHighlights}
                aria-label="Clear highlights"
              >
                <Eraser size={11} />
              </button>
            </div>
          )}

          {/* Selection info */}
          {selectionLabel && (
            <>
              <div className="ssg-toolbar__sep" />
              <span className="ssg-toolbar__sel-info">{selectionLabel}</span>
            </>
          )}

        </div>

        {/* ── Right side ── */}
        <div className="ssg-toolbar__right">

          {/* Ask Agent input — primary AI interaction */}
          <div className={`ssg-ask-agent${isAiLoading ? ' ssg-ask-agent--loading' : ''}`}>
            <PlexisLogo width={13} height={13} className="ssg-ask-agent__icon" />
            <input
              ref={agentInputRef}
              type="text"
              className="ssg-ask-agent__input"
              placeholder={isAiLoading ? 'Thinking…' : 'Ask Plexis about this data…'}
              value={agentInput}
              onChange={e => setAgentInput(e.target.value)}
              onKeyDown={handleAgentKeyDown}
              disabled={isAiLoading}
              aria-label="Ask Plexis AI agent"
              id="ssg-ask-agent-input"
            />
            {agentInput && !isAiLoading && (
              <button
                type="button"
                className="ssg-ask-agent__send"
                onClick={handleAgentSubmit}
                aria-label="Send query to Plexis"
                title="Send (Enter)"
              >
                <ArrowUp size={12} />
              </button>
            )}
          </div>

          {/* AI Mode toggle */}
          <button
            type="button"
            className={`ssg-ai-mode-btn${aiModeEnabled ? ' ssg-ai-mode-btn--active' : ''}`}
            onClick={onToggleAiMode}
            title={aiModeEnabled ? 'AI Mode ON — Plexis controls the workspace' : 'Enable AI Mode'}
            aria-pressed={aiModeEnabled}
          >
            <PlexisLogo width={12} height={12} />
            {aiModeEnabled ? 'AI ON' : 'AI Mode'}
          </button>

          <div className="ssg-toolbar__sep" />

          {/* View mode switcher */}
          <button
            type="button"
            className={`ssg-view-btn${viewMode === 'side_by_side' ? ' ssg-view-btn--active' : ''}`}
            onClick={() => onViewModeChange?.('side_by_side')}
            title="Side-by-side view"
            aria-pressed={viewMode === 'side_by_side'}
          >
            <LayoutPanelLeft size={13} />
          </button>
          <button
            type="button"
            className={`ssg-view-btn${viewMode === 'popup' ? ' ssg-view-btn--active' : ''}`}
            onClick={() => onViewModeChange?.('popup')}
            title="Popup view"
            aria-pressed={viewMode === 'popup'}
          >
            <Maximize2 size={13} />
          </button>

          {/* Copy button */}
          {(selectedRows?.size > 0 || activeCell) && (
            <>
              <div className="ssg-toolbar__sep" />
              <button
                type="button"
                className={`ssg-toolbar__btn${copyFlash ? ' ssg-toolbar__btn--copied' : ''}`}
                onClick={onCopy}
                title="Copy selection (Ctrl+C)"
              >
                {copyFlash ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </>
          )}

          {/* Find (Ctrl+F) */}
          <button
            type="button"
            className="ssg-toolbar__btn"
            onClick={onFindBarOpen}
            title="Find in dataset (Ctrl+F)"
            aria-label="Open find bar"
          >
            <Search size={13} />
          </button>

          {/* Loading indicator */}
          {isLoading && <RefreshCw size={14} className="ssg-spinner" />}

          {/* Close button */}
          <button
            type="button"
            className="ssg-toolbar__btn ssg-toolbar__btn--danger"
            onClick={onClose}
            aria-label="Close workspace"
            title="Close spreadsheet"
          >
            <X size={15} />
          </button>
        </div>
      </div>

      {/* ── Find bar (Ctrl+F) — secondary deterministic search ── */}
      {findBarOpen && (
        <div className="ssg-find-bar" role="search" aria-label="Find in dataset">
          <div className="ssg-find-bar__input-wrap">
            <Search size={12} style={{ color: '#52525b', flexShrink: 0 }} />
            <input
              ref={findInputRef}
              type="text"
              className="ssg-find-bar__input"
              placeholder="Find in dataset…"
              value={findInput}
              onChange={handleFindInput}
              onKeyDown={e => {
                if (e.key === 'Enter') onFindNav?.(e.shiftKey ? 'prev' : 'next');
                if (e.key === 'Escape') { handleFindClear(); onFindBarClose?.(); }
              }}
              aria-label="Find text in dataset"
              id="ssg-find-input"
            />
            {findInput && (
              <button type="button" className="ssg-find-bar__btn" onClick={handleFindClear} aria-label="Clear find">
                <X size={11} />
              </button>
            )}
          </div>

          {/* Result count */}
          {search && (
            <span className="ssg-find-bar__count">
              {searchResultCount > 0 ? `${searchResultIndex + 1} / ${searchResultCount}` : '0 results'}
            </span>
          )}

          {/* Prev / Next */}
          <button
            type="button"
            className="ssg-find-bar__btn"
            onClick={() => onFindNav?.('prev')}
            disabled={!searchResultCount}
            title="Previous match (Shift+Enter)"
          >
            <ChevronUp size={14} />
          </button>
          <button
            type="button"
            className="ssg-find-bar__btn"
            onClick={() => onFindNav?.('next')}
            disabled={!searchResultCount}
            title="Next match (Enter)"
          >
            <ChevronDown size={14} />
          </button>

          <button
            type="button"
            className="ssg-find-bar__close"
            onClick={() => { handleFindClear(); onFindBarClose?.(); }}
            aria-label="Close find bar"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </>
  );
}

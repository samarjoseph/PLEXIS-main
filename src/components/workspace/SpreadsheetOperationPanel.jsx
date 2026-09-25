/**
 * SpreadsheetOperationPanel — Plexis AI Agent result card.
 *
 * Appears below the grid when the Spreadsheet Agent executes an operation.
 * Designed to look and feel like a native Plexis AI message, not a debug panel.
 *
 * Features:
 *   - Operation-aware natural language message
 *   - Result value display (highest found, row location, etc.)
 *   - [ Locate ] [ Undo ] [ Redo ] action buttons
 *   - AI vs Auto source indicator
 *   - Retry on error
 *   - Compact, collapsible design that doesn't cover the spreadsheet
 */
import React, { useState } from 'react';
import {
  X, RotateCcw, RotateCw, MapPin, AlertCircle,
  RefreshCw, Cpu, Zap, ChevronDown, ChevronUp,
} from 'lucide-react';
import PlexisLogo from '../brand/PlexisLogo';

// ─── Operation type → human message ──────────────────────────────────────────

function buildAgentMessage(type, params, result, error) {
  if (error || type === 'ERROR') {
    return null; // handled separately
  }
  const col = params?.column || params?.columns?.[0] || '';
  const n   = params?.n;
  const dir = params?.order || params?.direction;
  const count = result?.rowIndices?.length ?? result?.result_count ?? 0;

  switch (type) {
    case 'TOP_N': {
      if (n === 1) return `I found the highest ${col} value in the dataset.`;
      return `Here are the top ${n} values in ${col}.`;
    }
    case 'BOTTOM_N': {
      if (n === 1) return `I found the lowest ${col} value in the dataset.`;
      return `Here are the bottom ${n} values in ${col}.`;
    }
    case 'FIND_DUPLICATES':
      return count > 0
        ? `I found ${count} duplicate rows based on ${col || 'the selected columns'}.`
        : `No duplicate rows found in ${col || 'the selected columns'}.`;
    case 'FIND_MISSING':
      return count > 0
        ? `I found ${count} rows with missing values.`
        : 'No missing values found in this dataset.';
    case 'FIND_OUTLIERS':
      return count > 0
        ? `I found ${count} outliers in ${col}.`
        : `No outliers detected in ${col}.`;
    case 'FILTER':
      return `I filtered the dataset: ${col} ${params?.operator || '='} ${params?.value}.`;
    case 'SORT':
      return `I sorted ${col} from ${dir === 'desc' ? 'highest to lowest' : 'lowest to highest'}.`;
    case 'NAVIGATE':
      return `I navigated to row ${(params?.row ?? 0) + 1}.`;
    case 'SEARCH':
      return `Searching for "${params?.query || params?.value}".`;
    case 'CLEAR':
      return 'Workspace cleared — all operations removed.';
    case 'UNDO':
      return 'Last operation undone.';
    case 'AGGREGATE': {
      const fn = params?.func || 'mean';
      const val = result?.stats?.result;
      return val != null
        ? `${fn}(${col}) = ${typeof val === 'number' ? val.toLocaleString() : val}`
        : `Calculated ${fn} of ${col}.`;
    }
    case 'HIGHLIGHT':
      return `${count} rows highlighted.`;
    case 'SELECT_ROWS':
      return `${count} rows selected.`;
    case 'UNKNOWN':
      return null; // error state
    default:
      return null;
  }
}

function buildResultCard(type, params, result) {
  if (!result?.success) return null;
  const col = params?.column || '';
  const rowIndices = result?.rowIndices || [];
  const stats = result?.stats || {};

  if (type === 'TOP_N' || type === 'BOTTOM_N') {
    const firstRow = rowIndices[0];
    const maxVal = stats?.max ?? stats?.result;
    const minVal = stats?.min;
    const label = type === 'TOP_N' ? 'Highest' : 'Lowest';
    const shownVal = type === 'TOP_N' ? maxVal : minVal;
    return {
      primary: shownVal != null ? String(shownVal) : null,
      primaryLabel: col ? `${label} ${col}` : label,
      row: firstRow != null ? firstRow + 1 : null,
      column: col,
      count: rowIndices.length,
    };
  }

  if (type === 'FIND_DUPLICATES' || type === 'FIND_MISSING' || type === 'FIND_OUTLIERS') {
    return {
      primary: String(rowIndices.length),
      primaryLabel: type === 'FIND_DUPLICATES' ? 'Duplicate rows' :
                    type === 'FIND_MISSING'     ? 'Rows with missing values' :
                    'Outlier rows',
      count: rowIndices.length,
    };
  }

  if (type === 'AGGREGATE') {
    const val = stats?.result;
    return {
      primary: val != null ? String(typeof val === 'number' ? val.toLocaleString() : val) : null,
      primaryLabel: `${stats?.function || 'result'}(${col})`,
    };
  }

  return null;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function SpreadsheetOperationPanel({
  operation,          // { id, type, params, result, explanation, error, source }
  operationIndex,     // 0-based index in history
  operationTotal,     // total operations in history
  onClose,
  onLocate,           // () => void — scroll + highlight result
  onUndo,             // () => void | null
  onRedo,             // () => void | null
  canUndo,            // bool
  canRedo,            // bool
  onRetry,            // () => void | null
}) {
  const [collapsed, setCollapsed] = useState(false);

  if (!operation) return null;

  const { type, params, result, explanation, error, source } = operation;
  const isError = !!(error) || type === 'UNKNOWN' || type === 'ERROR';
  const hasResult = result?.success && result?.rowIndices?.length > 0;
  const count = result?.rowIndices?.length ?? 0;

  const agentMessage = buildAgentMessage(type, params, result, error);
  const resultCard = buildResultCard(type, params, result);

  // Friendly error text
  const errorText = (() => {
    if (!isError) return null;
    if (type === 'UNKNOWN') {
      return explanation || 'Plexis could not determine what operation to run. Try rephrasing your request.';
    }
    if (error?.includes('No valid models') || error?.includes('All fallback attempts') || error?.includes('No available models')) {
      return 'AI model is temporarily unavailable. Try again in a moment.';
    }
    if (error?.includes('Column') && error?.includes('not found')) {
      return error;
    }
    if (error?.includes('Sorry') || error?.includes('issue generating')) {
      return 'AI model returned an unexpected response. Please try again.';
    }
    return error || 'An error occurred. Try rephrasing your request.';
  })();

  const displayMessage = agentMessage || explanation || null;

  return (
    <div className="ssg-ai-card">
      {/* ── Header ── */}
      <div className="ssg-ai-card__header">
        <div className="ssg-ai-card__title-row">
          <span className="ssg-ai-card__sparkle">
            <PlexisLogo width={14} height={14} className="ssg-ai-card__logo" />
          </span>
          <span className="ssg-ai-card__title">Plexis Agent</span>

          {source === 'heuristic' && (
            <span className="ssg-ai-card__source ssg-ai-card__source--auto" title="Local pattern match (AI unavailable)">
              <Zap size={9} /> Auto
            </span>
          )}
          {source === 'llm' && (
            <span className="ssg-ai-card__source ssg-ai-card__source--ai" title="AI model result">
              <Cpu size={9} /> AI
            </span>
          )}

          <div className="ssg-ai-card__header-actions">
            <button
              type="button"
              className="ssg-ai-card__icon-btn"
              onClick={() => setCollapsed(v => !v)}
              aria-label={collapsed ? 'Expand' : 'Collapse'}
            >
              {collapsed ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
            <button
              type="button"
              className="ssg-ai-card__icon-btn ssg-ai-card__icon-btn--close"
              onClick={onClose}
              aria-label="Dismiss"
            >
              <X size={13} />
            </button>
          </div>
        </div>
      </div>

      {/* ── Body (collapsible) ── */}
      {!collapsed && (
        <div className="ssg-ai-card__body">
          {/* Error state */}
          {isError ? (
            <div className="ssg-ai-card__error">
              <AlertCircle size={14} className="ssg-ai-card__error-icon" />
              <span>{errorText}</span>
            </div>
          ) : (
            <>
              {/* Natural language message */}
              {displayMessage && (
                <p className="ssg-ai-card__message">{displayMessage}</p>
              )}

              {/* Result card — shows the actual found value + location */}
              {resultCard && (
                <div className="ssg-ai-card__result-card">
                  {resultCard.primary != null && (
                    <div className="ssg-ai-card__result-value">
                      <div className="ssg-ai-card__result-num">{resultCard.primary}</div>
                      <div className="ssg-ai-card__result-label">{resultCard.primaryLabel}</div>
                    </div>
                  )}
                  {(resultCard.row != null || resultCard.column) && (
                    <div className="ssg-ai-card__result-meta">
                      {resultCard.row != null && <span>Row {resultCard.row}</span>}
                      {resultCard.row != null && resultCard.column && <span className="ssg-ai-card__result-sep">·</span>}
                      {resultCard.column && <span>Column "{resultCard.column}"</span>}
                    </div>
                  )}
                  {count > 1 && (
                    <div className="ssg-ai-card__result-count">
                      {count} rows highlighted
                    </div>
                  )}
                </div>
              )}

              {/* Simple result summary (no card) */}
              {!resultCard && result?.resultSummary && (
                <div className="ssg-ai-card__summary">
                  ✓ {result.resultSummary}
                </div>
              )}
            </>
          )}

          {/* ── Action buttons ── */}
          <div className="ssg-ai-card__actions">
            {isError ? (
              onRetry && (
                <button
                  type="button"
                  className="ssg-op-btn ssg-op-btn--primary"
                  onClick={onRetry}
                >
                  <RefreshCw size={11} /> Retry
                </button>
              )
            ) : (
              <>
                {hasResult && onLocate && (
                  <button
                    type="button"
                    className="ssg-op-btn ssg-op-btn--primary"
                    onClick={onLocate}
                    title="Scroll to result and highlight it"
                  >
                    <MapPin size={11} /> Locate
                  </button>
                )}

                <button
                  type="button"
                  className="ssg-op-btn"
                  onClick={onUndo}
                  disabled={!canUndo}
                  title={canUndo ? 'Undo this operation' : 'Nothing to undo'}
                >
                  <RotateCcw size={11} /> Undo
                </button>

                <button
                  type="button"
                  className="ssg-op-btn"
                  onClick={onRedo}
                  disabled={!canRedo}
                  title={canRedo ? 'Redo' : 'Nothing to redo'}
                >
                  <RotateCw size={11} /> Redo
                </button>

                {operationTotal > 1 && (
                  <span className="ssg-ai-card__op-count">
                    {operationIndex + 1} / {operationTotal}
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

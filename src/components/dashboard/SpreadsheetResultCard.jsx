/**
 * SpreadsheetResultCard — Plexis AI result card rendered inside the main chat.
 *
 * Appears as part of the normal conversation history when the user runs a
 * spreadsheet operation via "Ask Plexis about this data...".
 *
 * Design:
 *   - Dark Plexis surface with subtle purple accent border
 *   - Prominent result value (e.g. "65") with human label ("Highest age")
 *   - Row + column location metadata
 *   - [ Locate ] [ Undo ] [ Redo ] action buttons that control the live spreadsheet
 *   - Collapsible technical details section
 *
 * The card fires Events.SPREADSHEET_CARD_ACTION on the EventBus so that
 * Spreadsheet.jsx can respond — no prop-drilling needed.
 */
import React, { useState, useEffect } from 'react';
import { MapPin, RotateCcw, RotateCw, ChevronDown, ChevronUp, AlertCircle, Zap } from 'lucide-react';
import { EventBus } from '../../events/EventBus.js';
import { Events } from '../../events/Events.js';
import PlexisLogo from '../brand/PlexisLogo.jsx';

// ─── Build a human-readable result summary from operation data ────────────────

function buildResultSummary(operation, result) {
  if (!operation || !result?.success) return null;
  const type = operation.type;
  const col = operation.column || operation.columns?.[0] || '';
  const n = operation.n;
  const rowIndices = result.rowIndices || [];
  const stats = result.columnStats || result.stats || {};

  if (type === 'TOP_N' || type === 'BOTTOM_N') {
    const isTop = type === 'TOP_N';
    const label = isTop ? 'Highest' : 'Lowest';
    const val = isTop ? (stats.max ?? stats.result) : (stats.min ?? stats.result);
    const firstRow = rowIndices[0];
    return {
      primary: val != null ? String(typeof val === 'number' ? val.toLocaleString() : val) : null,
      primaryLabel: col ? `${label} ${col}` : label,
      row: firstRow != null ? firstRow + 1 : null,
      column: col,
      count: rowIndices.length,
      showCount: n > 1,
    };
  }

  if (type === 'FIND_DUPLICATES' || type === 'FIND_MISSING' || type === 'FIND_OUTLIERS') {
    const label =
      type === 'FIND_DUPLICATES' ? 'Duplicate rows' :
      type === 'FIND_MISSING'    ? 'Rows with missing values' :
      'Outlier rows';
    return {
      primary: String(rowIndices.length),
      primaryLabel: label,
      count: rowIndices.length,
      showCount: false,
    };
  }

  if (type === 'AGGREGATE') {
    const val = stats.result;
    const fn = stats.function || operation.func || 'result';
    return {
      primary: val != null ? String(typeof val === 'number' ? val.toLocaleString() : val) : null,
      primaryLabel: col ? `${fn}(${col})` : fn,
    };
  }

  if (type === 'FILTER') {
    return {
      primary: String(rowIndices.length),
      primaryLabel: `Matching rows`,
      column: col,
      count: rowIndices.length,
      showCount: false,
    };
  }

  return null;
}

// ─── Operation type → technical label ────────────────────────────────────────

function opLabel(type) {
  const labels = {
    TOP_N: 'Top N', BOTTOM_N: 'Bottom N', FILTER: 'Filter', SORT: 'Sort',
    FIND_DUPLICATES: 'Find Duplicates', FIND_MISSING: 'Find Missing',
    FIND_OUTLIERS: 'Find Outliers', AGGREGATE: 'Aggregate',
    NAVIGATE: 'Navigate', HIGHLIGHT: 'Highlight', CLEAR: 'Clear',
  };
  return labels[type] || type;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function SpreadsheetResultCard({ card, isError }) {
  const [detailsOpen, setDetailsOpen] = useState(false);

  // ── Live history state from canonical broadcast ────────────────────────────
  // Spreadsheet.jsx emits SPREADSHEET_HISTORY_CHANGED after EVERY history
  // mutation (new op, undo, redo). We subscribe here so canUndo / canRedo are
  // always in sync with the actual spreadsheet state — not the frozen snapshot
  // that was baked into the message object at creation time.
  const [histState, setHistState] = useState({
    currentOpIndex:  card?.canUndo ? 0 : -1,   // initial guess from frozen value
    historyLength:   card?.canUndo ? 1 : 0,
    redoStackLength: card?.canRedo ? 1 : 0,
  });

  useEffect(() => {
    const unsub = EventBus.on(Events.SPREADSHEET_HISTORY_CHANGED, (payload) => {
      setHistState(payload);
    });
    return unsub;
  }, []);

  // Derive live button enable state from canonical history
  const liveCanUndo = histState.currentOpIndex >= 0;
  const liveCanRedo = histState.redoStackLength > 0;

  if (!card) return null;

  const { operation, result, source, operationId } = card;
  const summary = buildResultSummary(operation, result);
  const hasResult = !isError && result?.success && (result?.rowIndices?.length > 0 || summary?.primary);

  const emit = (action) => {
    EventBus.emit(Events.SPREADSHEET_CARD_ACTION, { action, operationId });
  };

  // Explain button: fires explain_evidence with the full structured operation context.
  // The backend's _explain_existing_result() uses this to explain WHAT THE RESULT MEANS
  // (not how to calculate it, not code, not a tutorial).
  const emitExplain = () => {
    const stats = result?.columnStats || result?.stats || {};
    const resultValue =
      stats.result ?? stats.max ?? stats.min ?? null;
    EventBus.emit(Events.WORKSPACE_ACTION_REQUESTED, {
      type: 'explain_evidence',
      description: summary
        ? `${summary.primaryLabel}: ${summary.primary}`
        : `${operation?.type} on ${operation?.column}`,
      evidence: {
        id: operationId,
        type: operation?.type?.toLowerCase() || 'aggregate',
        description: summary
          ? `${summary.primaryLabel} = ${summary.primary}`
          : `${operation?.type} result`,
        metadata: {
          count: result?.rowIndices?.length ?? null,
          n: operation?.n ?? null,
        },
        preview_rows: [],
        locator: null,
      },
      operation_context: {
        operation_type: operation?.type || null,
        column: operation?.column || null,
        n: operation?.n ?? null,
        result_value: resultValue,
        row_count: result?.rowIndices?.length ?? null,
        row_indices: (result?.rowIndices || []).slice(0, 10),
        stats,
        result_summary: result?.resultSummary || null,
      },
      prefilledQuestion: 'Explain this result.',
    });
  };

  if (isError) {
    return (
      <div className="src-card src-card--error">
        <div className="src-error-row">
          <AlertCircle size={14} className="src-error-icon" />
          <span className="src-error-text">{card.errorText || "I couldn't complete that operation."}</span>
        </div>
        <div className="src-actions">
          <button type="button" className="src-btn" onClick={() => emit('undo')} disabled={!liveCanUndo}>
            <RotateCcw size={11} /> Undo
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="src-card">
      {/* Result value block */}
      {summary?.primary != null && (
        <div className="src-result-block">
          <div className="src-result-value">{summary.primary}</div>
          <div className="src-result-label">{summary.primaryLabel}</div>
          {(summary.row != null || summary.column) && (
            <div className="src-result-meta">
              {summary.row != null && <span>Row {summary.row}</span>}
              {summary.row != null && summary.column && (
                <span className="src-meta-sep">·</span>
              )}
              {summary.column && <span>Column "{summary.column}"</span>}
            </div>
          )}
          {summary.showCount && summary.count > 1 && (
            <div className="src-result-count">{summary.count} rows highlighted</div>
          )}
        </div>
      )}

      {/* No primary value but has rows */}
      {!summary?.primary && hasResult && (
        <div className="src-result-block">
          <div className="src-result-value">{result.rowIndices?.length ?? 0}</div>
          <div className="src-result-label">rows affected</div>
        </div>
      )}

      {/* Action buttons */}
      <div className="src-actions">
        {hasResult && (
          <button
            type="button"
            className="src-btn src-btn--primary"
            onClick={() => emit('locate')}
            title="Scroll to result and highlight it in the spreadsheet"
          >
            <MapPin size={11} /> Locate
          </button>
        )}
        {/* Explain: fires explain_evidence with full operation context */}
        {hasResult && (
          <button
            type="button"
            className="src-btn"
            onClick={emitExplain}
            title="Explain what this result means"
          >
            <Zap size={11} /> Explain
          </button>
        )}
        <button
          type="button"
          className="src-btn"
          onClick={() => emit('undo')}
          disabled={!liveCanUndo}
          title={liveCanUndo ? 'Undo this operation' : 'Nothing to undo'}
        >
          <RotateCcw size={11} /> Undo
        </button>
        <button
          type="button"
          className="src-btn"
          onClick={() => emit('redo')}
          disabled={!liveCanRedo}
          title={liveCanRedo ? 'Redo' : 'Nothing to redo'}
        >
          <RotateCw size={11} /> Redo
        </button>

        {/* Source badge */}
        {source && (
          <span className={`src-badge src-badge--${source}`}>
            {source === 'llm' ? 'AI' : source === 'follow_up' ? 'Follow-up' : 'Auto'}
          </span>
        )}

        {/* Technical details toggle */}
        {operation?.type && (
          <button
            type="button"
            className="src-details-toggle"
            onClick={() => setDetailsOpen(v => !v)}
            title="Technical details"
          >
            Details {detailsOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
          </button>
        )}
      </div>

      {/* Collapsible technical details */}
      {detailsOpen && operation?.type && (
        <div className="src-details">
          <div className="src-detail-row">
            <span className="src-detail-key">Operation</span>
            <span className="src-detail-val">{opLabel(operation.type)}</span>
          </div>
          {operation.column && (
            <div className="src-detail-row">
              <span className="src-detail-key">Column</span>
              <span className="src-detail-val">"{operation.column}"</span>
            </div>
          )}
          {operation.n != null && (
            <div className="src-detail-row">
              <span className="src-detail-key">N</span>
              <span className="src-detail-val">{operation.n}</span>
            </div>
          )}
          {operation.order && (
            <div className="src-detail-row">
              <span className="src-detail-key">Order</span>
              <span className="src-detail-val">{operation.order}</span>
            </div>
          )}
          {result?.rowIndices?.length > 0 && (
            <div className="src-detail-row">
              <span className="src-detail-key">Rows found</span>
              <span className="src-detail-val">{result.rowIndices.length}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

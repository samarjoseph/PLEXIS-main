/**
 * AnalyticalResultCard — Premium data result card for analytical responses.
 *
 * PURPOSE:
 *   Displays the verified analytical result (value + source rows).
 *   Does NOT contain action buttons — those live in VerticalActionMenu on the message.
 *
 * Layout:
 *   [Verified ✓]  [Maximum · age]
 *        65
 *   ─────────────────────────────────────
 *   ROW   NAME              AGE   CITY
 *    45   Gage Shields       65   East Judsonland
 *    72   Watson Rippin      65   North Clovis
 *   259   Ross Goodwin       65   Prestonview
 *
 * Table design:
 *   - Source row number always visible (left-anchored)
 *   - Analytical value column bold + gradient text
 *   - Hover highlight rows
 *   - Expanded by default if ≤ 5 rows, collapsed toggle if > 5
 *   - Horizontal scroll for wide data
 */
import React, { useState } from 'react';
import { CheckCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatValue(value) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') {
    // If it's an integer stored as float, show without decimals
    if (Number.isFinite(value) && value % 1 === 0) return value.toLocaleString();
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function opLabel(op) {
  const labels = {
    max: 'Maximum', min: 'Minimum', mean: 'Average', median: 'Median',
    sum: 'Sum', std: 'Std Dev', variance: 'Variance', range: 'Range',
    count: 'Count', nunique: 'Unique count', mode: 'Mode',
    top_n: 'Top N', bottom_n: 'Bottom N',
    filter: 'Filter', sort: 'Sort',
    duplicates: 'Duplicates', missing_values: 'Missing values',
    unique_values: 'Unique values', outliers: 'Outliers',
    frequency: 'Frequency', quantile: 'Quantile',
    correlation: 'Correlation', covariance: 'Covariance',
    locate_rows: 'Located rows', group_by: 'Group by',
  };
  return labels[op?.toLowerCase?.()] || op || 'Result';
}

// Derive display columns: skip internal fields, put analytical column first
function deriveColumns(rows, highlightCol) {
  if (!rows || rows.length === 0) return [];
  const skip = new Set(['source_row_number', 'dataframe_index', 'column_value', '_row_number']);
  const allCols = Object.keys(rows[0]).filter(k => !skip.has(k));
  if (highlightCol && allCols.includes(highlightCol)) {
    return [highlightCol, ...allCols.filter(c => c !== highlightCol)].slice(0, 6);
  }
  return allCols.slice(0, 6);
}

// ── AnalyticalResultCard ──────────────────────────────────────────────────────

export default function AnalyticalResultCard({ analysisId, result }) {
  const { value, operation, column, row_count, verified, rows = [] } = result || {};

  const hasRows = rows.length > 0;
  const defaultExpanded = rows.length <= 5;
  const [rowsExpanded, setRowsExpanded] = useState(defaultExpanded);

  if (!analysisId || !result) return null;

  const operationLabel = opLabel(operation);
  const primaryLabel = column
    ? `${operationLabel} · ${column}`
    : operationLabel;

  const displayCols = deriveColumns(rows, column);

  return (
    <motion.div
      className="arc-card"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
    >
      {/* ── Header row: verified badge + operation label ── */}
      <div className="arc-header">
        {verified ? (
          <span className="arc-badge arc-badge--verified">
            <CheckCircle size={10} /> Verified
          </span>
        ) : (
          <span className="arc-badge arc-badge--unverified">
            <AlertCircle size={10} /> Unverified
          </span>
        )}
        <span className="arc-op-label">{primaryLabel}</span>
      </div>

      {/* ── Primary value ── */}
      <div className="arc-value-block">
        <span className="arc-value">{formatValue(value)}</span>
        {row_count > 0 && (
          <span className="arc-row-count">
            {row_count} {row_count === 1 ? 'matching row' : 'matching rows'}
          </span>
        )}
      </div>

      {/* ── Source rows table ── */}
      {hasRows && (
        <div className="arc-rows-section">
          {rows.length > 5 && (
            <button
              type="button"
              className="arc-rows-toggle"
              onClick={() => setRowsExpanded(v => !v)}
            >
              {rowsExpanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
              {rowsExpanded ? 'Hide rows' : `Show ${rows.length} source rows`}
            </button>
          )}

          <AnimatePresence initial={false}>
            {rowsExpanded && (
              <motion.div
                className="arc-rows-table-wrap"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
              >
                <table className="arc-rows-table">
                  <thead>
                    <tr>
                      {/* Row number column — always first */}
                      <th className="arc-th arc-th--row">Row</th>
                      {displayCols.map(col => (
                        <th
                          key={col}
                          className={`arc-th${col === column ? ' arc-th--highlight' : ''}`}
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, 10).map((row, i) => (
                      <tr key={i} className="arc-tr">
                        <td className="arc-td arc-td--row">{row.source_row_number ?? '—'}</td>
                        {displayCols.map(col => (
                          <td
                            key={col}
                            className={`arc-td${col === column ? ' arc-td--highlight' : ''}`}
                          >
                            {formatValue(row[col])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}

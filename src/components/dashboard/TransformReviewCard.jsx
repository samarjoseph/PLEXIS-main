/**
 * TransformReviewCard — shows before/after diff for user approval.
 *
 * Props:
 *   plan: same plan object as TransformPlanCard
 *   datasetId: string
 *   onApply: (planId, datasetId) => void
 *   onCancel: () => void
 *   isApplying: boolean — show loading state during apply
 */
import React from 'react';
import { CheckCircle2, X, Loader2, Sparkles } from 'lucide-react';

const MAX_ROWS = 20;

function MissingBadge() {
  return <span className="trc-missing-badge">Missing</span>;
}

function formatValue(val) {
  if (val === null || val === undefined || val === '' || String(val).toLowerCase() === 'nan' || String(val).toLowerCase() === 'none') {
    return <MissingBadge />;
  }
  return <span>{String(val)}</span>;
}

export default function TransformReviewCard({ plan, datasetId, onApply, onCancel, isApplying }) {
  if (!plan) return null;

  const {
    plan_id,
    operation_label = 'Transformation',
    operation_code,
    affected_cells_count = 0,
    before_sample = [],
    operation_payload = {},
  } = plan;
  
  const impactType = operation_payload.impact?.type || 'cell';
  const columnsChanged = operation_payload.impact?.columns_changed || 0;

  const displayRows = before_sample.slice(0, MAX_ROWS);
  const hasMore = before_sample.length > MAX_ROWS;

  return (
    <div className="trc-card">
      {/* ── Header ── */}
      <div className="trc-header">
        <div className="trc-title">
          REVIEW CHANGES — <span className="trc-op-label">{operation_label}</span>
        </div>
        <div className="trc-cells-count">
          {impactType === 'schema' 
            ? `${columnsChanged} column${columnsChanged === 1 ? '' : 's'} renamed/changed`
            : `${affected_cells_count} ${affected_cells_count === 1 ? 'cell' : 'cells'} affected`}
        </div>
      </div>

      {/* ── Diff table ── */}
      {displayRows.length > 0 ? (
        <div className="trc-table-wrap">
          <table className="trc-table">
            <thead>
              <tr>
                <th>Row</th>
                <th>Column</th>
                <th>Before</th>
                <th>After</th>
              </tr>
            </thead>
            <tbody>
              {displayRows.map((row, idx) => (
                <tr key={idx}>
                  <td className="trc-row-num">{row.source_row_number ?? row.row_index ?? '—'}</td>
                  <td className="trc-col-name">{row.column}</td>
                  <td className="trc-before">{formatValue(row.before)}</td>
                  <td className="trc-after">
                    <span className="trc-after-value">{String(row.after ?? '—')}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore && (
            <div className="trc-truncation-note">
              Showing first {MAX_ROWS} of {before_sample.length} affected rows
            </div>
          )}
        </div>
      ) : (
        <div className="trc-no-preview">No preview rows available.</div>
      )}

      {/* ── Operation code block ── */}
      {operation_code && (
        <div className="trc-code-block">
          <span className="trc-code-label">Operation:</span>
          <code className="trc-code">{operation_code}</code>
        </div>
      )}

      {/* ── Intelligence Suggestion Provenance ── */}
      {plan.intelligence_provenance && plan.intelligence_provenance.used && (
        <div className="trc-provenance" style={{
            margin: '0 12px 12px', padding: '10px 12px', 
            backgroundColor: 'var(--bg-tertiary, rgba(255,255,255,0.05))',
            borderLeft: '3px solid var(--accent-primary, #6366f1)',
            borderRadius: '4px', fontSize: '13px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, marginBottom: '4px', color: 'var(--text-primary)' }}>
            <Sparkles size={14} style={{ color: 'var(--accent-primary, #6366f1)' }} />
            Plexis Intelligence suggestion
          </div>
          <div style={{ color: 'var(--text-secondary)' }}>
            {plan.intelligence_provenance.reason || 'An alternative value was suggested and accepted.'}
          </div>
        </div>
      )}

      {/* ── Actions ── */}
      <div className="trc-actions">
        <button
          type="button"
          className="trc-btn trc-btn--primary"
          disabled={isApplying}
          onClick={() => onApply(plan_id, datasetId)}
        >
          {isApplying ? (
            <>
              <Loader2 size={13} className="trc-spinner" />
              Applying…
            </>
          ) : (
            <>
              <CheckCircle2 size={13} />
              Apply Changes
            </>
          )}
        </button>
        <button
          type="button"
          className="trc-btn"
          disabled={isApplying}
          onClick={onCancel}
        >
          <X size={13} />
          Cancel
        </button>
      </div>
    </div>
  );
}

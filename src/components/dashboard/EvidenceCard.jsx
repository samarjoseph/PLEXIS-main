/**
 * EvidenceCard — inline evidence preview rendered inside MessageBubbleV2.
 *
 * Displayed when an AI message contains a message.evidence object.
 * Shows type badge, row count, key/value preview, and action buttons.
 *
 * Actions emit EventBus events — no prop callbacks needed.
 *   [Locate]  → EVIDENCE_SELECTED + NAVIGATE_TO_EVIDENCE (opens workspace, scrolls to rows)
 *   [Explain] → WORKSPACE_ACTION_REQUESTED (fires follow-up question to /api/ask)
 *
 * For EvidenceCollection: renders multi-colored reference list.
 * Data comes entirely from evidence.preview_rows — no extra API call.
 */
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MapPin, Zap, ChevronDown, ChevronUp, AlertTriangle, Layers } from 'lucide-react';
import { EventBus } from '../../events/EventBus.js';
import { Events } from '../../events/Events.js';
import { EvidenceRegistry } from '../../evidence/EvidenceRegistry.js';

const TYPE_LABELS = {
  rows: 'Rows',
  top_n: 'Top Rows',
  bottom_n: 'Bottom Rows',
  outliers: 'Outliers',
  missing: 'Missing Values',
  duplicates: 'Duplicates',
  filtered: 'Filtered Rows',
  correlation: 'Correlation',
  aggregate: 'Aggregate',
  group: 'Group',
  sample: 'Sample',
};

const TYPE_COLORS = {
  top_n: '#f59e0b',
  bottom_n: '#ef4444',
  outliers: '#ef4444',
  missing: '#f97316',
  duplicates: '#8b5cf6',
  filtered: '#3b82f6',
  correlation: '#06b6d4',
  rows: '#f59e0b',
  default: '#6366f1',
};

export default function EvidenceCard({ evidence }) {
  const [expanded, setExpanded] = useState(false);

  if (!evidence) return null;

  // Register in EvidenceRegistry on first render
  React.useEffect(() => {
    if (evidence?.id) {
      EvidenceRegistry.register(evidence);
    }
  }, [evidence?.id]);

  if (evidence.type === 'collection') {
    return <EvidenceCollectionCard evidence={evidence} />;
  }

  const color = TYPE_COLORS[evidence.type] || TYPE_COLORS.default;
  const typeLabel = TYPE_LABELS[evidence.type] || evidence.type;
  const previewRows = evidence.preview_rows || [];
  const isStable = evidence.locator?.is_stable !== false;
  const rowCount = evidence.metadata?.outlier_count
    ?? evidence.metadata?.duplicate_count
    ?? evidence.metadata?.missing_count
    ?? evidence.metadata?.count
    ?? evidence.metadata?.n
    ?? previewRows.length
    ?? 0;

  const handleLocate = () => {
    EventBus.emit(Events.EVIDENCE_SELECTED, { evidenceId: evidence.id, evidence });
    EventBus.emit(Events.WORKSPACE_OPENED, {});
    EventBus.emit(Events.NAVIGATE_TO_EVIDENCE, { evidenceId: evidence.id });
  };

  const handleExplain = () => {
    EventBus.emit(Events.WORKSPACE_ACTION_REQUESTED, {
      type: 'explain_evidence',
      evidenceId: evidence.id,
      description: evidence.description,
      // Pass full evidence so the backend has computed stats/metadata available.
      // The LLM must explain the EXISTING result, not rediscover or recode it.
      evidence: {
        id: evidence.id,
        type: evidence.type,
        description: evidence.description,
        metadata: evidence.metadata || {},
        preview_rows: (evidence.preview_rows || []).slice(0, 5),
        locator: evidence.locator || null,
      },
      // Neutral trigger — backend's explain_evidence handler builds the real grounded prompt
      prefilledQuestion: 'Explain this result.',
    });
  };

  return (
    <motion.div
      className="ev-card"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      style={{ '--ev-color': color }}
    >
      {/* Header */}
      <div className="ev-card-header">
        <div className="ev-card-badge" style={{ background: `${color}22`, color }}>
          <span className="ev-card-badge-dot" style={{ background: color }} />
          {typeLabel}
        </div>
        {rowCount > 0 && (
          <span className="ev-card-count">{rowCount.toLocaleString()} row{rowCount !== 1 ? 's' : ''}</span>
        )}
        {!isStable && (
          <span className="ev-card-unstable">
            <AlertTriangle size={11} /> Positional
          </span>
        )}
        {previewRows.length > 0 && (
          <button
            type="button"
            className="ev-card-expand-btn"
            onClick={() => setExpanded(v => !v)}
            aria-label={expanded ? 'Collapse preview' : 'Expand preview'}
          >
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        )}
      </div>

      {/* Description */}
      <div className="ev-card-desc">{evidence.description}</div>

      {/* Preview rows */}
      <AnimatePresence>
        {expanded && previewRows.length > 0 && (
          <motion.div
            className="ev-card-preview"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {previewRows.slice(0, 3).map((row, i) => (
              <div key={i} className="ev-card-row">
                {Object.entries(row).slice(0, 4).map(([k, v]) => (
                  <div key={k} className="ev-card-cell">
                    <span className="ev-card-cell-key">{k}</span>
                    <span className="ev-card-cell-val">{v == null ? '—' : String(v)}</span>
                  </div>
                ))}
              </div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Actions */}
      <div className="ev-card-actions">
        <motion.button
          type="button"
          className="ev-card-action ev-card-action--primary"
          onClick={handleLocate}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.97 }}
        >
          <MapPin size={12} />
          Locate
        </motion.button>
        <motion.button
          type="button"
          className="ev-card-action ev-card-action--secondary"
          onClick={handleExplain}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.97 }}
        >
          <Zap size={12} />
          Explain
        </motion.button>
      </div>
    </motion.div>
  );
}

function EvidenceCollectionCard({ evidence }) {
  const palette = ['#f59e0b', '#3b82f6', '#10b981', '#8b5cf6', '#06b6d4', '#ef4444'];
  const refs = evidence.references || [];

  const handleLocateAll = () => {
    EventBus.emit(Events.EVIDENCE_SELECTED, { evidenceId: evidence.id, evidence });
    EventBus.emit(Events.WORKSPACE_OPENED, {});
  };

  return (
    <motion.div
      className="ev-card ev-card--collection"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="ev-card-header">
        <div className="ev-card-badge" style={{ background: '#6366f122', color: '#6366f1' }}>
          <Layers size={11} />
          {refs.length} Evidence Groups
        </div>
      </div>
      <div className="ev-card-desc">{evidence.summary}</div>
      <div className="ev-card-legend">
        {refs.map((ref, i) => (
          <div key={ref.id || i} className="ev-card-legend-item">
            <span className="ev-card-legend-dot" style={{ background: palette[i % palette.length] }} />
            <span className="ev-card-legend-label">{ref.description}</span>
          </div>
        ))}
      </div>
      <div className="ev-card-actions">
        <motion.button
          type="button"
          className="ev-card-action ev-card-action--primary"
          onClick={handleLocateAll}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.97 }}
        >
          <MapPin size={12} />
          Locate All
        </motion.button>
      </div>
    </motion.div>
  );
}

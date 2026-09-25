/**
 * LocateResultSelector — floating panel for multi-row Locate results.
 *
 * Shown when /api/analysis/<id>/locate returns row_count > 1.
 * Lets the user pick which specific row to navigate to.
 *
 * Fires:
 *   ANALYSIS_LOCATE_SELECTION  when user confirms a row selection
 *   NAVIGATE_TO_ROW            after the API call succeeds
 */
import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MapPin, X } from 'lucide-react';
import { EventBus } from '../../events/EventBus.js';
import { Events } from '../../events/Events.js';
import { PlexisAPI } from '../../api.js';

function formatValue(val) {
  if (val === null || val === undefined) return '—';
  if (typeof val === 'number') return val.toLocaleString();
  return String(val);
}

export default function LocateResultSelector({ analysisId, rows = [], column, value, onClose }) {
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef(null);

  // Close on Escape
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Close on click outside
  useEffect(() => {
    const handleClick = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        onClose?.();
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  const handleConfirm = async () => {
    if (selected === null || loading) return;
    setLoading(true);
    try {
      // Log the selection
      await PlexisAPI.logLocateSelection(analysisId, selected);
      // Emit selection event
      EventBus.emit(Events.ANALYSIS_LOCATE_SELECTION, {
        analysisId,
        source_row_number: selected,
      });
      // Navigate to the selected row
      EventBus.emit(Events.NAVIGATE_TO_ROW, {
        rowIndex: selected - 1,   // Convert 1-based → 0-based for workspace navigator
        highlight: true,
      });
      onClose?.();
    } catch (err) {
      console.error('[LocateResultSelector] confirm failed:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AnimatePresence>
      <motion.div
        ref={panelRef}
        className="lrs-panel"
        initial={{ opacity: 0, y: 8, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.97 }}
        transition={{ duration: 0.18 }}
      >
        {/* Header */}
        <div className="lrs-header">
          <div className="lrs-title">
            <MapPin size={13} className="lrs-title-icon" />
            Choose a result to locate
          </div>
          <button type="button" className="lrs-close" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>

        {/* Context */}
        {column && value !== undefined && (
          <div className="lrs-context">
            <span className="lrs-context-label">{column}</span>
            <span className="lrs-context-value">{formatValue(value)}</span>
            <span className="lrs-context-count">· {rows.length} rows</span>
          </div>
        )}

        {/* Row list */}
        <div className="lrs-list">
          {rows.map((row, i) => {
            const isSelected = selected === row.source_row_number;
            // Get a display label from the row (prefer name/id/label columns)
            const displayKeys = Object.keys(row).filter(k =>
              k !== 'source_row_number' && k !== 'dataframe_index' && k !== 'column_value'
            );
            const primaryKey = displayKeys.find(k =>
              /name|title|label|id/i.test(k)
            ) || displayKeys[0];
            const primaryVal = primaryKey ? row[primaryKey] : null;
            const colVal = row[column] ?? row.column_value;

            return (
              <button
                key={i}
                type="button"
                className={`lrs-row${isSelected ? ' lrs-row--selected' : ''}`}
                onClick={() => setSelected(row.source_row_number)}
              >
                <div className="lrs-row-radio">
                  <div className={`lrs-radio${isSelected ? ' lrs-radio--on' : ''}`} />
                </div>
                <div className="lrs-row-content">
                  {primaryVal != null && (
                    <span className="lrs-row-name">{formatValue(primaryVal)}</span>
                  )}
                  {colVal != null && column && (
                    <span className="lrs-row-value">
                      {column}: <strong>{formatValue(colVal)}</strong>
                    </span>
                  )}
                </div>
                <div className="lrs-row-num">Row {row.source_row_number}</div>
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div className="lrs-footer">
          <button type="button" className="lrs-btn lrs-btn--cancel" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="lrs-btn lrs-btn--confirm"
            onClick={handleConfirm}
            disabled={selected === null || loading}
          >
            {loading ? 'Navigating…' : 'Locate'}
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

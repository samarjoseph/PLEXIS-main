/**
 * VerticalActionMenu — Message-level action entry point for analytical responses.
 *
 * Sits beside the Copy button as a vertical ⋮ (three-dot) icon.
 * Opens a compact glassmorphism contextual menu with available actions.
 *
 * Actions are determined by responseActions prop:
 *   { explain: bool, locate: bool, retry: bool }
 *
 * On mount after analytical result becomes ready, pulses briefly to draw attention.
 *
 * Fires EventBus events:
 *   ANALYSIS_EXPLAIN_REQUESTED
 *   ANALYSIS_LOCATE_SINGLE / ANALYSIS_LOCATE_MULTI (after API call)
 *   ANALYSIS_RETRY_REQUESTED
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MoreVertical, Sparkles, MapPin, RotateCcw } from 'lucide-react';
import { EventBus } from '../../events/EventBus.js';
import { Events } from '../../events/Events.js';
import { PlexisAPI } from '../../api.js';

export default function VerticalActionMenu({ analysisId, responseActions, result }) {
  const [open, setOpen] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState(null);
  const [pulsing, setPulsing] = useState(false);
  const menuRef = useRef(null);
  const buttonRef = useRef(null);

  const canExplain = responseActions?.explain && analysisId;
  const canLocate  = responseActions?.locate  && analysisId && result?.row_count > 0;
  const canRetry   = responseActions?.retry   && analysisId;
  const hasActions = canExplain || canLocate || canRetry;

  // Attention animation: pulse once on mount when there are actions
  useEffect(() => {
    if (!hasActions) return;
    const timer = setTimeout(() => {
      setPulsing(true);
      setTimeout(() => setPulsing(false), 1400);
    }, 400);
    return () => clearTimeout(timer);
  }, [hasActions]);

  // Close on outside click / Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    const onOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target) &&
          buttonRef.current && !buttonRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onOutside);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onOutside);
    };
  }, [open]);

  const handleLocate = useCallback(async () => {
    if (locating) return;
    setOpen(false);
    setLocating(true);
    setLocateError(null);
    try {
      const data = await PlexisAPI.locateAnalysis(analysisId);
      if (data.navigate_direct && data.rows?.length === 1) {
        EventBus.emit(Events.ANALYSIS_LOCATE_SINGLE, {
          analysisId,
          source_row_number: data.rows[0].source_row_number,
          dataframe_index: data.rows[0].dataframe_index,
          column: data.column,
        });
      } else if (data.rows?.length > 1) {
        EventBus.emit(Events.ANALYSIS_LOCATE_MULTI, {
          analysisId,
          rows: data.rows,
          column: data.column,
          value: data.value,
        });
      } else {
        setLocateError('No matching rows found.');
      }
    } catch (err) {
      setLocateError('Locate failed. Please try again.');
      console.error('[VerticalActionMenu] locate error:', err);
    } finally {
      setLocating(false);
    }
  }, [analysisId, locating]);

  const handleExplain = useCallback(() => {
    setOpen(false);
    EventBus.emit(Events.ANALYSIS_EXPLAIN_REQUESTED, { analysisId });
  }, [analysisId]);

  const handleRetry = useCallback(() => {
    setOpen(false);
    EventBus.emit(Events.ANALYSIS_RETRY_REQUESTED, { analysisId });
  }, [analysisId]);

  if (!hasActions) return null;

  const menuItems = [
    canExplain && { id: 'explain', icon: Sparkles, label: 'Explain result', onClick: handleExplain },
    canLocate  && { id: 'locate',  icon: MapPin,   label: locating ? 'Locating…' : 'Locate in spreadsheet', onClick: handleLocate, disabled: locating },
    canRetry   && { id: 'retry',   icon: RotateCcw, label: 'Retry query',   onClick: handleRetry },
  ].filter(Boolean);

  return (
    <div className="vam-root">
      {/* ⋮ trigger button */}
      <motion.button
        ref={buttonRef}
        type="button"
        className={`vam-trigger${pulsing ? ' vam-trigger--pulse' : ''}${open ? ' vam-trigger--open' : ''}`}
        onClick={() => setOpen(v => !v)}
        aria-label="Message actions"
        aria-expanded={open}
        aria-haspopup="true"
        whileHover={{ scale: 1.08 }}
        whileTap={{ scale: 0.94 }}
        title="Actions"
      >
        <MoreVertical size={14} />
      </motion.button>

      {/* Dropdown menu */}
      <AnimatePresence>
        {open && (
          <motion.div
            ref={menuRef}
            className="vam-menu"
            role="menu"
            aria-label="Analytical result actions"
            initial={{ opacity: 0, scale: 0.92, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: -4 }}
            transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
          >
            {menuItems.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="menuitem"
                  className={`vam-item vam-item--${item.id}${item.disabled ? ' vam-item--disabled' : ''}`}
                  onClick={item.onClick}
                  disabled={item.disabled}
                >
                  <Icon size={13} className="vam-item-icon" />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Locate error toast */}
      <AnimatePresence>
        {locateError && (
          <motion.div
            className="vam-error-toast"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            onAnimationComplete={() => setTimeout(() => setLocateError(null), 3000)}
          >
            {locateError}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

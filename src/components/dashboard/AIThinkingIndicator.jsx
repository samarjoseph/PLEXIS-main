/**
 * AIThinkingIndicator — Unified animated loading indicator for Plexis AI.
 *
 * Replaces the old ThinkingV2 + spinning star avatar in ChatAreaV2.
 *
 * Design:
 *   - Animated gradient shimmer bar
 *   - Rotating thinking states: "Understanding…" → "Analyzing…" → "Preparing answer…"
 *   - Plexis brand glow (indigo/violet)
 *   - Smooth fade-in/out with framer-motion
 *
 * Used ONLY by ChatAreaV2 for the initial loading state before the first
 * response token (or before the synchronous response returns).
 */
import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import PlexisLogo from '../brand/PlexisLogo';

const STATES = [
  'Understanding…',
  'Analyzing…',
  'Preparing answer…',
];

const STATE_INTERVAL_MS = 2100;

export default function AIThinkingIndicator() {
  const [stateIdx, setStateIdx] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setStateIdx(i => (i + 1) % STATES.length);
    }, STATE_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      className="ait-root"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
    >
      {/* Plexis avatar glow */}
      <div className="ait-avatar">
        <motion.div
          className="ait-avatar-glow"
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
        />
        <PlexisLogo width={17} height={17} />
      </div>

      {/* Content area */}
      <div className="ait-body">
        {/* Rotating state text */}
        <motion.div
          key={stateIdx}
          className="ait-state-text"
          initial={{ opacity: 0, x: 6 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -6 }}
          transition={{ duration: 0.25 }}
        >
          {STATES[stateIdx]}
        </motion.div>

        {/* Shimmer bar */}
        <div className="ait-shimmer-wrap">
          <div className="ait-shimmer-bar" />
          <div className="ait-shimmer-bar ait-shimmer-bar--short" />
        </div>
      </div>
    </motion.div>
  );
}

import React from 'react';
import { motion } from 'framer-motion';

/**
 * ThinkingV2
 *
 * Displayed in two contexts:
 *   1. isLoading=true, no message yet   → "Plexis is thinking" (standard query)
 *   2. message.isStreaming + no text yet → shown inside MessageBubbleV2 until first token arrives
 *
 * Props:
 *   label  — optional override for the text (default: "Plexis is thinking")
 */
export default function ThinkingV2({ label = 'Plexis is thinking' }) {
  return (
    <div className="v2-thinking">
      <span className="v2-thinking-text">{label}</span>
      <div className="v2-thinking-dots">
        <span className="v2-thinking-dot" />
        <span className="v2-thinking-dot" />
        <span className="v2-thinking-dot" />
      </div>
    </div>
  );
}

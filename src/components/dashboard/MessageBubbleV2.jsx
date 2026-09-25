/**
 * MessageBubbleV2 — Main AI message renderer.
 *
 * Changes (UX Correction Pass):
 *   - Action buttons removed from AnalyticalResultCard (they're in VerticalActionMenu now)
 *   - VerticalActionMenu added beside Copy button in message footer
 *   - ThinkingV2 no longer rendered here — AIThinkingIndicator in ChatAreaV2 covers this
 *   - Plexis avatar: gradient mark instead of plain white square
 *   - responseActions + analysisId + result passed to VerticalActionMenu
 */
import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { motion } from 'framer-motion';
import { Globe, ExternalLink, FileSpreadsheet, Copy, Check, AlertTriangle } from 'lucide-react';
import PlexisLogo from '../brand/PlexisLogo';
import Tooltip from '../ui/Tooltip';
import EvidenceCard from './EvidenceCard.jsx';
import SpreadsheetResultCard from './SpreadsheetResultCard.jsx';
import AnalyticalResultCard from './AnalyticalResultCard.jsx';
import VerticalActionMenu from './VerticalActionMenu.jsx';

export default function MessageBubbleV2({ message, onRetry }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(typeof message.text === 'string' ? message.text : '');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  /* ── User messages ── */
  if (message.sender === 'user') {
    if (message.isFileCard) {
      return (
        <motion.div
          className="v2-msg-file-card"
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <div className="v2-msg-file-icon">
            <FileSpreadsheet size={20} />
          </div>
          <div>
            <div className="v2-msg-file-name">{message.fileName}</div>
            <div className="v2-msg-file-size">{message.fileSize}</div>
          </div>
        </motion.div>
      );
    }

    return (
      <div className="v2-msg-user-wrap">
        <div className="v2-msg-user-bubble" style={{ whiteSpace: 'pre-wrap' }}>
          {message.text}
        </div>
        <div className="v2-msg-actions v2-msg-actions-right">
          <Tooltip label="Copy message" side="top">
            <button type="button" className="v2-copy-btn" onClick={handleCopy}>
              {copied ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
            </button>
          </Tooltip>
        </div>
      </div>
    );
  }

  /* ── System Error Messages ── */
  if (message.sender === 'system_error') {
    return (
      <motion.div
        className="v2-msg-system-error"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
      >
        <div className="v2-error-compact">
          <AlertTriangle size={14} className="v2-error-icon-compact" />
          <span className="v2-error-text-compact">Please check your internet connection and try again.</span>
          <button
            type="button"
            className="v2-error-retry-compact"
            onClick={() => onRetry?.(message)}
          >
            Retry
          </button>
        </div>
      </motion.div>
    );
  }

  /* ── AI messages ── */
  const isStreaming = !!message.isStreaming;
  const hasContent = typeof message.text === 'string' && message.text.length > 0;

  // Analytical result context for VerticalActionMenu
  const analysisId = message.analysisId || null;
  const responseActions = message.responseActions || null;
  const result = message.result || null;
  const hasAnalyticalActions = !!(analysisId && responseActions);

  return (
    <motion.div
      className="v2-msg-ai"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      {/* ── Plexis gradient avatar ── */}
      <div className="v2-msg-ai-avatar v2-msg-ai-avatar--gradient">
        <PlexisLogo width={17} height={17} />
      </div>

      <div className="v2-msg-ai-body">
        {/*
          When streaming and no content yet, show nothing here —
          ChatAreaV2's AIThinkingIndicator is already shown.
          When streaming with content, render accumulated markdown.
          When done streaming / non-streaming, render full markdown.
        */}
        {hasContent && (
          <div className="v2-prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.text}
            </ReactMarkdown>
          </div>
        )}

        {/* Web search badge + citations */}
        {message.source === 'SOURCE_WEB_SEARCH' && (
          <div className="v2-msg-meta">
            <span className="v2-badge-web">
              <Globe size={12} /> Web Verified
            </span>
            {message.provider && (
              <span className="v2-msg-provider">{message.provider}</span>
            )}
            {message.sources?.length > 0 && (
              <div className="v2-msg-citations">
                {message.sources.slice(0, 4).map((url, idx) => {
                  let domain = 'Source';
                  try {
                    domain = new URL(url).hostname.replace('www.', '');
                  } catch {
                    domain = `Link ${idx + 1}`;
                  }
                  return (
                    <a
                      key={idx}
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="v2-citation"
                    >
                      {domain} <ExternalLink size={10} />
                    </a>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Evidence Card */}
        {!isStreaming && message.evidence && (
          <EvidenceCard evidence={message.evidence} />
        )}

        {/* Analytical Result Card — no action buttons inside */}
        {!isStreaming && analysisId && result && (
          <AnalyticalResultCard
            analysisId={analysisId}
            result={result}
          />
        )}

        {/* Spreadsheet Result Card */}
        {!isStreaming && message.spreadsheetCard && (
          <SpreadsheetResultCard
            card={message.spreadsheetCard}
            isError={message.spreadsheetCard?.isError}
          />
        )}

        {/* ── Message footer: Copy + VerticalActionMenu ── */}
        {!isStreaming && (
          <div className="v2-msg-actions">
            <Tooltip label="Copy AI response" side="top">
              <button type="button" className="v2-copy-btn" onClick={handleCopy}>
                {copied ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
              </button>
            </Tooltip>

            {/* Vertical ⋮ menu — only rendered when analytical actions are available */}
            {hasAnalyticalActions && (
              <VerticalActionMenu
                analysisId={analysisId}
                responseActions={responseActions}
                result={result}
              />
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

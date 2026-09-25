/**
 * ModuleGrid — RFC-002 Frontend Component
 *
 * Renders Knowledge Module cards with:
 *  - Skeleton states (HIDDEN → SKELETON → LOADED → EXPANDED → CACHED)
 *  - Dynamic ordering by richness_score (executive always first)
 *  - Per-card LLM explanation SSE streaming
 *  - Local explanation caching by (datasetId + moduleId)
 *  - DataQualityCard pinned to position 2 when quality < 90
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldCheck, BarChart3, Table2, Share2, Search,
  Eye, TrendingUp, Lightbulb, LayoutGrid, Brain,
  MessageCircle, Star, ChevronDown, ChevronUp,
  AlertTriangle, Loader2, Sparkles, Zap
} from 'lucide-react';
import { PlexisAPI } from '../../api';

// ── Icon map ─────────────────────────────────────────────────────────────────
const ICON_MAP = {
  'shield-check':    ShieldCheck,
  'chart-bar':       BarChart3,
  'table-cells':     Table2,
  'share-nodes':     Share2,
  'magnifying-glass': Search,
  'eye':             Eye,
  'chart-pie':       TrendingUp,
  'light-bulb':      Lightbulb,
  'chart-bar-square': LayoutGrid,
  'brain-circuit':   Brain,
  'chat-bubble':     MessageCircle,
  'star':            Star,
};

function ModuleIcon({ name, size = 16, color }) {
  const Icon = ICON_MAP[name] || Lightbulb;
  return <Icon size={size} color={color} />;
}

// ── Explanation cache (localStorage per datasetId+moduleId) ──────────────────
function getCacheKey(datasetId, moduleId) {
  return `plexis_exp_${datasetId}_${moduleId}`;
}
function getCachedExplanation(datasetId, moduleId) {
  try { return localStorage.getItem(getCacheKey(datasetId, moduleId)) || null; }
  catch { return null; }
}
function setCachedExplanation(datasetId, moduleId, text) {
  try { localStorage.setItem(getCacheKey(datasetId, moduleId), text); }
  catch {}
}

// ── Quality progress bar ─────────────────────────────────────────────────────
function QualityBar({ label, value, color = '#6366f1' }) {
  return (
    <div className="mg-quality-bar-row">
      <span className="mg-quality-bar-label">{label}</span>
      <div className="mg-quality-bar-track">
        <motion.div
          className="mg-quality-bar-fill"
          style={{ backgroundColor: color }}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, value)}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />
      </div>
      <span className="mg-quality-bar-value">{value?.toFixed(1)}%</span>
    </div>
  );
}

// ── Correlation strength bar ─────────────────────────────────────────────────
function CorrelationBar({ r }) {
  const abs = Math.abs(r);
  const color = abs > 0.7 ? '#10b981' : abs > 0.4 ? '#f59e0b' : '#64748b';
  return (
    <div className="mg-corr-bar-track">
      <motion.div
        className="mg-corr-bar-fill"
        style={{ backgroundColor: color }}
        initial={{ width: 0 }}
        animate={{ width: `${abs * 100}%` }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
      />
    </div>
  );
}

// ── LLM Explanation Streamer ─────────────────────────────────────────────────
function ExplanationPanel({ datasetId, moduleId, isOpen }) {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!isOpen || !datasetId || !moduleId) return;

    // Check local cache first
    const cached = getCachedExplanation(datasetId, moduleId);
    if (cached) { setText(cached); setDone(true); return; }

    // Stream explanation
    setLoading(true);
    setText('');
    setDone(false);

    const controller = new AbortController();
    abortRef.current = controller;

    (async () => {
      try {
        const resp = await PlexisAPI.explainModuleStream(datasetId, moduleId, {
          verbosity: 'standard',
          audience: 'technical',
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulated = '';

        while (true) {
          const { done: streamDone, value } = await reader.read();
          if (streamDone) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop() || '';
          for (const part of parts) {
            if (!part.trim()) continue;
            const lines = part.split('\n');
            const eventLine = lines.find(l => l.startsWith('event:'));
            const dataLine = lines.find(l => l.startsWith('data:'));
            if (!dataLine) continue;
            try {
              const payload = JSON.parse(dataLine.slice(5).trim());
              const evt = eventLine ? eventLine.slice(6).trim() : 'chunk';
              if (evt === 'chunk' && payload.text) {
                accumulated += payload.text;
                setText(accumulated);
              } else if (evt === 'done') {
                setCachedExplanation(datasetId, moduleId, accumulated);
                setDone(true);
              }
            } catch {}
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setText('*Could not load explanation. Click to retry.*');
        }
      } finally {
        setLoading(false);
      }
    })();

    return () => { controller.abort(); abortRef.current = null; };
  }, [isOpen, datasetId, moduleId]);

  if (!isOpen) return null;

  return (
    <motion.div
      className="mg-explanation"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2 }}
    >
      <div className="mg-explanation-header">
        <Sparkles size={13} color="#a855f7" />
        <span>AI Explanation</span>
        {loading && <Loader2 size={12} className="mg-spin" color="#6366f1" />}
      </div>
      <div className="mg-explanation-body">
        {text ? (
          <ReactMarkdown>{text}</ReactMarkdown>
        ) : loading ? (
          <div className="mg-explanation-skeleton">
            <div className="mg-skel-line" style={{ width: '90%' }} />
            <div className="mg-skel-line" style={{ width: '75%' }} />
            <div className="mg-skel-line" style={{ width: '82%' }} />
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}

// ── Base Card Shell ──────────────────────────────────────────────────────────
function ModuleCard({ module, datasetId, children, expandable = true }) {
  const [expanded, setExpanded] = useState(false);
  const isAnomaly = module.richness_score > 80;

  return (
    <motion.div
      className={`mg-card ${isAnomaly ? 'mg-card-highlight' : ''}`}
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      <button
        className="mg-card-header"
        onClick={() => expandable && setExpanded(e => !e)}
        aria-expanded={expanded}
      >
        <div className="mg-card-header-left">
          <div className="mg-card-icon">
            <ModuleIcon name={module.icon} size={15} color="#a855f7" />
          </div>
          <div className="mg-card-meta">
            <span className="mg-card-title">{module.display_name}</span>
            <span className="mg-card-preview">{module.preview}</span>
          </div>
        </div>
        <div className="mg-card-header-right">
          <div className="mg-richness-badge" title={`Richness: ${module.richness_score.toFixed(0)}`}>
            <div
              className="mg-richness-dot"
              style={{
                backgroundColor: module.richness_score > 70 ? '#10b981'
                  : module.richness_score > 40 ? '#f59e0b' : '#6366f1'
              }}
            />
          </div>
          {expandable && (
            expanded ? <ChevronUp size={14} color="#64748b" /> : <ChevronDown size={14} color="#64748b" />
          )}
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            className="mg-card-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: 'easeInOut' }}
            style={{ overflow: 'hidden' }}
          >
            <div className="mg-card-content">
              {children}
            </div>
            <ExplanationPanel
              datasetId={datasetId}
              moduleId={module.module_id}
              isOpen={expanded}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Skeleton Card ────────────────────────────────────────────────────────────
function SkeletonCard({ displayName }) {
  return (
    <div className="mg-card mg-card-skeleton">
      <div className="mg-card-header" style={{ cursor: 'default' }}>
        <div className="mg-card-header-left">
          <div className="mg-skel-icon" />
          <div style={{ flex: 1 }}>
            <div className="mg-skel-line" style={{ width: '40%', height: 12, marginBottom: 6 }} />
            <div className="mg-skel-line" style={{ width: '70%', height: 10 }} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Executive Summary Card ───────────────────────────────────────────────────
function ExecutiveSummaryCard({ module, datasetId }) {
  const { data } = module;
  const identity = data?.dataset_identity || {};
  const facts = data?.facts || [];
  const anomalies = facts.filter(f => f.is_anomalous);

  return (
    <ModuleCard module={module} datasetId={datasetId} expandable={false}>
      <div className="mg-executive-grid">
        <div className="mg-exec-stat">
          <span className="mg-exec-stat-label">Domain</span>
          <span className="mg-exec-stat-value">{identity.domain || '—'}</span>
        </div>
        <div className="mg-exec-stat">
          <span className="mg-exec-stat-label">Rows</span>
          <span className="mg-exec-stat-value">{(identity.rows || 0).toLocaleString()}</span>
        </div>
        <div className="mg-exec-stat">
          <span className="mg-exec-stat-label">Columns</span>
          <span className="mg-exec-stat-value">{identity.columns || 0}</span>
        </div>
        <div className="mg-exec-stat">
          <span className="mg-exec-stat-label">Readiness</span>
          <span className={`mg-exec-stat-value mg-readiness-${identity.readiness}`}>
            {identity.readiness_score?.toFixed(0)}/100
          </span>
        </div>
      </div>
      {anomalies.length > 0 && (
        <div className="mg-anomaly-banner">
          <AlertTriangle size={13} color="#f59e0b" />
          <span>{anomalies.length} anomaly/anomalies flagged</span>
        </div>
      )}
    </ModuleCard>
  );
}

// ── Data Quality Card ────────────────────────────────────────────────────────
function DataQualityCard({ module, datasetId }) {
  const d = module.data || {};
  const issues = d.issues || [];
  const critical = issues.filter(i => i.severity === 'critical' || i.severity === 'high');

  return (
    <ModuleCard module={module} datasetId={datasetId}>
      <div className="mg-quality-score-row">
        <span className="mg-quality-score-label">Overall Score</span>
        <span className={`mg-quality-score-value ${d.overall_score >= 80 ? 'good' : d.overall_score >= 60 ? 'fair' : 'poor'}`}>
          {d.overall_score?.toFixed(0)}/100
        </span>
      </div>
      <QualityBar label="Completeness" value={d.completeness_score} color="#6366f1" />
      <QualityBar label="Consistency" value={d.consistency_score} color="#a855f7" />
      <QualityBar label="Uniqueness" value={d.uniqueness_score} color="#10b981" />
      {d.duplicate_rows?.count > 0 && (
        <div className="mg-quality-issue-row">
          <AlertTriangle size={12} color="#f59e0b" />
          <span>{d.duplicate_rows.count} duplicate rows ({d.duplicate_rows.pct?.toFixed(1)}%)</span>
        </div>
      )}
      {critical.length > 0 && (
        <div className="mg-quality-issues">
          {critical.slice(0, 3).map((issue, i) => (
            <div key={i} className={`mg-quality-issue mg-severity-${issue.severity}`}>
              <strong>{issue.type?.replace(/_/g, ' ')}</strong>: {issue.description}
            </div>
          ))}
        </div>
      )}
    </ModuleCard>
  );
}

// ── Statistics Table Card ────────────────────────────────────────────────────
function StatisticsTableCard({ module, datasetId }) {
  const cols = module.data?.numeric_columns || [];
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('mean');
  const [sortDir, setSortDir] = useState('desc');

  const filtered = cols
    .filter(c => c.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0;
      return sortDir === 'desc' ? bv - av : av - bv;
    });

  const handleSort = key => {
    if (sortKey === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortKey(key); setSortDir('desc'); }
  };

  const SortHeader = ({ k, label }) => (
    <th className="mg-th" onClick={() => handleSort(k)} style={{ cursor: 'pointer' }}>
      {label}{sortKey === k ? (sortDir === 'desc' ? ' ↓' : ' ↑') : ''}
    </th>
  );

  return (
    <ModuleCard module={module} datasetId={datasetId}>
      <input
        className="mg-search"
        placeholder="Filter columns…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      <div className="mg-table-wrap">
        <table className="mg-table">
          <thead>
            <tr>
              <th className="mg-th">Column</th>
              <SortHeader k="mean" label="Mean" />
              <SortHeader k="median" label="Median" />
              <SortHeader k="std" label="Std" />
              <SortHeader k="outlier_pct" label="Outliers%" />
              <th className="mg-th">Shape</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 10).map(col => (
              <tr key={col.name} className={col.is_primary_metric ? 'mg-tr-primary' : 'mg-tr'}>
                <td className="mg-td mg-td-name">
                  {col.is_primary_metric && <Zap size={10} color="#f59e0b" />}
                  {col.name}
                </td>
                <td className="mg-td">{col.mean?.toFixed(2) ?? '—'}</td>
                <td className="mg-td">{col.median?.toFixed(2) ?? '—'}</td>
                <td className="mg-td">{col.std?.toFixed(2) ?? '—'}</td>
                <td className="mg-td">
                  {col.outlier_pct > 5 ? (
                    <span className="mg-tag-danger">{col.outlier_pct?.toFixed(1)}%</span>
                  ) : `${col.outlier_pct?.toFixed(1)}%`}
                </td>
                <td className="mg-td">
                  <span className={`mg-shape-tag mg-shape-${col.shape?.replace('-', '_')}`}>
                    {col.shape || '—'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length > 10 && (
        <p className="mg-table-overflow">Showing 10 of {filtered.length} columns</p>
      )}
    </ModuleCard>
  );
}

// ── Relationships Card ───────────────────────────────────────────────────────
function RelationshipCard({ module, datasetId }) {
  const corrs = module.data?.correlations || [];
  const groups = module.data?.grouping_dimensions || [];

  return (
    <ModuleCard module={module} datasetId={datasetId}>
      {corrs.length > 0 && (
        <div className="mg-corr-list">
          {corrs.slice(0, 6).map((c, i) => (
            <div key={i} className="mg-corr-row">
              <span className="mg-corr-cols">{c.col_a} ↔ {c.col_b}</span>
              <span className="mg-corr-r">r={c.pearson_r?.toFixed(2)}</span>
              <CorrelationBar r={c.pearson_r} />
              <span className={`mg-corr-strength mg-strength-${c.strength}`}>{c.strength?.replace('_', ' ')}</span>
            </div>
          ))}
        </div>
      )}
      {groups.length > 0 && (
        <div className="mg-group-list">
          <p className="mg-subsection-title">Grouping Dimensions</p>
          {groups.slice(0, 4).map((g, i) => (
            <div key={i} className="mg-group-row">
              <span className="mg-group-col">{g.column}</span>
              <span className="mg-group-controls">controls {g.controls_metrics?.length || 0} metric(s)</span>
            </div>
          ))}
        </div>
      )}
    </ModuleCard>
  );
}

// ── Generic List Card (Patterns, Rare, Insights) ─────────────────────────────
function ListCard({ module, datasetId, itemsKey, renderItem }) {
  const items = module.data?.[itemsKey] || [];
  return (
    <ModuleCard module={module} datasetId={datasetId}>
      <div className="mg-item-list">
        {items.slice(0, 6).map((item, i) => (
          <div key={i} className="mg-list-item">
            {renderItem(item, i)}
          </div>
        ))}
        {items.length === 0 && (
          <p className="mg-empty-list">No items available.</p>
        )}
      </div>
    </ModuleCard>
  );
}

// ── Visualization Suggestions Card ───────────────────────────────────────────
function VizCard({ module, datasetId }) {
  const suggestions = module.data?.suggestions || [];
  return (
    <ModuleCard module={module} datasetId={datasetId}>
      <div className="mg-viz-grid">
        {suggestions.slice(0, 6).map((s, i) => (
          <div key={i} className="mg-viz-item">
            <span className="mg-viz-chart-type">{s.chart_type}</span>
            <span className="mg-viz-title">{s.title}</span>
            {s.x_axis && <span className="mg-viz-axis">x: {s.x_axis}</span>}
            {s.y_axis && <span className="mg-viz-axis">y: {s.y_axis}</span>}
          </div>
        ))}
      </div>
    </ModuleCard>
  );
}

// ── Predicted Questions Card ─────────────────────────────────────────────────
function QuestionsCard({ module, datasetId, onQuestionClick }) {
  const questions = module.data?.questions || [];
  return (
    <ModuleCard module={module} datasetId={datasetId}>
      <div className="mg-questions-list">
        {questions.slice(0, 6).map((q, i) => (
          <button
            key={i}
            className="mg-question-btn"
            onClick={() => onQuestionClick?.(q.question)}
          >
            <MessageCircle size={12} color="#6366f1" />
            <span>{q.question}</span>
          </button>
        ))}
      </div>
    </ModuleCard>
  );
}

// ── Column Intelligence Card ─────────────────────────────────────────────────
function ColumnIntelligenceCard({ module, datasetId }) {
  const cols = module.data?.columns || [];
  const [search, setSearch] = useState('');
  const filtered = cols.filter(c => c.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <ModuleCard module={module} datasetId={datasetId}>
      <input
        className="mg-search"
        placeholder="Filter columns…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      <div className="mg-col-list">
        {filtered.slice(0, 12).map((col, i) => (
          <div key={i} className="mg-col-row">
            <div className="mg-col-info">
              <span className="mg-col-name">{col.name}</span>
              <span className={`mg-role-tag mg-role-${col.role?.toLowerCase()}`}>{col.role}</span>
            </div>
            <div className="mg-col-stats">
              <span className="mg-col-stat">{col.null_pct?.toFixed(1)}% null</span>
              <span className="mg-col-stat">{col.unique_count?.toLocaleString()} uniq</span>
            </div>
          </div>
        ))}
      </div>
    </ModuleCard>
  );
}

// ── Distribution Card ────────────────────────────────────────────────────────
function DistributionCard({ module, datasetId }) {
  const dists = module.data?.distributions || [];
  return (
    <ModuleCard module={module} datasetId={datasetId}>
      <div className="mg-dist-list">
        {dists.slice(0, 6).map((d, i) => (
          <div key={i} className="mg-dist-row">
            <span className="mg-dist-col">{d.column}</span>
            <span className={`mg-dist-type mg-dist-${d.distribution_type?.replace('_', '-')}`}>
              {d.distribution_type?.replace('_', ' ')}
            </span>
            <span className="mg-dist-skew">skew {d.skewness?.toFixed(2)}</span>
            <span className="mg-dist-spread">{d.spread}</span>
          </div>
        ))}
      </div>
    </ModuleCard>
  );
}

// ── Main ModuleGrid ──────────────────────────────────────────────────────────
export default function ModuleGrid({
  datasetId,
  skeletonModules = [],    // [{module_id, display_name, icon}] — from module_ready SSE
  loadedModules = [],      // full module list from done event
  onQuestionClick,
}) {
  // Determine what to show: prefer loaded, fall back to skeletons
  const hasLoaded = loadedModules.length > 0;

  // Order: executive first, then sort by richness descending
  const orderedModules = hasLoaded
    ? [
        ...loadedModules.filter(m => m.module_id === 'executive'),
        // Quality pinned to #2 if score < 90
        ...loadedModules.filter(m => m.module_id === 'quality' && (m.data?.overall_score ?? 100) < 90),
        ...loadedModules
          .filter(m => m.module_id !== 'executive'
            && !(m.module_id === 'quality' && (m.data?.overall_score ?? 100) < 90)
            && m.module_id !== 'questions'
            && m.richness_score >= 20)
          .sort((a, b) => b.richness_score - a.richness_score),
        ...loadedModules.filter(m => m.module_id === 'questions'),
      ]
    : [];

  if (!hasLoaded && skeletonModules.length === 0) return null;

  return (
    <div className="mg-grid">
      <AnimatePresence mode="popLayout">
        {hasLoaded
          ? orderedModules.map(module => (
              <ModuleCardRouter
                key={module.module_id}
                module={module}
                datasetId={datasetId}
                onQuestionClick={onQuestionClick}
              />
            ))
          : skeletonModules.map(m => (
              <SkeletonCard key={m.module_id} displayName={m.display_name} />
            ))
        }
      </AnimatePresence>
    </div>
  );
}

// ── Card Router ──────────────────────────────────────────────────────────────
function ModuleCardRouter({ module, datasetId, onQuestionClick }) {
  switch (module.module_id) {
    case 'executive':
      return <ExecutiveSummaryCard module={module} datasetId={datasetId} />;
    case 'quality':
      return <DataQualityCard module={module} datasetId={datasetId} />;
    case 'statistics':
      return <StatisticsTableCard module={module} datasetId={datasetId} />;
    case 'columns':
      return <ColumnIntelligenceCard module={module} datasetId={datasetId} />;
    case 'relationships':
      return <RelationshipCard module={module} datasetId={datasetId} />;
    case 'distribution':
      return <DistributionCard module={module} datasetId={datasetId} />;
    case 'patterns':
      return (
        <ListCard module={module} datasetId={datasetId} itemsKey="patterns"
          renderItem={(item) => (
            <>
              <div className="mg-list-item-header">
                <span className={`mg-pattern-type mg-pattern-${item.type}`}>{item.type?.replace('_', ' ')}</span>
                <span className="mg-list-col">{item.column}</span>
                {item.severity === 'high' && <AlertTriangle size={12} color="#f59e0b" />}
              </div>
              <p className="mg-list-desc">{item.description}</p>
            </>
          )}
        />
      );
    case 'rare':
      return (
        <ListCard module={module} datasetId={datasetId} itemsKey="observations"
          renderItem={(item) => (
            <>
              <div className="mg-list-item-header">
                <span className="mg-rare-type">{item.type?.replace('_', ' ')}</span>
                <span className="mg-list-col">{item.column}</span>
              </div>
              <p className="mg-list-desc">{item.description}</p>
            </>
          )}
        />
      );
    case 'insights':
      return (
        <ListCard module={module} datasetId={datasetId} itemsKey="insights"
          renderItem={(item) => (
            <>
              <div className="mg-list-item-header">
                <span className={`mg-insight-sev mg-severity-${item.severity}`}>{item.severity}</span>
                <strong className="mg-insight-title">{item.title}</strong>
              </div>
              <p className="mg-list-desc">{item.description}</p>
            </>
          )}
        />
      );
    case 'viz':
      return <VizCard module={module} datasetId={datasetId} />;
    case 'questions':
      return <QuestionsCard module={module} datasetId={datasetId} onQuestionClick={onQuestionClick} />;
    case 'semantic':
      return (
        <ModuleCard module={module} datasetId={datasetId}>
          <div className="mg-semantic-grid">
            {module.data?.column_roles && Object.entries(module.data.column_roles).map(([role, cols]) =>
              cols.length > 0 && (
                <div key={role} className="mg-semantic-role">
                  <span className="mg-semantic-role-label">{role.replace('_', ' ')}</span>
                  <div className="mg-semantic-tags">
                    {cols.slice(0, 5).map(c => (
                      <span key={c} className="mg-tag">{c}</span>
                    ))}
                  </div>
                </div>
              )
            )}
          </div>
        </ModuleCard>
      );
    default:
      return (
        <ModuleCard module={module} datasetId={datasetId}>
          <pre className="mg-raw">{JSON.stringify(module.data, null, 2)}</pre>
        </ModuleCard>
      );
  }
}

/**
 * InvestigationView.jsx — Autonomous Dataset Investigation Display
 *
 * Renders the results of the Autonomous Investigation Engine.
 * Subscribes to SSE stream for progressive updates during investigation.
 * Shows completed investigation report when cached/done.
 *
 * Architecture:
 *  - Completely separate from the 12 Knowledge Module cards (ModuleGrid)
 *  - Consumes InvestigationReport.section_groups → SectionGroup[] → AutonomousSection[]
 *  - Each section has a closed SectionType enum (metric_group, table, chart, finding, warning, etc.)
 *  - Dynamic composition: N results → M grouped sections (not 1:1)
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { PlexisAPI } from '../../api';
import { EventBus } from '../../events/EventBus.js';
import { Events } from '../../events/Events.js';
import './InvestigationView.css';

// ── Section Type Icons ──────────────────────────────────────────────────────
const SECTION_ICONS = {
  metric_group: '📊',
  table: '📋',
  chart: '📈',
  finding: '🔍',
  warning: '⚠️',
  relationship: '🔗',
  text: '📝',
  comparison: '⚖️',
  // Evidence-driven section types
  statistics: '📊',
  distribution: '📈',
  missingness: '⚠️',
  identifier: '🔑',
  data_quality: '🛡️',
  ranking: '🏆',
  outlier_list: '📌',
};

const STATUS_LABELS = {
  starting: 'Initializing investigation…',
  building_summary: 'Analyzing dataset structure…',
  generating_candidates: 'Generating analysis candidates…',
  filtering_candidates: 'Evaluating candidate quality…',
  planning: 'AI is selecting investigations…',
  executing: 'Running analyses…',
  interpreting: 'Interpreting results…',
  synthesizing: 'Synthesizing insights…',
  building_presentation: 'Building presentation…',
};

// ── Progress Indicator ──────────────────────────────────────────────────────
function InvestigationProgress({ status, details }) {
  const label = STATUS_LABELS[status] || status;
  const steps = Object.keys(STATUS_LABELS);
  const currentIdx = steps.indexOf(status);
  const progress = currentIdx >= 0 ? ((currentIdx + 1) / steps.length) * 100 : 0;

  return (
    <div className="inv-progress">
      <div className="inv-progress__header">
        <span className="inv-progress__icon">🔬</span>
        <span className="inv-progress__label">{label}</span>
      </div>
      <div className="inv-progress__bar">
        <motion.div
          className="inv-progress__fill"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      {details && (
        <div className="inv-progress__details">
          {details.total_candidates && (
            <span>{details.total_candidates} candidates evaluated</span>
          )}
          {details.planned_investigations && (
            <span>{details.planned_investigations} investigations planned</span>
          )}
          {details.complexity_tier && (
            <span className={`inv-tier inv-tier--${details.complexity_tier}`}>
              {details.complexity_tier}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Finding Card (progressive, appears as findings arrive) ──────────────────
function FindingCard({ finding }) {
  return (
    <motion.div
      className="inv-finding-card"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <span className="inv-finding-card__type">
        {finding.analysis_type?.replace(/_/g, ' ')}
      </span>
      <span className="inv-finding-card__cols">
        {finding.columns?.join(', ')}
      </span>
    </motion.div>
  );
}

// ── Metric Group Section ────────────────────────────────────────────────────
function MetricGroupSection({ section }) {
  const data = section.data || {};
  // Extract metrics from various result data shapes
  const metrics = useMemo(() => {
    const m = [];
    const skip = ['column', 'periods', 'scatter_sample', 'top_rows', 'frequencies', 'groups', 'top_missing', 'top_values', 'gap_dates'];
    for (const [key, value] of Object.entries(data)) {
      if (skip.includes(key)) continue;
      if (typeof value === 'number') {
        m.push({ label: key.replace(/_/g, ' '), value: formatNumber(value), raw: value });
      }
    }
    return m;
  }, [data]);

  return (
    <div className="inv-section inv-section--metrics">
      <div className="inv-section__metrics-grid">
        {metrics.map((m, i) => (
          <div key={i} className="inv-metric-card">
            <div className="inv-metric-card__value">{m.value}</div>
            <div className="inv-metric-card__label">{m.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Table Section ───────────────────────────────────────────────────────────
function TableSection({ section }) {
  const data = section.data || {};
  // Find the array to render as table
  const rows = data.groups || data.frequencies || data.top_rows || data.top_missing || data.top_values || [];
  if (!rows.length) return <div className="inv-section inv-section--empty">No table data</div>;

  const columns = Object.keys(rows[0] || {});

  return (
    <div className="inv-section inv-section--table">
      <div className="inv-table-wrapper">
        <table className="inv-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col}>{col.replace(/_/g, ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 15).map((row, i) => (
              <tr key={i}>
                {columns.map((col) => (
                  <td key={col}>{typeof row[col] === 'number' ? formatNumber(row[col]) : String(row[col] ?? '')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 15 && (
          <div className="inv-table__more">Showing 15 of {rows.length} rows</div>
        )}
      </div>
    </div>
  );
}

// ── Chart Section (simple bar/histogram using CSS) ──────────────────────────
function ChartSection({ section }) {
  const data = section.data || {};

  // Distribution histogram
  if (data.counts && data.bins) {
    const maxCount = Math.max(...data.counts, 1);
    return (
      <div className="inv-section inv-section--chart">
        <div className="inv-histogram">
          {data.counts.map((count, i) => (
            <div key={i} className="inv-histogram__bar-wrapper" title={`${data.bins[i]?.toFixed(1)} – ${data.bins[i+1]?.toFixed(1)}: ${count}`}>
              <div
                className="inv-histogram__bar"
                style={{ height: `${(count / maxCount) * 100}%` }}
              />
            </div>
          ))}
        </div>
        <div className="inv-chart__meta">
          {data.skewness != null && <span>Skew: {formatNumber(data.skewness)}</span>}
          {data.kurtosis != null && <span>Kurt: {formatNumber(data.kurtosis)}</span>}
        </div>
      </div>
    );
  }

  // Temporal trend (simple sparkline)
  if (data.periods?.length > 1) {
    const values = data.periods.map(p => p.value);
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const range = max - min || 1;
    return (
      <div className="inv-section inv-section--chart">
        <div className="inv-sparkline">
          {values.map((v, i) => (
            <div key={i} className="inv-sparkline__bar-wrapper" title={`${data.periods[i]?.period}: ${formatNumber(v)}`}>
              <div
                className="inv-sparkline__bar"
                style={{ height: `${((v - min) / range) * 100}%` }}
              />
            </div>
          ))}
        </div>
        {data.direction && (
          <div className="inv-chart__meta">
            <span className={`inv-trend inv-trend--${data.direction}`}>
              {data.direction === 'increasing' ? '↑' : data.direction === 'decreasing' ? '↓' : '→'} {data.direction}
            </span>
            {data.change_pct != null && <span>{formatNumber(data.change_pct)}% change</span>}
          </div>
        )}
      </div>
    );
  }

  // Frequency / concentration — simple horizontal bars
  const bars = data.frequencies || data.top_values || [];
  if (bars.length > 0) {
    const maxVal = Math.max(...bars.map(b => b.count || b.pct || 0), 1);
    return (
      <div className="inv-section inv-section--chart">
        <div className="inv-hbar-chart">
          {bars.slice(0, 10).map((bar, i) => (
            <div key={i} className="inv-hbar">
              <span className="inv-hbar__label">{bar.value}</span>
              <div className="inv-hbar__track">
                <div
                  className="inv-hbar__fill"
                  style={{ width: `${((bar.count || bar.pct || 0) / maxVal) * 100}%` }}
                />
              </div>
              <span className="inv-hbar__value">{bar.pct != null ? `${formatNumber(bar.pct)}%` : formatNumber(bar.count)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Fallback: render data as metric group
  return <MetricGroupSection section={section} />;
}

// ── Finding / Warning / Relationship Section ────────────────────────────────
function FindingSection({ section }) {
  const data = section.data || {};
  return (
    <div className={`inv-section inv-section--${section.section_type}`}>
      {section.section_type === 'warning' && <div className="inv-warning-badge">⚠️ Attention</div>}
      {section.section_type === 'relationship' && <div className="inv-relationship-badge">🔗 Relationship</div>}
      <div className="inv-finding-details">
        {Object.entries(data).map(([k, v]) => {
          if (typeof v === 'object' && v !== null) return null;
          return (
            <div key={k} className="inv-finding-detail">
              <span className="inv-finding-detail__key">{k.replace(/_/g, ' ')}</span>
              <span className="inv-finding-detail__value">
                {typeof v === 'number' ? formatNumber(v) : String(v)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Statistics Table Section ────────────────────────────────────────────────
function StatisticsTableSection({ section }) {
  const d = section.data || {};
  const statsRows = [
    ['Valid values', d.valid_count],
    ['Missing', d.missing_count],
    ['Missing %', d.missing_pct != null ? `${d.missing_pct}%` : null],
    ['Mean', d.mean],
    ['Median', d.median],
    ['Std', d.std],
    ['Min', d.min],
    ['Q1 (25%)', d.q1],
    ['Q3 (75%)', d.q3],
    ['Max', d.max],
    ['Skewness', d.skewness],
    ['Kurtosis', d.kurtosis],
  ].filter(([, v]) => v != null);

  return (
    <div className="inv-section inv-section--statistics">
      <table className="inv-stats-table">
        <tbody>
          {statsRows.map(([label, value]) => (
            <tr key={label}>
              <td className="inv-stats-table__label">{label}</td>
              <td className="inv-stats-table__value">
                {typeof value === 'number' ? formatNumber(value) : value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Distribution Section (histogram + inline stats) ─────────────────────────
function DistributionSection({ section }) {
  const d = section.data || {};
  const counts = d.counts || [];
  const bins = d.bins || [];
  const maxCount = Math.max(...counts, 1);

  return (
    <div className="inv-section inv-section--distribution">
      {/* Inline stat chips */}
      <div className="inv-distribution__chips">
        {d.valid_count != null && <span className="inv-chip">{d.valid_count} valid</span>}
        {d.missing_count > 0 && <span className="inv-chip inv-chip--warn">{d.missing_count} missing</span>}
        {d.mean != null && <span className="inv-chip">{formatNumber(d.mean)} mean</span>}
        {d.median != null && <span className="inv-chip">{formatNumber(d.median)} median</span>}
      </div>
      {/* Histogram */}
      <div className="inv-distribution__layout">
        <div className="inv-histogram">
          {counts.map((count, i) => (
            <div key={i} className="inv-histogram__bar-wrapper" title={`${bins[i]?.toFixed(1)} – ${bins[i+1]?.toFixed(1)}: ${count}`}>
              <div
                className="inv-histogram__bar"
                style={{ height: `${(count / maxCount) * 100}%` }}
              />
            </div>
          ))}
        </div>
        {/* Side stats table */}
        <div className="inv-distribution__stats">
          <table className="inv-stats-table inv-stats-table--compact">
            <tbody>
              {d.min != null && <tr><td className="inv-stats-table__label">Min</td><td className="inv-stats-table__value">{formatNumber(d.min)}</td></tr>}
              {d.max != null && <tr><td className="inv-stats-table__label">Max</td><td className="inv-stats-table__value">{formatNumber(d.max)}</td></tr>}
              {d.std != null && <tr><td className="inv-stats-table__label">Std</td><td className="inv-stats-table__value">{formatNumber(d.std)}</td></tr>}
              {d.skewness != null && <tr><td className="inv-stats-table__label">Skew</td><td className="inv-stats-table__value">{formatNumber(d.skewness)}</td></tr>}
              {d.kurtosis != null && <tr><td className="inv-stats-table__label">Kurtosis</td><td className="inv-stats-table__value">{formatNumber(d.kurtosis)}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      {/* Modal bin callout */}
      {d.modal_bin_label && (
        <div className="inv-distribution__callout">
          ↑ Largest bin: {d.modal_bin_label} → {d.modal_bin_count} records
        </div>
      )}
    </div>
  );
}

// ── Identifier Quality Section ──────────────────────────────────────────────
function IdentifierQualitySection({ section }) {
  const d = section.data || {};
  const isClean = d.is_clean;

  return (
    <div className="inv-section inv-section--identifier">
      <div className="inv-identifier__metrics">
        <div className="inv-id-metric">
          <span className="inv-id-metric__value">{formatNumber(d.unique_count)}</span>
          <span className="inv-id-metric__label">unique</span>
        </div>
        <div className="inv-id-metric">
          <span className={`inv-id-metric__value ${d.duplicate_count > 0 ? 'inv-id-metric__value--warn' : ''}`}>
            {d.duplicate_count}
          </span>
          <span className="inv-id-metric__label">duplicates</span>
        </div>
        <div className="inv-id-metric">
          <span className={`inv-id-metric__value ${d.missing_count > 0 ? 'inv-id-metric__value--warn' : ''}`}>
            {d.missing_count}
          </span>
          <span className="inv-id-metric__label">missing</span>
        </div>
        <div className="inv-id-metric">
          <span className="inv-id-metric__value">{d.uniqueness_pct}%</span>
          <span className="inv-id-metric__label">unique</span>
        </div>
      </div>
      <div className={`inv-identifier__finding ${isClean ? 'inv-identifier__finding--clean' : 'inv-identifier__finding--warn'}`}>
        {isClean ? '✓' : '⚠'} {d.finding_text}
      </div>
    </div>
  );
}

// ── Missingness Section ─────────────────────────────────────────────────────
function MissingnessSection({ section }) {
  const d = section.data || {};
  const summary = d.column_missing_summary || [];
  const missingIndices = d.missing_row_indices || [];

  const handleLocate = () => {
    if (missingIndices.length === 1) {
      EventBus.emit(Events.NAVIGATE_TO_ROW, {
        rowIndex: missingIndices[0],
        highlight: true,
      });
    } else if (missingIndices.length > 1) {
      EventBus.emit(Events.ANALYSIS_LOCATE_MULTI, {
        analysisId: 'missingness',
        rows: missingIndices.map(i => ({ source_row_number: i + 1 })),
        column: summary[0]?.column || 'data',
        value: 'missing',
      });
    }
  };

  if (!summary.length && d.total_missing_cells === 0) {
    return (
      <div className="inv-section inv-section--missingness">
        <div className="inv-identifier__finding inv-identifier__finding--clean">
          ✓ No missing values detected.
        </div>
      </div>
    );
  }

  return (
    <div className="inv-section inv-section--missingness">
      {d.total_missing_cells > 0 && (
        <div className="inv-missingness__alert">
          ⚠ {d.total_missing_cells} missing value{d.total_missing_cells !== 1 ? 's' : ''} detected
        </div>
      )}
      {summary.length > 0 && (
        <div className="inv-table-wrapper">
          <table className="inv-table">
            <thead>
              <tr>
                <th>Column</th>
                <th>Missing</th>
                <th>Valid</th>
                <th>Missing %</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((row, i) => (
                <tr key={i}>
                  <td>{row.column}</td>
                  <td>{row.missing_count}</td>
                  <td>{row.valid_count}</td>
                  <td>{row.missing_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {missingIndices.length > 0 && (
        <div className="inv-missingness__locate">
          <span className="inv-missingness__indices">
            Row{missingIndices.length > 1 ? 's' : ''}: {missingIndices.slice(0, 10).map(i => i + 1).join(', ')}
            {missingIndices.length > 10 ? ` (+${missingIndices.length - 10} more)` : ''}
          </span>
          <button className="inv-locate-btn" onClick={handleLocate}>
            📍 Locate in spreadsheet
          </button>
        </div>
      )}
    </div>
  );
}

// ── Section Renderer (dispatches to correct section type) ───────────────────
function SectionRenderer({ section }) {
  const sectionType = section.section_type;

  const ContentComponent = {
    metric_group: MetricGroupSection,
    table: TableSection,
    chart: ChartSection,
    finding: FindingSection,
    warning: FindingSection,
    relationship: FindingSection,
    text: FindingSection,
    comparison: TableSection,
    // Evidence-driven section types
    statistics: StatisticsTableSection,
    distribution: DistributionSection,
    missingness: MissingnessSection,
    identifier: IdentifierQualitySection,
    data_quality: FindingSection,
    ranking: TableSection,
    outlier_list: FindingSection,
  }[sectionType] || FindingSection;

  return (
    <motion.div
      className={`inv-section-card ${section.flagged ? 'inv-section-card--flagged' : ''}`}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="inv-section-card__header">
        <span className="inv-section-card__icon">{SECTION_ICONS[sectionType] || '📊'}</span>
        <h4 className="inv-section-card__title">{section.title}</h4>
        {section.flagged && <span className="inv-section-card__flag" title="Some numbers may need verification">⚠</span>}
      </div>
      <ContentComponent section={section} />
      {section.interpretation && (
        <p className="inv-section-card__interpretation inv-interpretation--subordinate">{section.interpretation}</p>
      )}
    </motion.div>
  );
}

// ── Section Group ───────────────────────────────────────────────────────────
function SectionGroupView({ group }) {
  return (
    <div className="inv-group">
      <h3 className="inv-group__title">{group.group_title}</h3>
      {group.synthesis_insight?.synthesis_text && (
        <div className="inv-group__synthesis">
          <span className="inv-group__synthesis-icon">💡</span>
          <p>{group.synthesis_insight.synthesis_text}</p>
        </div>
      )}
      <div className="inv-group__sections">
        {(group.sections || []).map((section) => (
          <SectionRenderer key={section.section_id} section={section} />
        ))}
      </div>
    </div>
  );
}

// ── Number Formatter ────────────────────────────────────────────────────────
function formatNumber(n) {
  if (n == null || isNaN(n)) return '–';
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toFixed(2);
}

// ── Main Component ──────────────────────────────────────────────────────────
export default function InvestigationView({ datasetId }) {
  const [status, setStatus] = useState('idle'); // idle | connecting | investigating | done | error | cached
  const [progressStatus, setProgressStatus] = useState('');
  const [progressDetails, setProgressDetails] = useState({});
  const [findings, setFindings] = useState([]);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const eventSourceRef = useRef(null);

  // Cleanup on unmount or dataset change
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [datasetId]);

  // Connect to investigation SSE stream
  const connectToStream = useCallback(() => {
    if (!datasetId) return;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setStatus('connecting');
    setFindings([]);
    setReport(null);
    setError(null);

    const url = PlexisAPI.getInvestigationStreamUrl(datasetId);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.addEventListener('investigation', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.status === 'cached') {
          setStatus('cached');
        } else if (data.status === 'not_started') {
          setStatus('idle');
        } else {
          setStatus('investigating');
          setProgressStatus(data.status || '');
          setProgressDetails(data);
        }
      } catch (err) {
        console.warn('[InvestigationView] Parse error:', err);
      }
    });

    es.addEventListener('finding_ready', (e) => {
      try {
        const finding = JSON.parse(e.data);
        setFindings(prev => [...prev, finding]);
      } catch (err) {
        console.warn('[InvestigationView] Finding parse error:', err);
      }
    });

    es.addEventListener('investigation_done', (e) => {
      try {
        const data = JSON.parse(e.data);
        setReport(data);
        setStatus('done');
      } catch (err) {
        console.warn('[InvestigationView] Done parse error:', err);
      }
      es.close();
      eventSourceRef.current = null;
    });

    es.onerror = () => {
      // SSE closed — check if report available
      es.close();
      eventSourceRef.current = null;
      if (status !== 'done' && status !== 'cached') {
        // Try to fetch completed report
        PlexisAPI.getInvestigation(datasetId).then(data => {
          if (data?.section_groups) {
            setReport(data);
            setStatus('done');
          } else if (data?.status === 'in_progress') {
            // Retry connection after a short delay
            setTimeout(() => connectToStream(), 3000);
          } else {
            setStatus('idle');
          }
        }).catch(() => setStatus('idle'));
      }
    };
  }, [datasetId]);

  // Auto-connect when datasetId changes
  useEffect(() => {
    if (!datasetId) return;
    // First try to get cached report
    PlexisAPI.getInvestigation(datasetId).then(data => {
      if (data?.section_groups) {
        setReport(data);
        setStatus('done');
      } else if (data?.status === 'in_progress') {
        connectToStream();
      } else {
        // Wait a moment, then connect (investigation may have just started from upload)
        setTimeout(() => connectToStream(), 1000);
      }
    }).catch(() => {
      setTimeout(() => connectToStream(), 1000);
    });
  }, [datasetId, connectToStream]);

  // ── Render ──────────────────────────────────────────────────────────────

  if (!datasetId) return null;

  // Loading / connecting
  if (status === 'connecting') {
    return (
      <div className="inv-container inv-container--loading">
        <div className="inv-loader" />
        <span>Connecting to investigation…</span>
      </div>
    );
  }

  // Investigation in progress
  if (status === 'investigating') {
    return (
      <div className="inv-container inv-container--progress">
        <InvestigationProgress status={progressStatus} details={progressDetails} />
        {findings.length > 0 && (
          <div className="inv-findings-stream">
            <h4 className="inv-findings-stream__title">Findings arriving…</h4>
            <AnimatePresence>
              {findings.map((f, i) => (
                <FindingCard key={`${f.candidate_id}-${i}`} finding={f} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    );
  }

  // Completed report
  if ((status === 'done' || status === 'cached') && report) {
    const groups = report.section_groups || [];
    return (
      <div className="inv-container inv-container--report">
        <div className="inv-report-header">
          <div className="inv-report-header__title">
            <span className="inv-report-header__icon">🔬</span>
            <h2>Dataset Investigation</h2>
          </div>
          <div className="inv-report-header__meta">
            <span className="inv-report-meta">
              {report.successful_investigations}/{report.total_investigations} analyses
            </span>
            <span className={`inv-tier inv-tier--${report.complexity_tier}`}>
              {report.complexity_tier}
            </span>
            {report.status === 'partial' && (
              <span className="inv-report-partial">Partial results</span>
            )}
          </div>
        </div>

        <div className="inv-groups">
          <AnimatePresence>
            {groups.map((group) => (
              <motion.div
                key={group.group_id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
              >
                <SectionGroupView group={group} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>

        {report.synthesis_text && (
          <div className="inv-synthesis inv-synthesis--subordinate">
            <div className="inv-synthesis__icon">💡</div>
            <p className="inv-synthesis__text">{report.synthesis_text}</p>
          </div>
        )}

        {report.status === 'failed' && (
          <div className="inv-error">
            <span>⚠️</span>
            <p>{report.synthesis_text || 'Investigation failed.'}</p>
          </div>
        )}
      </div>
    );
  }

  // Idle — waiting for investigation
  if (status === 'idle') {
    return (
      <div className="inv-container inv-container--idle">
        <div className="inv-idle">
          <span className="inv-idle__icon">🔬</span>
          <p>Investigation will begin automatically when data is ready.</p>
        </div>
      </div>
    );
  }

  return null;
}

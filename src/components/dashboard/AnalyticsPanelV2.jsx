import React, { useRef, useState, useMemo, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Chart as ReactChart } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  RadialLinearScale,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { MatrixController, MatrixElement } from 'chartjs-chart-matrix';
import { TreemapController, TreemapElement } from 'chartjs-chart-treemap';
import {
  BarChart3,
  LineChart,
  PieChart,
  CircleDot,
  AreaChart,
  Radar,
  ScatterChart,
  Grid3X3,
  LayoutGrid,
  BarChart2,
  Download,
  Maximize2,
  Minimize2,
  Image,
  PanelRightClose,
  Database,
  FileSpreadsheet,
  Lightbulb,
  FileJson,
  Hash,
  HardDrive,
  Columns,
} from 'lucide-react';
import { exportChartAsPNG, exportChartDataAsCSV } from '../../utils/chartExport';
import UITooltip from '../ui/Tooltip';

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement, BarElement,
  ArcElement, RadialLinearScale, MatrixController, MatrixElement,
  Tooltip, Legend, Filler, TreemapController, TreemapElement
);

const CHART_TYPES = [
  { id: 'bar', label: 'Bar', icon: BarChart3 },
  { id: 'line', label: 'Line', icon: LineChart },
  { id: 'area', label: 'Area', icon: AreaChart },
  { id: 'pie', label: 'Pie', icon: PieChart },
  { id: 'doughnut', label: 'Doughnut', icon: CircleDot },
  { id: 'radar', label: 'Radar', icon: Radar },
  { id: 'scatter', label: 'Scatter', icon: ScatterChart },
  { id: 'histogram', label: 'Histogram', icon: BarChart2 },
  { id: 'heatmap', label: 'Heatmap', icon: Grid3X3 },
  { id: 'treemap', label: 'Treemap', icon: LayoutGrid },
];

function resolveEngineType(type) {
  if (type === 'area') return 'line';
  if (type === 'histogram') return 'bar';
  return type;
}

function buildChartConfig(chartType, rawData) {
  const { labels = [], datasets = [] } = rawData || {};
  const baseDataset = datasets[0] || { data: [], label: 'Series' };
  const values = baseDataset.data || [];
  const palette = ['#6366f1', '#a855f7', '#ec4899', '#10b981', '#f59e0b', '#06b6d4'];

  if (chartType === 'scatter') {
    return {
      labels,
      datasets: [{
        label: baseDataset.label,
        data: labels.map((_, i) => ({ x: i, y: values[i] ?? 0 })),
        backgroundColor: '#6366f1',
        borderColor: '#818cf8',
      }],
    };
  }

  if (chartType === 'heatmap') {
    const matrixData = labels.flatMap((label, x) =>
      [0, 1, 2].map((y) => ({
        x, y,
        v: Math.round((values[x] ?? 0) * (0.5 + y * 0.25)),
        label,
      }))
    );
    return {
      datasets: [{
        label: 'Heatmap',
        data: matrixData,
        backgroundColor: (ctx) => {
          const v = ctx.raw?.v ?? 0;
          const alpha = Math.min(0.9, Math.max(0.1, v / 100));
          return `rgba(99, 102, 241, ${alpha})`;
        },
        width: () => 18,
        height: () => 18,
      }],
    };
  }

  if (chartType === 'treemap') {
    return {
      datasets: [{
        label: 'Treemap',
        tree: labels.map((label, i) => ({ label, value: values[i] ?? 0 })),
        key: 'value',
        groups: ['label'],
        backgroundColor: (ctx) => palette[ctx.dataIndex % palette.length],
      }],
    };
  }

  return {
    labels,
    datasets: datasets.length
      ? datasets.map((ds, i) => ({
          ...ds,
          borderColor: ds.borderColor || palette[i % palette.length],
          backgroundColor:
            chartType === 'line' || chartType === 'area'
              ? 'rgba(99, 102, 241, 0.12)'
              : chartType === 'pie' || chartType === 'doughnut'
                ? palette
                : palette[i % palette.length],
          fill: chartType === 'area',
          tension: 0.4,
        }))
      : [{ label: 'No data', data: [] }],
  };
}

function getChartOptions(chartType) {
  const polar = ['pie', 'doughnut', 'radar', 'treemap'].includes(chartType);
  const noScale = ['heatmap', 'treemap'].includes(chartType);

  if (noScale) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: chartType === 'treemap', labels: { color: '#94a3b8' } },
        tooltip: {
          backgroundColor: '#0a0c14',
          borderColor: 'rgba(255,255,255,0.08)',
          titleColor: '#6366f1',
          bodyColor: '#f8fafc',
          borderWidth: 1,
        },
      },
    };
  }

  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: polar,
        labels: { color: '#94a3b8', font: { size: 11, family: 'Inter' } },
      },
      tooltip: {
        backgroundColor: '#0a0c14',
        borderColor: 'rgba(255,255,255,0.08)',
        borderWidth: 1,
        titleColor: '#6366f1',
        bodyColor: '#f8fafc',
        padding: 10,
        cornerRadius: 8,
      },
    },
    scales: polar
      ? {}
      : {
          y: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#64748b', font: { size: 10, family: 'Inter' } },
          },
          x: {
            grid: { display: chartType !== 'scatter' ? false : true, color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#64748b', font: { size: 10, family: 'Inter' } },
          },
        },
  };
}

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(() => window.innerWidth >= 1024);

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    const handler = (e) => setIsDesktop(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return isDesktop;
}

export default function AnalyticsPanelV2({
  chartData, chartType, onChartTypeChange,
  collapsed, onToggleCollapse,
  datasetName, datasetStats,
}) {
  const chartRef = useRef(null);
  const [fullscreen, setFullscreen] = useState(false);
  const isDesktop = useIsDesktop();

  // Resizing state
  const [panelW, setPanelW] = useState(420);
  const [isDragging, setIsDragging] = useState(false);

  const handleDragStart = useCallback((e) => {
    if (!isDesktop || fullscreen) return;
    e.preventDefault();
    setIsDragging(true);
    document.body.classList.add('is-dragging');

    const handleMouseMove = (eMove) => {
      let newW = window.innerWidth - eMove.clientX;
      if (newW < 320) newW = 320;
      if (newW > 700) newW = 700;
      setPanelW(newW);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.classList.remove('is-dragging');
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [isDesktop, fullscreen]);

  const engineType = resolveEngineType(chartType);
  const computedData = useMemo(
    () => buildChartConfig(chartType, chartData),
    [chartType, chartData]
  );
  const options = useMemo(() => getChartOptions(chartType), [chartType]);
  const hasData = chartData?.labels?.length > 0;
  const hasDataset = !!datasetName;

  const handleExportJSON = () => {
    if (!chartData) return;
    const blob = new Blob([JSON.stringify(chartData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'plexis-data.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (collapsed) return null;

  return (
    <motion.aside
      className={`v2-analytics ${fullscreen ? 'v2-analytics-fullscreen' : ''}`}
      initial={{ opacity: 0, x: '100%' }}
      animate={{ opacity: 1, x: 0, width: fullscreen ? '100vw' : (isDesktop ? panelW : undefined) }}
      exit={{ opacity: 0, x: '100%' }}
      transition={isDragging ? { duration: 0 } : { duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
    >
      {/* Drag Handle */}
      {isDesktop && !fullscreen && (
        <div
          className={`v2-resize-handle v2-resize-handle-left ${isDragging ? 'active' : ''}`}
          onMouseDown={handleDragStart}
        />
      )}
      <div className="v2-analytics-header">
        <h3>Analytics</h3>
        <div className="v2-analytics-header-actions" style={{ gap: '14px' }}>
          <UITooltip label="Fullscreen" side="bottom">
            <button
              type="button"
              className="v2-icon-btn"
              onClick={() => setFullscreen(!fullscreen)}
            >
              {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
          </UITooltip>
          <UITooltip label="Close" side="bottom">
            <button
              type="button"
              className="v2-icon-btn"
              onClick={onToggleCollapse}
            >
              <PanelRightClose size={15} />
            </button>
          </UITooltip>
        </div>
      </div>

      <div className="v2-analytics-content">
        {/* Dataset Information */}
        <div className="v2-analytics-section">
          <div className="v2-analytics-section-title">
            <Database size={12} />
            Dataset Information
          </div>
          {hasDataset ? (
            <>
              <div className="v2-analytics-stat" style={{ marginBottom: '8px' }}>
                <span className="v2-analytics-stat-label">Active Dataset</span>
                <span className="v2-analytics-stat-value" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <FileSpreadsheet size={14} color="var(--dash-accent)" />
                  {datasetName}
                </span>
              </div>
              {datasetStats && (
                <div className="v2-analytics-stat-grid">
                  {datasetStats.rows != null && (
                    <div className="v2-analytics-stat">
                      <span className="v2-analytics-stat-label">Rows</span>
                      <span className="v2-analytics-stat-value">{datasetStats.rows.toLocaleString()}</span>
                    </div>
                  )}
                  {datasetStats.columns != null && (
                    <div className="v2-analytics-stat">
                      <span className="v2-analytics-stat-label">Columns</span>
                      <span className="v2-analytics-stat-value">{datasetStats.columns}</span>
                    </div>
                  )}
                  {datasetStats.memory && (
                    <div className="v2-analytics-stat">
                      <span className="v2-analytics-stat-label">Memory</span>
                      <span className="v2-analytics-stat-value">{datasetStats.memory}</span>
                    </div>
                  )}
                  {datasetStats.types && (
                    <div className="v2-analytics-stat">
                      <span className="v2-analytics-stat-label">Types</span>
                      <div className="v2-analytics-tags">
                        {datasetStats.types.map((t, i) => (
                          <span key={i} className="v2-analytics-tag">{t}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="v2-analytics-empty-section">
              <FileSpreadsheet size={20} color="var(--dash-dim)" style={{ marginBottom: '6px' }} />
              <p>No dataset loaded</p>
            </div>
          )}
        </div>

        {/* Charts */}
        <div className="v2-analytics-section">
          <div className="v2-analytics-section-title">
            <BarChart3 size={12} />
            Active Charts
          </div>
          <div className="v2-chart-types">
            {CHART_TYPES.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                className={`v2-chart-type-btn ${chartType === id ? 'active' : ''}`}
                onClick={() => onChartTypeChange(id)}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>

          <div className="v2-chart-container">
            {hasData ? (
              <ReactChart
                ref={chartRef}
                type={engineType}
                data={computedData}
                options={options}
              />
            ) : (
              <div className="v2-chart-empty">
                <BarChart3 size={28} strokeWidth={1.5} color="var(--dash-dim)" />
                <p style={{ fontWeight: 500, marginBottom: '4px' }}>No chart available</p>
                <p style={{ fontSize: '0.75rem', color: 'var(--dash-dim)', maxWidth: '220px', lineHeight: '1.5' }}>
                  This dataset does not contain trend or sequence-based data suitable for visualization.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Quick Insights */}
        <div className="v2-analytics-section">
          <div className="v2-analytics-section-title">
            <Lightbulb size={12} />
            Quick Insights
          </div>
          {hasData ? (
            <div className="v2-analytics-insight">
              Displaying <strong>{chartData.labels?.length || 0}</strong> data points
              across <strong>{chartData.datasets?.length || 0}</strong> series
              using <strong>{chartType}</strong> visualization.
            </div>
          ) : (
            <div className="v2-analytics-empty-section">
              <Lightbulb size={18} color="var(--dash-dim)" style={{ marginBottom: '4px' }} />
              <p>Insights appear after data analysis</p>
            </div>
          )}
        </div>

        {/* Export */}
        <div className="v2-analytics-section">
          <div className="v2-analytics-section-title">
            <Download size={12} />
            Export
          </div>
          <div className="v2-export-actions">
            <button
              type="button"
              className="v2-export-btn"
              disabled={!hasData}
              onClick={() => exportChartAsPNG(chartRef, 'plexis-chart.png')}
            >
              <Image size={14} /> PNG
            </button>
            <button
              type="button"
              className="v2-export-btn"
              disabled={!hasData}
              onClick={() => exportChartDataAsCSV(chartData, 'plexis-data.csv')}
            >
              <Download size={14} /> CSV
            </button>
            <button
              type="button"
              className="v2-export-btn"
              disabled={!hasData}
              onClick={handleExportJSON}
            >
              <FileJson size={14} /> JSON
            </button>
          </div>
        </div>
      </div>
    </motion.aside>
  );
}

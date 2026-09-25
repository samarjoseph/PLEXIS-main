export function exportChartAsPNG(chartRef, filename = 'plexis-chart.png') {
  const canvas = chartRef?.current?.canvas || chartRef?.canvas;
  if (!canvas) return false;

  const link = document.createElement('a');
  link.download = filename;
  link.href = canvas.toDataURL('image/png', 1.0);
  link.click();
  return true;
}

export function exportChartDataAsCSV(chartData, filename = 'plexis-data.csv') {
  const { labels = [], datasets = [] } = chartData || {};
  if (!labels.length || !datasets.length) return false;

  const header = ['Label', ...datasets.map((d, i) => d.label || `Series ${i + 1}`)];
  const rows = labels.map((label, idx) => {
    const values = datasets.map((d) => {
      const val = d.data?.[idx];
      return val === undefined || val === null ? '' : val;
    });
    return [label, ...values];
  });

  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
  return true;
}

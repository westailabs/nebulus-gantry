export interface ChartData {
  type: 'bar' | 'line' | 'pie';
  title: string;
  xKey?: string;
  yKey?: string;
  data: Record<string, unknown>[];
  description?: string;
}

function parseChartPayload(jsonStr: string): ChartData | null {
  const parsed = JSON.parse(jsonStr);

  if (parsed.chart && parsed.chart.type && parsed.chart.data) {
    return {
      type: parsed.chart.type,
      title: parsed.chart.title || 'Chart',
      xKey: parsed.chart.xKey || 'name',
      yKey: parsed.chart.yKey || 'value',
      data: parsed.chart.data,
      description: parsed.chart.description,
    };
  }

  return null;
}

// Utility function to detect chart data in text
export function extractChartFromText(text: string): ChartData | null {
  try {
    // Look for JSON chart blocks in the format: {"chart": {...}}
    const chartRegex = /\{"chart":\s*\{[^}]+\}\}/g;
    const match = chartRegex.exec(text);

    if (!match) {
      return null;
    }

    return parseChartPayload(match[0]);
  } catch (error) {
    console.warn('Failed to parse chart data from text:', error);
  }

  return null;
}

// Alternative function to detect multiple charts in text
export function extractChartsFromText(text: string): ChartData[] {
  const charts: ChartData[] = [];

  try {
    // Look for all JSON chart blocks
    const chartRegex = /\{"chart":\s*\{[^}]+\}\}/g;
    let match;

    while ((match = chartRegex.exec(text)) !== null) {
      try {
        const chart = parseChartPayload(match[0]);
        if (chart) {
          charts.push(chart);
        }
      } catch (error) {
        console.warn('Failed to parse individual chart:', error);
      }
    }
  } catch (error) {
    console.warn('Failed to extract charts from text:', error);
  }

  return charts;
}

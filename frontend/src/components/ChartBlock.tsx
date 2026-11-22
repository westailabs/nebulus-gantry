import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from 'recharts';
import type { ChartData } from './chartUtils';

// Color palette for charts
const COLORS = [
  '#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6',
  '#06B6D4', '#F97316', '#84CC16', '#EC4899', '#6B7280',
];

interface ChartBlockProps {
  chartData: ChartData;
  className?: string;
}

export function ChartBlock({ chartData, className = '' }: ChartBlockProps) {
  const { type, title, xKey, yKey, data, description } = chartData;

  if (!data || data.length === 0) {
    return (
      <div className={`p-4 bg-gray-800/50 border border-gray-700 rounded-lg ${className}`}>
        <h4 className="text-sm font-medium text-gray-300 mb-2">{title}</h4>
        <p className="text-xs text-gray-500">No data available</p>
      </div>
    );
  }

  const renderChart = () => {
    switch (type) {
      case 'bar':
        return (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey={xKey}
                tick={{ fontSize: 12, fill: '#9CA3AF' }}
                stroke="#6B7280"
              />
              <YAxis
                tick={{ fontSize: 12, fill: '#9CA3AF' }}
                stroke="#6B7280"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1F2937',
                  border: '1px solid #374151',
                  borderRadius: '8px',
                  color: '#F9FAFB',
                }}
              />
              <Legend wrapperStyle={{ color: '#D1D5DB' }} />
              <Bar
                dataKey={yKey}
                fill={COLORS[0]}
                name={yKey?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Value'}
              />
            </BarChart>
          </ResponsiveContainer>
        );

      case 'line':
        return (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey={xKey}
                tick={{ fontSize: 12, fill: '#9CA3AF' }}
                stroke="#6B7280"
              />
              <YAxis
                tick={{ fontSize: 12, fill: '#9CA3AF' }}
                stroke="#6B7280"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1F2937',
                  border: '1px solid #374151',
                  borderRadius: '8px',
                  color: '#F9FAFB',
                }}
              />
              <Legend wrapperStyle={{ color: '#D1D5DB' }} />
              <Line
                type="monotone"
                dataKey={yKey}
                stroke={COLORS[0]}
                strokeWidth={2}
                dot={{ fill: COLORS[0], r: 4 }}
                name={yKey?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Value'}
              />
            </LineChart>
          </ResponsiveContainer>
        );

      case 'pie':
        return (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={data}
                dataKey={yKey}
                nameKey={xKey}
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry) => `${entry[xKey || 'name']}: ${entry[yKey || 'value']}`}
                labelStyle={{ fontSize: '12px', fill: '#D1D5DB' }}
              >
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1F2937',
                  border: '1px solid #374151',
                  borderRadius: '8px',
                  color: '#F9FAFB',
                }}
              />
              <Legend wrapperStyle={{ color: '#D1D5DB' }} />
            </PieChart>
          </ResponsiveContainer>
        );

      default:
        return (
          <div className="p-4 text-center text-gray-500">
            <p>Unsupported chart type: {type}</p>
          </div>
        );
    }
  };

  return (
    <div className={`p-4 bg-gray-800/30 border border-gray-700 rounded-lg my-4 ${className}`}>
      <div className="mb-4">
        <h4 className="text-lg font-medium text-gray-200 mb-1">{title}</h4>
        {description && (
          <p className="text-sm text-gray-400">{description}</p>
        )}
      </div>

      <div className="bg-gray-900/50 rounded-lg p-3">
        {renderChart()}
      </div>

      {/* Data summary */}
      <div className="mt-3 pt-3 border-t border-gray-700">
        <p className="text-xs text-gray-500">
          {data.length} data point{data.length !== 1 ? 's' : ''}
          {xKey && yKey && ` • ${xKey} vs ${yKey}`}
        </p>
      </div>
    </div>
  );
}

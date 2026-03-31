'use client';
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell } from 'recharts';
import type { ValueType } from 'recharts/types/component/DefaultTooltipContent';
import type { TrendRow } from '@/types/conviction';

interface Props {
  rows: TrendRow[];
  firedays?: string[];
  width?: number;
  height?: number;
}

function convColor(score: number): string {
  if (score >= 0.75) return '#34d399';
  if (score >= 0.50) return '#1e4a2f';
  if (score >= 0.30) return '#1e3a5f';
  return '#1f2937';
}

export function DeliveryTrendChart({ rows, firedays = [], width = 420, height = 100 }: Props) {
  const sorted = [...rows].sort((a, b) =>
    a.trade_date < b.trade_date ? -1 : 1
  );

  return (
    <BarChart width={width} height={height} data={sorted}
      margin={{ top: 4, right: 4, bottom: 12, left: -20 }}>
      <XAxis dataKey="trade_date"
        tickFormatter={(v: string) => v.slice(5)}
        tick={{ fontSize: 7, fill: '#4b5563' }} />
      <YAxis domain={[0, 1]} tick={{ fontSize: 7, fill: '#4b5563' }} width={24} />
      <Tooltip
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 9 }}
        formatter={(v: ValueType | undefined) => [typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : String(v ?? ''), 'Delivery']}
      />
      <Bar dataKey="conviction_score" isAnimationActive={false}>
        {sorted.map((row) => (
          <Cell
            key={row.trade_date}
            fill={firedays.includes(row.trade_date) ? '#f87171' : convColor(row.conviction_score)}
          />
        ))}
      </Bar>
    </BarChart>
  );
}

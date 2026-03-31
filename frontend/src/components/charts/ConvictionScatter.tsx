'use client';
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';
import type { ValueType, NameType } from 'recharts/types/component/DefaultTooltipContent';
import type { RankedSymbol } from '@/types/conviction';

interface Props {
  symbols: RankedSymbol[];
  width?: number;
  height?: number;
}

export function ConvictionScatter({ symbols, width = 400, height = 200 }: Props) {
  const data = symbols
    .filter((s) => s.cusum_c !== undefined)
    .map((s) => ({ x: s.cusum_c ?? 0, y: s.avg_conviction, name: s.symbol }));

  return (
    <ScatterChart width={width} height={height}
      margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
      <XAxis dataKey="x" type="number" name="CUSUM C"
        tick={{ fontSize: 8, fill: '#4b5563' }}
        label={{ value: 'CUSUM C →', position: 'insideBottom', offset: -4, fontSize: 8, fill: '#4b5563' }} />
      <YAxis dataKey="y" type="number" name="Conv"
        tick={{ fontSize: 8, fill: '#4b5563' }}
        domain={[0, 1]} />
      <Tooltip
        cursor={{ strokeDasharray: '3 3', stroke: '#1f2937' }}
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 9 }}
        formatter={(v: ValueType | undefined, name: NameType | undefined) => [typeof v === 'number' ? v.toFixed(3) : String(v ?? ''), String(name ?? '')]}
      />
      <ReferenceLine y={0.6} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1} />
      <Scatter data={data} fill="#60a5fa" opacity={0.7} />
    </ScatterChart>
  );
}

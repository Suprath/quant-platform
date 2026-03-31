'use client';
import { LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';
import type { ValueType } from 'recharts/types/component/DefaultTooltipContent';

interface HawkesTick {
  ts_ms: number;
  lambda: number;
}

interface Props {
  data: HawkesTick[];
  width?: number;
  height?: number;
}

export function HawkesLineChart({ data, width = 320, height = 60 }: Props) {
  return (
    <LineChart width={width} height={height} data={data}
      margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
      <XAxis dataKey="ts_ms" hide />
      <YAxis tick={{ fontSize: 8, fill: '#4b5563' }} width={30} />
      <Tooltip
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 10 }}
        formatter={(v: ValueType | undefined) => [typeof v === 'number' ? v.toFixed(0) : String(v ?? ''), 'λ']}
        labelFormatter={() => ''}
      />
      <Line type="monotone" dataKey="lambda"
        stroke="#f59e0b" strokeWidth={1.5}
        dot={false} isAnimationActive={false} />
    </LineChart>
  );
}

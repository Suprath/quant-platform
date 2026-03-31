'use client';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';
import type { ValueType } from 'recharts/types/component/DefaultTooltipContent';

interface AlphaTick {
  ts_ms: number;
  alpha: number;
}

interface Props {
  data: AlphaTick[];
  width?: number;
  height?: number;
}

export function AlphaAreaChart({ data, width = 320, height = 80 }: Props) {
  return (
    <AreaChart width={width} height={height} data={data}
      margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
      <defs>
        <linearGradient id="alphaGreen" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
          <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
        </linearGradient>
        <linearGradient id="alphaRed" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%" stopColor="#f87171" stopOpacity={0.3} />
          <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
        </linearGradient>
      </defs>
      <XAxis dataKey="ts_ms" hide />
      <YAxis tick={{ fontSize: 8, fill: '#4b5563' }} width={30} />
      <Tooltip
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 10 }}
        formatter={(v: ValueType | undefined) => [typeof v === 'number' ? v.toFixed(5) : String(v ?? ''), 'α']}
        labelFormatter={() => ''}
      />
      <ReferenceLine y={0} stroke="#1f2937" strokeWidth={1} />
      <Area type="monotone" dataKey="alpha"
        stroke="#34d399" strokeWidth={1.5}
        fill="url(#alphaGreen)"
        dot={false} isAnimationActive={false} />
    </AreaChart>
  );
}

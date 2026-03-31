'use client';
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ReferenceLine, Customized } from 'recharts';
import type { ValueType, NameType } from 'recharts/types/component/DefaultTooltipContent';
import type { RankedSymbol } from '@/types/conviction';

interface Props {
  symbols: RankedSymbol[];
  width?: number;
  height?: number;
}

interface CustomizedProps {
  xAxisMap?: Record<number, { scale: (v: number) => number; domain: number[] }>;
  yAxisMap?: Record<number, { scale: (v: number) => number; domain: number[] }>;
}

function RegressionLine(props: CustomizedProps) {
  const { xAxisMap, yAxisMap } = props;
  if (!xAxisMap || !yAxisMap) return null;
  const xScale = xAxisMap[0]?.scale;
  const yScale = yAxisMap[0]?.scale;
  if (!xScale || !yScale) return null;

  // Retrieve data from closure — passed via regressionData prop workaround
  const pts = (props as unknown as { regressionData?: { x: number; y: number }[] }).regressionData;
  if (!pts || pts.length < 2) return null;

  const n = pts.length;
  const sumX = pts.reduce((s, p) => s + p.x, 0);
  const sumY = pts.reduce((s, p) => s + p.y, 0);
  const sumXY = pts.reduce((s, p) => s + p.x * p.y, 0);
  const sumX2 = pts.reduce((s, p) => s + p.x * p.x, 0);
  const denom = n * sumX2 - sumX * sumX;
  if (denom === 0) return null;
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;

  const xMin = Math.min(...pts.map((p) => p.x));
  const xMax = Math.max(...pts.map((p) => p.x));
  const yAtXmin = slope * xMin + intercept;
  const yAtXmax = slope * xMax + intercept;

  const x1 = xScale(xMin);
  const x2 = xScale(xMax);
  const y1 = yScale(yAtXmin);
  const y2 = yScale(yAtXmax);

  return (
    <line
      x1={x1} y1={y1} x2={x2} y2={y2}
      stroke="#f59e0b" strokeWidth={1} strokeDasharray="4 2"
    />
  );
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
      <Scatter data={data} fill="#60a5fa" opacity={0.7} isAnimationActive={false} />
      {data.length >= 2 && (
        <Customized component={(p: CustomizedProps) => (
          <RegressionLine {...p} {...{ regressionData: data } as object} />
        )} />
      )}
    </ScatterChart>
  );
}

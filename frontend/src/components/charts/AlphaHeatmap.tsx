'use client';
import { useMemo } from 'react';
import type { SymbolState } from '@/types/orderflow';

interface Props {
  symbols: SymbolState[];
  onSelect?: (symbol: string) => void;
}

function alphaToColor(alpha: number): string {
  const intensity = Math.min(Math.abs(alpha) * 200, 1);
  if (alpha > 0) {
    const g = Math.round(52 + intensity * 160);
    return `rgb(30,${g},80)`;
  } else {
    const r = Math.round(100 + intensity * 150);
    return `rgb(${r},30,30)`;
  }
}

export const AlphaHeatmap = ({ symbols, onSelect }: Props) => {
  const cells = useMemo(
    () => symbols.map((s) => ({ symbol: s.symbol, color: alphaToColor(s.alpha) })),
    [symbols]
  );

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
      {cells.map(({ symbol, color }) => (
        <div
          key={symbol}
          title={symbol}
          onClick={() => onSelect?.(symbol)}
          style={{
            width: 10, height: 10, borderRadius: 1,
            background: color, cursor: 'pointer',
          }}
        />
      ))}
    </div>
  );
};

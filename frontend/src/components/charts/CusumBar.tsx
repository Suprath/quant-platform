'use client';
import { useEffect, useRef, useState } from 'react';

interface Props {
  value: number;
  threshold?: number;
  fired?: boolean;
}

export function CusumBar({ value, threshold = 5.0, fired = false }: Props) {
  const [flash, setFlash] = useState(false);
  const prevFired = useRef(false);

  useEffect(() => {
    if (fired && !prevFired.current) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 600);
      return () => clearTimeout(t);
    }
    prevFired.current = fired;
  }, [fired]);

  const pct = Math.min((value / threshold) * 100, 100);
  const color = pct > 80 ? '#f87171' : pct > 50 ? '#f59e0b' : '#34d399';

  return (
    <div style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ color: '#4b5563', fontSize: 9, fontFamily: 'monospace' }}>CUSUM C</span>
        <span style={{ color, fontSize: 9, fontFamily: 'monospace', fontWeight: 700 }}>
          {value.toFixed(2)} / {threshold.toFixed(1)}
        </span>
      </div>
      <div style={{
        height: 8, background: '#1f2937', borderRadius: 2, overflow: 'hidden',
        border: flash ? '1px solid #f87171' : '1px solid transparent',
        transition: 'border-color 0.1s',
      }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: color,
          borderRadius: 2, transition: 'width 0.1s linear, background 0.2s',
        }} />
      </div>
    </div>
  );
}

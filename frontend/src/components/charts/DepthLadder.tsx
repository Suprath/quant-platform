'use client';
import { useRef } from 'react';
import type { DepthFrame, DepthLevel } from '@/types/orderflow';
import { VolumeAtPrice } from './VolumeAtPrice';

interface Props {
  frame: DepthFrame | null;
}

function LevelRow({ level, side }: { level: DepthLevel; side: 'bid' | 'ask' }) {
  const color = side === 'bid' ? '#34d399' : '#f87171';
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 6px',
      fontFamily: 'monospace', fontSize: 9 }}>
      <span style={{ color }}>{level.price.toFixed(2)}</span>
      <span style={{ color: '#9ca3af' }}>{level.quantity.toLocaleString()}</span>
    </div>
  );
}

function ObiSparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const W = 120, H = 24;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke="#34d399" strokeWidth={1} />
    </svg>
  );
}

export function DepthLadder({ frame }: Props) {
  const obiHistRef = useRef<number[]>([]);
  const tapeRef = useRef<string[]>([]);

  if (!frame) {
    return (
      <div style={{ color: '#4b5563', fontSize: 9, fontFamily: 'monospace', padding: 8 }}>
        Select a symbol to view order book depth
      </div>
    );
  }

  const { bids, asks, ltp, depth_levels } = frame;
  const totalBidQty = bids.reduce((s, l) => s + l.quantity, 0);
  const totalAskQty = asks.reduce((s, l) => s + l.quantity, 0);
  const obi = totalBidQty + totalAskQty > 0
    ? (totalBidQty - totalAskQty) / (totalBidQty + totalAskQty)
    : 0;

  // Update OBI history
  const hist = obiHistRef.current;
  if (hist.length === 0 || hist[hist.length - 1] !== obi) {
    obiHistRef.current = [...hist, obi].slice(-60);
  }

  // Update trade tape
  const bestBid = bids.length > 0 ? bids[0].price : 0;
  const bestAsk = asks.length > 0 ? asks[0].price : 0;
  const midprice = (bestBid + bestAsk) / 2;
  const side = ltp >= midprice ? 'BUY' : ltp < midprice ? 'SELL' : 'UNKNOWN';
  const now = new Date(frame.ts_ms);
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  const tapeLine = `${hh}:${mm}:${ss} ${side} @${ltp.toFixed(2)}`;
  const tape = tapeRef.current;
  if (tape.length === 0 || tape[tape.length - 1] !== tapeLine) {
    tapeRef.current = [...tape, tapeLine].slice(-20);
  }

  const visibleTape = tapeRef.current.slice(-8);

  return (
    <div style={{ fontFamily: 'monospace' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px',
        borderBottom: '1px solid #1f2937', marginBottom: 4 }}>
        <span style={{ color: '#4b5563', fontSize: 8 }}>DEPTH ({depth_levels} levels)</span>
        <span style={{ color: '#60a5fa', fontSize: 9, fontWeight: 700 }}>LTP {ltp.toFixed(2)}</span>
        <span style={{ color: obi >= 0 ? '#34d399' : '#f87171', fontSize: 8 }}>
          OBI {obi.toFixed(3)}
        </span>
      </div>

      {/* OBI sparkline */}
      <div style={{ padding: '2px 6px', marginBottom: 4 }}>
        <ObiSparkline values={obiHistRef.current} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
        <div>
          <div style={{ color: '#4b5563', fontSize: 7, padding: '0 6px', marginBottom: 2 }}>BIDS</div>
          {bids.map((l, i) => <LevelRow key={i} level={l} side="bid" />)}
        </div>
        <div>
          <div style={{ color: '#4b5563', fontSize: 7, padding: '0 6px', marginBottom: 2 }}>ASKS</div>
          {asks.map((l, i) => <LevelRow key={i} level={l} side="ask" />)}
        </div>
      </div>

      {/* VolumeAtPrice */}
      <VolumeAtPrice bids={bids} asks={asks} />

      {/* Trade tape */}
      <div style={{ marginTop: 6, fontFamily: 'monospace', fontSize: 9, lineHeight: '16px' }}>
        <div style={{ color: '#4b5563', fontSize: 7, marginBottom: 2 }}>TRADE TAPE</div>
        {visibleTape.map((entry, i) => {
          const entSide = entry.includes(' BUY ') ? 'BUY' : entry.includes(' SELL ') ? 'SELL' : 'UNKNOWN';
          const color = entSide === 'BUY' ? '#34d399' : entSide === 'SELL' ? '#f87171' : '#6b7280';
          return (
            <div key={i} style={{ color, fontSize: 9, lineHeight: '16px' }}>{entry}</div>
          );
        })}
      </div>
    </div>
  );
}

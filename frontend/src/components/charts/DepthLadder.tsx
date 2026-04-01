'use client';
import type { DepthFrame, DepthLevel } from '@/types/orderflow';

interface Props {
  frame: DepthFrame | null;
}

function LevelRow({ level, side }: { level: DepthLevel; side: 'bid' | 'ask' }) {
  const color = side === 'bid' ? '#34d399' : '#f87171';
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 8px',
      fontFamily: 'monospace', fontSize: 11 }}>
      <span style={{ color }}>{level.price.toFixed(2)}</span>
      <span style={{ color: '#9ca3af' }}>{level.quantity.toLocaleString()}</span>
    </div>
  );
}

export function DepthLadder({ frame }: Props) {
  if (!frame) {
    return (
      <div style={{ color: '#4b5563', fontSize: 11, fontFamily: 'monospace', padding: 8 }}>
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

  return (
    <div style={{ fontFamily: 'monospace' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 8px',
        borderBottom: '1px solid #1f2937', marginBottom: 6 }}>
        <span style={{ color: '#4b5563', fontSize: 10 }}>DEPTH ({depth_levels} levels)</span>
        <span style={{ color: '#60a5fa', fontSize: 12, fontWeight: 700 }}>LTP {ltp.toFixed(2)}</span>
        <span style={{ color: obi >= 0 ? '#34d399' : '#f87171', fontSize: 10 }}>
          OBI {obi.toFixed(3)}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
        <div>
          <div style={{ color: '#4b5563', fontSize: 9, padding: '0 8px', marginBottom: 4 }}>BIDS</div>
          {bids.map((l, i) => <LevelRow key={i} level={l} side="bid" />)}
        </div>
        <div>
          <div style={{ color: '#4b5563', fontSize: 9, padding: '0 8px', marginBottom: 4 }}>ASKS</div>
          {asks.map((l, i) => <LevelRow key={i} level={l} side="ask" />)}
        </div>
      </div>
    </div>
  );
}

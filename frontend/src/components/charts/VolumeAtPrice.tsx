'use client';
import type { DepthLevel } from '@/types/orderflow';

interface Props {
  bids: DepthLevel[];
  asks: DepthLevel[];
}

export function VolumeAtPrice({ bids, asks }: Props) {
  const allQtys = [...bids, ...asks].map((l) => l.quantity);
  const maxQty = allQtys.length > 0 ? Math.max(...allQtys) : 1;

  // Zip bid and ask rows by index
  const len = Math.max(bids.length, asks.length);
  const rows: { bid: DepthLevel | null; ask: DepthLevel | null }[] = [];
  for (let i = 0; i < len; i++) {
    rows.push({ bid: bids[i] ?? null, ask: asks[i] ?? null });
  }

  return (
    <div style={{ fontFamily: 'monospace', fontSize: 11, marginTop: 8 }}>
      <div style={{ color: '#4b5563', fontSize: 10, marginBottom: 4 }}>VOLUME AT PRICE</div>
      {rows.map((row, i) => {
        const bidW = row.bid ? (row.bid.quantity / maxQty) * 100 : 0;
        const askW = row.ask ? (row.ask.quantity / maxQty) * 100 : 0;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', height: 18, gap: 4, marginBottom: 2 }}>
            {/* Bid bar (left side, right-aligned) */}
            <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end', height: 10 }}>
              <div style={{
                width: `${bidW}%`, height: '100%',
                background: '#34d399', opacity: 0.7, borderRadius: '1px 0 0 1px',
              }} />
            </div>
            {/* Price label */}
            <div style={{ width: 50, textAlign: 'center', color: '#6b7280', fontSize: 10, flexShrink: 0 }}>
              {row.bid?.price.toFixed(1) ?? row.ask?.price.toFixed(1) ?? ''}
            </div>
            {/* Ask bar (right side, left-aligned) */}
            <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-start', height: 10 }}>
              <div style={{
                width: `${askW}%`, height: '100%',
                background: '#f87171', opacity: 0.7, borderRadius: '0 1px 1px 0',
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

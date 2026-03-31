'use client';
import { useState } from 'react';
import { useConvictionStore } from '@/stores/convictionStore';
import { useConvictionSSE } from '@/hooks/useConvictionSSE';
import { useConvictionTrend } from '@/hooks/useConvictionTrend';
import { ConvictionScatter } from '@/components/charts/ConvictionScatter';
import { DeliveryTrendChart } from '@/components/charts/DeliveryTrendChart';
import type { RankedSymbol } from '@/types/conviction';

const BG = '#0a0a0f';
const PANEL_BG = '#0d1117';
const BORDER = '#1f2937';
const MONO = 'ui-monospace, "Geist Mono", monospace';

type ConvTab = 'selection' | 'correlation' | 'trend';

function ConvBar({ score }: { score: number }) {
  const pct = score * 100;
  const color = pct >= 70 ? '#34d399' : pct >= 50 ? '#60a5fa' : '#4b5563';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <div style={{ width: 60, height: 6, background: '#1f2937', borderRadius: 2 }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 9, color, fontFamily: MONO }}>{score.toFixed(2)}</span>
    </div>
  );
}

function SelectionTab({ symbols, onSelect, selectedSymbol }:
  { symbols: RankedSymbol[]; onSelect: (s: string) => void; selectedSymbol: string | null }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 9, fontFamily: MONO }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BORDER}` }}>
            {['#', 'SYMBOL', 'CONV SCORE (5d)', 'KALMAN α', 'HAWKES λ', 'CUSUM C', 'q*'].map(h => (
              <th key={h} style={{ padding: '4px 8px', color: '#4b5563', textAlign: 'left', fontWeight: 700 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((s, i) => {
            const fired = (s.cusum_c ?? 0) >= 5.0;
            return (
              <tr key={s.symbol} onClick={() => onSelect(s.symbol)}
                style={{
                  borderBottom: `1px solid ${BORDER}`, cursor: 'pointer',
                  background: fired ? 'rgba(248,113,113,0.07)'
                    : selectedSymbol === s.symbol ? '#111827' : 'transparent',
                }}>
                <td style={{ padding: '3px 8px', color: '#4b5563' }}>{i + 1}</td>
                <td style={{ padding: '3px 8px', color: fired ? '#f87171' : '#60a5fa', fontWeight: 700 }}>
                  {s.symbol.replace('NSE_EQ|', '')}
                  {fired && <span style={{ marginLeft: 4, fontSize: 7 }}>⚡</span>}
                </td>
                <td style={{ padding: '3px 8px' }}><ConvBar score={s.avg_conviction} /></td>
                <td style={{ padding: '3px 8px',
                  color: (s.alpha ?? 0) >= 0 ? '#34d399' : '#f87171' }}>
                  {s.alpha !== undefined ? `${s.alpha >= 0 ? '+' : ''}${s.alpha.toFixed(4)}` : '—'}
                </td>
                <td style={{ padding: '3px 8px', color: '#f59e0b' }}>
                  {s.lambda_hawkes?.toFixed(0) ?? '—'}
                </td>
                <td style={{ padding: '3px 8px', color: '#9ca3af' }}>
                  {s.cusum_c !== undefined ? `${s.cusum_c.toFixed(1)}/5.0` : '—'}
                </td>
                <td style={{ padding: '3px 8px', color: '#f59e0b', fontWeight: 700 }}>
                  {s.q_star ?? '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function ConvictionPage() {
  useConvictionSSE();
  const { rankedSymbols, sseStatus } = useConvictionStore();
  const [activeTab, setActiveTab] = useState<ConvTab>('selection');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const trendRows = useConvictionTrend(activeTab === 'trend' ? selectedSymbol : null);

  const tabs: { id: ConvTab; label: string }[] = [
    { id: 'selection', label: 'STOCK SELECTION' },
    { id: 'correlation', label: 'INTRADAY CORRELATION' },
    { id: 'trend', label: 'TREND' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh',
      background: BG, fontFamily: MONO, color: '#9ca3af', overflow: 'hidden' }}>

      {/* Status Strip */}
      <div style={{ background: '#111827', borderBottom: `1px solid ${BORDER}`,
        padding: '4px 12px', display: 'flex', gap: 16, alignItems: 'center', flexShrink: 0 }}>
        <span style={{ color: sseStatus === 'connected' ? '#34d399' : '#f87171', fontSize: 9, fontWeight: 700 }}>
          ⬤ SSE {sseStatus.toUpperCase()}
        </span>
        <span style={{ color: '#f59e0b', fontSize: 9 }}>◈ /dashboard/conviction</span>
        <span style={{ color: '#6b7280', fontSize: 9, marginLeft: 'auto' }}>
          {rankedSymbols.length} symbols ranked
        </span>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${BORDER}`, flexShrink: 0,
        background: PANEL_BG }}>
        {tabs.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '5px 16px', fontSize: 9, fontWeight: 700, cursor: 'pointer',
              border: 'none', outline: 'none', fontFamily: MONO,
              background: activeTab === tab.id ? BG : PANEL_BG,
              color: activeTab === tab.id ? '#f59e0b' : '#6b7280',
              borderBottom: activeTab === tab.id ? '2px solid #f59e0b' : '2px solid transparent',
            }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>

        {activeTab === 'selection' && (
          <SelectionTab
            symbols={rankedSymbols}
            onSelect={(s) => { setSelectedSymbol(s); }}
            selectedSymbol={selectedSymbol}
          />
        )}

        {activeTab === 'correlation' && (
          <div>
            <div style={{ fontSize: 9, color: '#4b5563', marginBottom: 8 }}>
              SCATTER: Today&apos;s CUSUM C (x) vs EOD Conviction Score (y) — {rankedSymbols.length} symbols
            </div>
            <ConvictionScatter symbols={rankedSymbols} width={560} height={220} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginTop: 12 }}>
              {[
                { label: 'SYMBOLS TRACKED', value: String(rankedSymbols.length), color: '#60a5fa' },
                { label: 'HIGH CONV (>0.6)', value: String(rankedSymbols.filter(s => s.avg_conviction > 0.6).length), color: '#34d399' },
                { label: 'AVG CONVICTION', value: rankedSymbols.length > 0
                  ? (rankedSymbols.reduce((s, r) => s + r.avg_conviction, 0) / rankedSymbols.length).toFixed(3)
                  : '—', color: '#f59e0b' },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ background: '#111827', border: `1px solid ${BORDER}`,
                  borderRadius: 3, padding: '8px 10px' }}>
                  <div style={{ fontSize: 7, color: '#4b5563', marginBottom: 2 }}>{label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color }}>{value}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'trend' && (
          <div>
            <div style={{ fontSize: 9, color: '#4b5563', marginBottom: 8 }}>
              {selectedSymbol
                ? `20-DAY DELIVERY TREND — ${selectedSymbol.replace('NSE_EQ|', '')}`
                : 'Click a symbol in Stock Selection to view its 20-day trend'}
            </div>
            {selectedSymbol && trendRows && trendRows.length > 0 && (
              <DeliveryTrendChart rows={trendRows} width={480} height={120} />
            )}
            {selectedSymbol && trendRows && trendRows.length === 0 && (
              <div style={{ color: '#4b5563', fontSize: 9 }}>No delivery data found for {selectedSymbol}</div>
            )}
            {selectedSymbol && trendRows === null && (
              <div style={{ color: '#4b5563', fontSize: 9 }}>Loading…</div>
            )}
            {!selectedSymbol && (
              <div style={{ color: '#4b5563', fontSize: 9 }}>
                Go to Stock Selection tab, click a symbol, then return here.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

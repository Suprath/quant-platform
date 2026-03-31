'use client';
import { useState, useMemo, useRef } from 'react';
import { useOrderFlowStore } from '@/stores/orderflowStore';
import { useOrderFlowWS } from '@/hooks/useOrderFlowWS';
import { useMarketDepthWS } from '@/hooks/useMarketDepthWS';
import { AlphaAreaChart } from '@/components/charts/AlphaAreaChart';
import { HawkesLineChart } from '@/components/charts/HawkesLineChart';
import { CusumBar } from '@/components/charts/CusumBar';
import { AlphaHeatmap } from '@/components/charts/AlphaHeatmap';
import { DepthLadder } from '@/components/charts/DepthLadder';
import type { SymbolState } from '@/types/orderflow';

const BG = '#0a0a0f';
const PANEL_BG = '#0d1117';
const BORDER = '#1f2937';
const MONO = 'ui-monospace, "Geist Mono", monospace';

function useAlphaHistory(symbols: Record<string, SymbolState>, selectedSymbol: string | null) {
  const historyRef = useRef<Record<string, { ts_ms: number; alpha: number }[]>>({});
  const hawkesRef = useRef<Record<string, { ts_ms: number; lambda: number }[]>>({});

  if (selectedSymbol && symbols[selectedSymbol]) {
    const s = symbols[selectedSymbol];
    const ah = historyRef.current[selectedSymbol] ?? [];
    const last = ah[ah.length - 1];
    if (!last || last.ts_ms !== s.ts_ms) {
      historyRef.current[selectedSymbol] = [...ah, { ts_ms: s.ts_ms, alpha: s.alpha }].slice(-200);
      const hh = hawkesRef.current[selectedSymbol] ?? [];
      hawkesRef.current[selectedSymbol] = [...hh, { ts_ms: s.ts_ms, lambda: s.lambda_hawkes }].slice(-200);
    }
  }

  return {
    alphaHistory: selectedSymbol ? (historyRef.current[selectedSymbol] ?? []) : [],
    hawkesHistory: selectedSymbol ? (hawkesRef.current[selectedSymbol] ?? []) : [],
  };
}

type DrillTab = 'drilldown' | 'depth';

export default function OrderFlowPage() {
  useOrderFlowWS();
  const { symbols, watchlist, selectedSymbol, signalFeed, cusumFires,
          depthData, wsStatus, setSelectedSymbol } = useOrderFlowStore();
  const [drillTab, setDrillTab] = useState<DrillTab>('drilldown');

  useMarketDepthWS(drillTab === 'depth' ? selectedSymbol : null);

  const { alphaHistory, hawkesHistory } = useAlphaHistory(symbols, selectedSymbol);

  const sorted = useMemo(() => {
    const firedSet = new Set(cusumFires.slice(0, 20).map((f) => f.symbol));
    const fired = watchlist.filter((s) => firedSet.has(s));
    const rest = watchlist.filter((s) => !firedSet.has(s));
    return [...fired, ...rest];
  }, [watchlist, cusumFires]);

  const selected = selectedSymbol ? symbols[selectedSymbol] : null;
  const firedToday = cusumFires.filter((f) => selectedSymbol && f.symbol === selectedSymbol).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh',
      background: BG, fontFamily: MONO, color: '#9ca3af', overflow: 'hidden' }}>

      {/* Status Strip */}
      <div style={{ background: '#111827', borderBottom: `1px solid ${BORDER}`,
        padding: '4px 12px', display: 'flex', gap: 16, alignItems: 'center', flexShrink: 0 }}>
        <span style={{ color: wsStatus === 'connected' ? '#34d399' : '#f87171', fontSize: 9, fontWeight: 700 }}>
          ⬤ {wsStatus.toUpperCase()}
        </span>
        <span style={{ color: '#60a5fa', fontSize: 9 }}>{watchlist.length} SYMBOLS</span>
        <span style={{ color: '#f87171', fontSize: 9 }}>⚡ {cusumFires.length} FIRES TODAY</span>
        <span style={{ color: '#6b7280', fontSize: 9, marginLeft: 'auto' }}>
          ⚡ /dashboard/orderflow
        </span>
      </div>

      {/* Main 3-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr 220px',
        flex: 1, overflow: 'hidden', gap: 0 }}>

        {/* ── Watchlist ── */}
        <div style={{ borderRight: `1px solid ${BORDER}`, overflowY: 'auto', background: PANEL_BG }}>
          <div style={{ padding: '4px 8px', borderBottom: `1px solid ${BORDER}`,
            fontSize: 8, color: '#4b5563', fontWeight: 700, letterSpacing: '0.1em' }}>
            WATCHLIST ↑ α+λ/1e5
          </div>
          {sorted.map((sym) => {
            const s = symbols[sym];
            if (!s) return null;
            const fired = cusumFires.slice(0, 20).some((f) => f.symbol === sym);
            return (
              <div key={sym} onClick={() => setSelectedSymbol(sym)}
                style={{
                  padding: '4px 8px', cursor: 'pointer', borderBottom: `1px solid ${BORDER}`,
                  background: fired
                    ? 'rgba(248,113,113,0.10)'
                    : selectedSymbol === sym ? '#111827' : 'transparent',
                }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ fontSize: 10, fontWeight: 700,
                    color: fired ? '#f87171' : selectedSymbol === sym ? '#60a5fa' : '#9ca3af' }}>
                    {sym.replace('NSE_EQ|', '')}
                  </span>
                  <span style={{ fontSize: 9, color: s.alpha >= 0 ? '#34d399' : '#f87171' }}>
                    {s.alpha >= 0 ? '+' : ''}{s.alpha.toFixed(4)}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 8, color: '#f59e0b' }}>{s.lambda_hawkes.toFixed(0)} λ</span>
                  <span style={{ fontSize: 8, color: '#6b7280' }}>{s.cusum_c.toFixed(1)}/5.0</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Drilldown / Depth ── */}
        <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Tab bar */}
          <div style={{ display: 'flex', borderBottom: `1px solid ${BORDER}`, flexShrink: 0 }}>
            {(['drilldown', 'depth'] as DrillTab[]).map((tab) => (
              <button key={tab} onClick={() => setDrillTab(tab)}
                style={{
                  padding: '5px 14px', fontSize: 9, fontWeight: 700, cursor: 'pointer',
                  border: 'none', outline: 'none', fontFamily: MONO,
                  background: drillTab === tab ? BG : PANEL_BG,
                  color: drillTab === tab ? '#60a5fa' : '#6b7280',
                  borderBottom: drillTab === tab ? `2px solid #60a5fa` : '2px solid transparent',
                }}>
                {tab.toUpperCase()}
              </button>
            ))}
            {selectedSymbol && (
              <span style={{ marginLeft: 12, alignSelf: 'center', fontSize: 9,
                color: '#4b5563' }}>{selectedSymbol.replace('NSE_EQ|', '')}</span>
            )}
          </div>

          <div style={{ flex: 1, padding: 10, overflowY: 'auto', background: BG }}>
            {drillTab === 'drilldown' ? (
              <>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 8, color: '#4b5563', marginBottom: 3 }}>KALMAN α — last 200 ticks</div>
                  <AlphaAreaChart data={alphaHistory} width={480} height={80} />
                </div>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 8, color: '#4b5563', marginBottom: 3 }}>HAWKES λ DECAY</div>
                  <HawkesLineChart data={hawkesHistory} width={480} height={60} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <CusumBar
                    value={selected?.cusum_c ?? 0}
                    fired={selected?.cusum_fired ?? false}
                  />
                </div>
                <div>
                  <div style={{ fontSize: 8, color: '#4b5563', marginBottom: 4 }}>
                    α HEATMAP — {watchlist.length} symbols
                  </div>
                  <AlphaHeatmap
                    symbols={Object.values(symbols)}
                    onSelect={setSelectedSymbol}
                  />
                </div>
              </>
            ) : (
              <DepthLadder frame={depthData} />
            )}
          </div>
        </div>

        {/* ── Detail Panel ── */}
        <div style={{ borderLeft: `1px solid ${BORDER}`, background: PANEL_BG,
          padding: 10, overflowY: 'auto' }}>
          <div style={{ fontSize: 8, color: '#4b5563', fontWeight: 700,
            letterSpacing: '0.1em', marginBottom: 8 }}>
            {selected ? selected.symbol.replace('NSE_EQ|', '') : 'SELECT SYMBOL'}
          </div>
          {selected ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                { label: 'KALMAN α', value: selected.alpha.toFixed(5),
                  color: selected.alpha >= 0 ? '#34d399' : '#f87171' },
                { label: 'HAWKES λ', value: selected.lambda_hawkes.toFixed(0), color: '#f59e0b' },
                { label: 'CUSUM C', value: `${selected.cusum_c.toFixed(2)} / 5.0`,
                  color: selected.cusum_c > 4 ? '#f87171' : '#9ca3af' },
                { label: 'σ² VAR', value: selected.variance.toFixed(6), color: '#a78bfa' },
                { label: 'KYLE λ', value: selected.kyle_lambda.toFixed(4), color: '#60a5fa' },
                { label: 'q* SIZE', value: String(selected.q_star),
                  color: selected.q_star > 0 ? '#34d399' : '#6b7280' },
                { label: 'FIRES TODAY', value: String(firedToday),
                  color: firedToday > 0 ? '#f87171' : '#6b7280' },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ borderBottom: `1px solid ${BORDER}`, paddingBottom: 5 }}>
                  <div style={{ fontSize: 7, color: '#4b5563', marginBottom: 1 }}>{label}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color }}>{value}</div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ color: '#4b5563', fontSize: 9 }}>
              Click a symbol in the watchlist to see details
            </div>
          )}
        </div>
      </div>

      {/* Signal Ticker */}
      <div style={{ height: 22, background: '#111827', borderTop: `1px solid ${BORDER}`,
        overflow: 'hidden', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 24, animation: 'scroll 30s linear infinite',
          fontSize: 8, whiteSpace: 'nowrap', padding: '0 12px' }}>
          {signalFeed.map((e, i) => (
            <span key={i} style={{ color: e.side === 'FIRE' ? '#f87171' : e.side === 'BUY' ? '#34d399' : '#f87171' }}>
              {new Date(e.ts_ms).toTimeString().slice(0, 8)}{' '}
              {e.symbol.replace('NSE_EQ|', '')}{' '}
              {e.side === 'FIRE' ? '⚡ FIRE' : e.side}{' '}
              q*={e.q_star} α={e.alpha.toFixed(4)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

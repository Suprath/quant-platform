'use client';
import { useEffect, useRef } from 'react';
import { useOrderFlowStore } from '@/stores/orderflowStore';
import type { SymbolState, SignalEvent, CusumFire } from '@/types/orderflow';

const WS_URL = () =>
  `${typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss' : 'ws'}://${
    process.env.NEXT_PUBLIC_API_HOST || 'localhost:8080'
  }/ws/orderflow`;

export function useOrderFlowWS() {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelayRef = useRef(1000);
  const { setSymbols, addSignalEvent, addCusumFire, setWsStatus } = useOrderFlowStore();

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      setWsStatus('connecting');
      const ws = new WebSocket(WS_URL());
      wsRef.current = ws;

      ws.onopen = () => {
        retryDelayRef.current = 1000;
        setWsStatus('connected');
      };

      ws.onmessage = (evt) => {
        try {
          const states: SymbolState[] = JSON.parse(evt.data as string);
          setSymbols(states);

          for (const s of states) {
            if (s.cusum_fired) {
              const fire: CusumFire = {
                symbol: s.symbol,
                q_star: s.q_star,
                alpha: s.alpha,
                ts_ms: s.ts_ms,
              };
              addCusumFire(fire);
              const event: SignalEvent = {
                symbol: s.symbol,
                side: 'FIRE',
                q_star: s.q_star,
                alpha: s.alpha,
                ts_ms: s.ts_ms,
              };
              addSignalEvent(event);
            }
          }
        } catch {
          // malformed frame — skip
        }
      };

      ws.onerror = () => ws.close();

      ws.onclose = () => {
        if (cancelled) return;
        setWsStatus('disconnected');
        const delay = Math.min(retryDelayRef.current, 30000);
        retryDelayRef.current = delay * 2;
        retryRef.current = setTimeout(connect, delay * (0.8 + Math.random() * 0.4));
      };
    }

    connect();
    return () => {
      cancelled = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [setSymbols, addSignalEvent, addCusumFire, setWsStatus]);
}

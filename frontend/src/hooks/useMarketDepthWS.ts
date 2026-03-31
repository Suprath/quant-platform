'use client';
import { useEffect, useRef } from 'react';
import { useOrderFlowStore } from '@/stores/orderflowStore';
import type { DepthFrame } from '@/types/orderflow';

const DEPTH_WS_URL = (symbol: string) =>
  `${typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss' : 'ws'}://${
    process.env.NEXT_PUBLIC_API_HOST || 'localhost:8080'
  }/ws/depth/${encodeURIComponent(symbol)}`;

export function useMarketDepthWS(symbol: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelayRef = useRef(1000);
  const { setDepthData } = useOrderFlowStore();

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(DEPTH_WS_URL(symbol!));
      wsRef.current = ws;

      ws.onmessage = (evt) => {
        try {
          const frame: DepthFrame = JSON.parse(evt.data as string);
          setDepthData(frame);
        } catch {
          // skip
        }
      };

      ws.onerror = () => ws.close();

      ws.onclose = () => {
        if (cancelled) return;
        const delay = Math.min(retryDelayRef.current, 30000);
        retryDelayRef.current = delay * 2;
        retryRef.current = setTimeout(connect, delay + Math.random() * 200);
      };
    }

    connect();
    return () => {
      cancelled = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [symbol, setDepthData]);
}

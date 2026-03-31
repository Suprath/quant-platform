'use client';
import { useEffect, useRef } from 'react';
import { useConvictionStore } from '@/stores/convictionStore';
import type { RankedSymbol } from '@/types/conviction';

const SSE_URL = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'}/api/conviction/stream`;

export function useConvictionSSE() {
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelayRef = useRef(1000);
  const { setRankedSymbols, setSseStatus } = useConvictionStore();

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      setSseStatus('connecting');
      const es = new EventSource(SSE_URL);
      esRef.current = es;

      es.onopen = () => {
        retryDelayRef.current = 1000;
        setSseStatus('connected');
      };

      es.addEventListener('ranked_list', (evt: MessageEvent) => {
        try {
          const ranked: RankedSymbol[] = JSON.parse(evt.data as string);
          setRankedSymbols(ranked);
        } catch {
          // skip
        }
      });

      es.onerror = () => {
        if (cancelled) return;
        es.close();
        setSseStatus('disconnected');
        const delay = Math.min(retryDelayRef.current, 30000);
        retryDelayRef.current = delay * 2;
        retryRef.current = setTimeout(connect, delay * (0.8 + Math.random() * 0.4));
      };
    }

    connect();
    return () => {
      cancelled = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      esRef.current?.close();
    };
  }, [setRankedSymbols, setSseStatus]);
}

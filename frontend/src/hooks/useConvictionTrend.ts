'use client';
import { useEffect, useRef } from 'react';
import { useConvictionStore } from '@/stores/convictionStore';
import type { TrendRow } from '@/types/conviction';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export function useConvictionTrend(symbol: string | null) {
  const trendData = useConvictionStore((s) => s.trendData);
  const setTrendData = useConvictionStore((s) => s.setTrendData);
  const fetchingRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!symbol) return;
    if (trendData[symbol] !== undefined) return;  // already cached
    if (fetchingRef.current.has(symbol)) return;  // in-flight

    fetchingRef.current.add(symbol);
    fetch(`${API_URL}/api/conviction/trend/${encodeURIComponent(symbol)}`)
      .then((r) => r.json())
      .then((rows: TrendRow[]) => setTrendData(symbol, rows))
      .catch(() => setTrendData(symbol, []))
      .finally(() => fetchingRef.current.delete(symbol));
  }, [symbol, trendData, setTrendData]);

  return symbol ? (trendData[symbol] ?? null) : null;
}

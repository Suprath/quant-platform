'use client';
import { useEffect } from 'react';
import { useConvictionStore } from '@/stores/convictionStore';
import type { TrendRow } from '@/types/conviction';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export function useConvictionTrend(symbol: string | null) {
  const { trendData, setTrendData } = useConvictionStore();

  useEffect(() => {
    if (!symbol) return;
    if (trendData[symbol]) return;  // already cached in store

    fetch(`${API_URL}/api/conviction/trend/${encodeURIComponent(symbol)}`)
      .then((r) => r.json())
      .then((rows: TrendRow[]) => setTrendData(symbol, rows))
      .catch(() => {
        setTrendData(symbol, []);
      });
  }, [symbol, trendData, setTrendData]);

  return symbol ? (trendData[symbol] ?? null) : null;
}

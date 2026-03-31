import { create } from 'zustand';
import type { RankedSymbol, CorrelationStats, TrendRow, SseStatus } from '@/types/conviction';

interface ConvictionStore {
  rankedSymbols: RankedSymbol[];
  correlationStats: CorrelationStats | null;
  trendData: Record<string, TrendRow[]>;
  sseStatus: SseStatus;

  setRankedSymbols: (symbols: RankedSymbol[]) => void;
  setCorrelationStats: (stats: CorrelationStats) => void;
  setTrendData: (symbol: string, rows: TrendRow[]) => void;
  setSseStatus: (status: SseStatus) => void;
}

export const useConvictionStore = create<ConvictionStore>((set) => ({
  rankedSymbols: [],
  correlationStats: null,
  trendData: {},
  sseStatus: 'disconnected',

  setRankedSymbols: (rankedSymbols) => set({ rankedSymbols }),

  setCorrelationStats: (correlationStats) => set({ correlationStats }),

  setTrendData: (symbol, rows) =>
    set((state) => ({
      trendData: { ...state.trendData, [symbol]: rows },
    })),

  setSseStatus: (sseStatus) => set({ sseStatus }),
}));

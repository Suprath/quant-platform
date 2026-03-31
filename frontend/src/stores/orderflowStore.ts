import { create } from 'zustand';
import type { SymbolState, DepthFrame, SignalEvent, CusumFire, WsStatus } from '@/types/orderflow';

const MAX_SIGNAL_FEED = 100;
const MAX_CUSUM_FIRES = 50;

interface OrderFlowStore {
  symbols: Record<string, SymbolState>;
  watchlist: string[];
  selectedSymbol: string | null;
  signalFeed: SignalEvent[];
  cusumFires: CusumFire[];
  depthData: DepthFrame | null;
  wsStatus: WsStatus;

  setSymbols: (states: SymbolState[]) => void;
  setSelectedSymbol: (symbol: string | null) => void;
  addSignalEvent: (event: SignalEvent) => void;
  addCusumFire: (fire: CusumFire) => void;
  setDepthData: (frame: DepthFrame) => void;
  setWsStatus: (status: WsStatus) => void;
}

export const useOrderFlowStore = create<OrderFlowStore>((set) => ({
  symbols: {},
  watchlist: [],
  selectedSymbol: null,
  signalFeed: [],
  cusumFires: [],
  depthData: null,
  wsStatus: 'disconnected',

  setSymbols: (states) =>
    set(() => {
      const symbols: Record<string, SymbolState> = {};
      const watchlist: string[] = [];
      for (const s of states) {
        symbols[s.symbol] = s;
        watchlist.push(s.symbol);
      }
      return { symbols, watchlist };
    }),

  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol, depthData: null }),

  addSignalEvent: (event) =>
    set((state) => ({
      signalFeed: [event, ...state.signalFeed].slice(0, MAX_SIGNAL_FEED),
    })),

  addCusumFire: (fire) =>
    set((state) => ({
      cusumFires: [fire, ...state.cusumFires].slice(0, MAX_CUSUM_FIRES),
    })),

  setDepthData: (frame) => set({ depthData: frame }),

  setWsStatus: (wsStatus) => set({ wsStatus }),
}));

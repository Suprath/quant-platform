export interface SymbolState {
  symbol: string;
  alpha: number;
  lambda_hawkes: number;
  cusum_c: number;
  variance: number;
  q_star: number;
  kyle_lambda: number;
  ts_ms: number;
  cusum_fired: boolean;
}

export interface DepthLevel {
  price: number;
  quantity: number;
}

export interface DepthFrame {
  symbol: string;
  ltp: number;
  depth_levels: number;
  bids: DepthLevel[];
  asks: DepthLevel[];
  ts_ms: number;
}

export interface SignalEvent {
  symbol: string;
  side: 'BUY' | 'SELL' | 'FIRE';
  q_star: number;
  alpha: number;
  ts_ms: number;
}

export interface CusumFire {
  symbol: string;
  q_star: number;
  alpha: number;
  ts_ms: number;
}

export type WsStatus = 'connecting' | 'connected' | 'disconnected';

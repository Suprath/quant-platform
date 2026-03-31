export interface RankedSymbol {
  symbol: string;
  avg_conviction: number;
  latest_date: string;
  alpha?: number;
  lambda_hawkes?: number;
  cusum_c?: number;
  q_star?: number;
}

export interface CorrelationStats {
  pearson_r: number;
  fires_high_conv_count: number;
  fires_total: number;
  avg_conv_at_fire: number;
  universe_avg_conv: number;
}

export interface TrendRow {
  trade_date: string;
  symbol: string;
  conviction_score: number;
  total_volume: number;
  delivery_qty: number;
}

export type SseStatus = 'connecting' | 'connected' | 'disconnected';

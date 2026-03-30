# KIRA Frontend Dashboard Design Spec

## Goal

Add two new high-density quant dashboards (Order Flow, EOD Conviction) to the existing Next.js frontend, integrate real-time Upstox V3 market depth, and fix the critical issues in the current frontend. All changes target the `develop` branch.

## Visual Style

**Bloomberg Terminal** — `#0a0a0f` background, monospace fonts throughout, micro-panels, no whitespace waste. Color palette: green `#34d399` (bullish/positive), red `#f87171` (bearish/fire), amber `#f59e0b` (Hawkes/warning), blue `#60a5fa` (neutral data), purple `#a78bfa` (variance), gray `#6b7280` (inactive).

## Navigation

Two new nav items added to the existing left sidebar (52px wide icon strip):

| Icon | Label | Route | Status |
|------|-------|--------|--------|
| ⚡ | FLOW | `/dashboard/orderflow` | NEW — green highlight |
| ◈ | CONV | `/dashboard/conviction` | NEW — amber highlight |

Global status bar (WebSocket status, CUSUM fire count, IST clock) appears at the top of every page.

---

## 1. Order Flow Dashboard (`/dashboard/orderflow`)

### Layout — C: Watchlist + Drilldown + Detail Panel

Three-column layout. No page scroll — fits viewport.

```
┌─────────────────────────────────────────────────────────────┐
│ Global Status Strip (WS status · CUSUM fires · IST clock)  │
├──────────────┬──────────────────────────┬───────────────────┤
│  WATCHLIST   │  SIGNAL DRILLDOWN  │DEPTH│  DETAIL PANEL     │
│  (sorted by  │  Kalman α chart         │  Symbol metrics   │
│   α · λ · C) │  Hawkes λ decay chart   │  Kalman α         │
│              │  CUSUM accumulator bar  │  Hawkes λ         │
│  500-symbol  │  500-symbol heatmap     │  CUSUM C          │
│  list        │                         │  σ²               │
│              │  [DRILLDOWN] [DEPTH]    │  Kyle λ           │
│              │  ── tab selector ──     │  q* size          │
│              │                         │  EOD conv %       │
│              │  DEPTH TAB:             │  Fires today      │
│              │  Bid/ask ladder         │                   │
│              │  OBI sparkline          │                   │
│              │  Volume-at-price        │                   │
│              │  Trade tape             │                   │
├──────────────┴──────────────────────────┴───────────────────┤
│  Signal ticker (autoscrolling: SYMBOL · BUY/SELL · q*=N)   │
└─────────────────────────────────────────────────────────────┘
```

### Watchlist Panel (left, ~200px)

- Sorted by composite score: `|alpha| + lambda/1e5 + cusum_c/5` descending.
- CUSUM-fired symbols pinned to top with red background (`rgba(248,113,113,0.12)`).
- Each row: symbol name, α value (green/red colored), Hawkes λ, CUSUM C/5.0 progress bar.
- Clicking a row sets `selectedSymbol` in the Zustand store, updates Drilldown + Detail panels.
- Virtualized list (only render visible rows) — supports 500+ symbols without DOM thrash.

### Signal Drilldown Panel (center) — two tabs

**DRILLDOWN tab:**
- Kalman α time-series: `AreaChart` (Recharts), last 200 ticks, green fill above zero / red below.
- Hawkes λ decay: `LineChart`, exponential decay curve visible between events.
- CUSUM accumulator: animated progress bar from 0 → 5.0, flashes red on fire and resets.
- 500-symbol alpha heatmap: flat grid of colored cells (`#34d399` → `#f87171` by alpha sign/magnitude), `useMemo`-memoized.

**DEPTH tab** (Upstox V3 market data — see section 3):
- Bid/ask ladder: levels rendered based on `depth_levels` field in incoming WebSocket frames (5 or 20, never hardcoded).
- OBI sparkline: last 60 values from `feature_engine` OBI computation.
- Volume-at-price: horizontal `BarChart`, price levels on Y, volume on X.
- Trade tape: virtualized scrolling list of recent prints (price, qty, side inferred as BUY if `price >= ask[0].price`, SELL if `price <= bid[0].price`, else UNKNOWN).

### Detail Panel (right, ~220px)

Shows metrics for `selectedSymbol`:

| Field | Source |
|-------|--------|
| Kalman α | `orderflowStore.symbols[selected].alpha` |
| Hawkes λ | `orderflowStore.symbols[selected].lambda` |
| CUSUM C | `orderflowStore.symbols[selected].cusum_c` |
| σ² (variance) | `orderflowStore.symbols[selected].variance` |
| Kyle λ | `orderflowStore.symbols[selected].kyle_lambda` |
| q* size | `orderflowStore.symbols[selected].q_star` |
| EOD conviction % | pulled from `convictionStore.rankedSymbols` by symbol match |
| Fires today | count from `orderflowStore.cusumFires` filtered by symbol |

### Signal Ticker (bottom strip)

Autoscrolling marquee of last 100 CUSUM fire + strong signal events. Format: `09:24:31 TCS ⚡ BUY q*=82 α=+0.00423`. Fires in red, normal signals in green.

---

## 2. EOD Conviction Dashboard (`/dashboard/conviction`)

### Tab 1: Stock Selection (pre-market ranking)

Updated via SSE at market open and on each CUSUM fire event.

- Table columns: rank, symbol, conviction score (5-day avg) with inline bar, delivery %, Kalman α, Hawkes λ, CUSUM C, q\*, fire indicator.
- Sorted: `avg_conviction_score × sign(kalman_alpha)` descending.
- CUSUM-fired rows highlighted red.
- Filter controls: lookback days (5/10/20), show top N (20/50/100).
- Conviction score = `DELIV_QTY / TOTTRDQTY` from `eod_bhavcopy` table, averaged over lookback window.

### Tab 2: Intraday Correlation

- `ScatterChart` (Recharts): X = today's CUSUM C value, Y = EOD conviction score, one dot per tracked symbol.
- Trend line: linear regression overlay rendered as a single SVG `<line>` element.
- Stat cards: Pearson r, fires-with-high-conviction hit rate (conv > 0.6), average conviction at fire vs universe average.
- Updates via SSE on each new CUSUM fire event (re-fetches scatter data for that symbol).

### Tab 3: Trend (symbol-level delivery history)

- Activated by clicking any symbol in Tab 1 or Tab 2.
- `BarChart`: 20 trading days of delivery % bars. Color ramp: dark blue → green as conviction improves.
- CUSUM fire overlay: thin red bars in a secondary row beneath the main chart aligned to same day axis.
- Fetched via `GET /api/conviction/trend/{symbol}` (REST, not streaming). Cached in Redis 30 min.

---

## 3. Upstox V3 Market Depth Integration

### Subscription tier detection

On ingestor startup, call `GET /v3/user/profile` (one REST call, no rate limit impact). Store result in Redis key `upstox:depth_levels` with value `20`, `5`, or `0` depending on subscription. All downstream services read from Redis — no repeated API calls.

### Mixed-mode subscription strategy

- **Default**: all 1000 symbols subscribe to `ltpc` mode (lowest bandwidth, single WebSocket connection).
- **On depth tab open**: API Gateway writes focused symbol to Redis key `depth:focused_symbol`. Ingestor polls this key every 2s; when it changes, sends a Upstox V3 WebSocket re-subscribe message upgrading that symbol to `full` (5 levels) or `full_with_20depth` (20 levels) per `upstox:depth_levels`. Maximum one symbol in elevated mode at any time.
- **On depth tab close / client disconnect**: API Gateway clears `depth:focused_symbol`. Ingestor reverts symbol to `ltpc`.

### Kafka topic: `market-depth`

Each message: `{symbol, timestamp_ns, depth_levels, bids: [{price, qty, orders}×N], asks: [{price, qty, orders}×N], ltp, volume}`.

### API Gateway endpoint: `/ws/depth/{symbol}`

- On connect: writes symbol to `depth:focused_symbol` in Redis.
- Consumes `market-depth` Kafka topic, filters by symbol, streams frames to client.
- Cadence: up to 100ms (batches rapid ticks within same 100ms window).
- On disconnect: clears `depth:focused_symbol`.

### Free tier rate limit compliance

| Limit | How respected |
|-------|--------------|
| 1 WebSocket connection to Upstox | Single ingestor process, never creates a second connection |
| 1000 symbols per connection | Capped at 1000 in `SymbolRegistry` (already enforced) |
| No per-tick REST calls | Zero REST calls on any hot path |
| REST reconnect | Exponential backoff: base 1s, multiplier 2×, cap 30s, jitter ±20% |
| WebSocket reconnect | Same exponential backoff, never faster than 5s |
| Conviction trend REST | Redis cache, TTL 30 min — at most 1 call per symbol per 30 min |

---

## 4. Architecture

### New API Gateway endpoints (`services/api_gateway/main.py`)

| Endpoint | Type | Purpose |
|----------|------|---------|
| `GET /ws/orderflow` | WebSocket | Streams microstructure signals from `microstructure` Kafka topic. Broadcasts `{symbol, alpha, lambda, cusum_c, cusum_fired, q_star, kyle_lambda, variance}` at ≤50ms cadence. CUSUM fires sent immediately (priority). |
| `GET /ws/depth/{symbol}` | WebSocket | Streams market depth frames from `market-depth` Kafka topic filtered by symbol. Manages `depth:focused_symbol` Redis key lifecycle. |
| `GET /api/conviction/stream` | SSE | Streams ranked symbol list from `eod_bhavcopy` at market open + on CUSUM fire events. Sends `ranked_list` and `correlation_stats` as distinct SSE event types. |
| `GET /api/conviction/trend/{symbol}` | REST GET | Returns 20 rows of `eod_bhavcopy` for a symbol. Redis-cached 30 min. |

### Frontend state (`frontend/src/`)

**Stores (Zustand):**

- `stores/orderflowStore.ts`
  - `symbols: Record<string, SymbolState>` — keyed by symbol string
  - `watchlist: string[]` — sorted symbol array (recomputed on each WS frame)
  - `selectedSymbol: string | null`
  - `signalFeed: SignalEvent[]` — last 100, for ticker
  - `cusumFires: CusumFire[]` — for detail panel fire count + Tab 2 scatter
  - `depthData: DepthFrame | null` — latest depth frame for selectedSymbol (from `/ws/depth`)
  - `wsStatus: 'connecting' | 'connected' | 'disconnected'`

- `stores/convictionStore.ts`
  - `rankedSymbols: RankedSymbol[]`
  - `correlationStats: CorrelationStats | null`
  - `trendData: Record<string, TrendRow[]>` — keyed by symbol, populated on demand
  - `sseStatus: 'connecting' | 'connected' | 'disconnected'`

**Hooks:**

- `hooks/useOrderFlowWS.ts` — connects to `/ws/orderflow`, dispatches to `orderflowStore`. Exponential backoff reconnect.
- `hooks/useMarketDepthWS.ts` — connects to `/ws/depth/{symbol}`, re-connects on symbol change, dispatches depth frames to `orderflowStore.depthData`. Disconnects when depth tab is not visible (IntersectionObserver / tab visibility check).
- `hooks/useConvictionSSE.ts` — EventSource to `/api/conviction/stream`, dispatches to `convictionStore`. Reconnects with backoff.
- `hooks/useConvictionTrend.ts` — fetches `/api/conviction/trend/{symbol}` on symbol change, writes to `convictionStore.trendData`. Skips fetch if already cached.

**New pages:**

- `app/dashboard/orderflow/page.tsx` — renders Layout C. Mounts `useOrderFlowWS` at page level.
- `app/dashboard/conviction/page.tsx` — 3-tab page. Mounts `useConvictionSSE` at page level. Tab 3 mounts `useConvictionTrend` when a symbol is selected.

**Shared components:**

- `components/charts/AlphaAreaChart.tsx` — Recharts `AreaChart` wrapper, green/red fill by sign.
- `components/charts/HawkesLineChart.tsx` — Recharts `LineChart`.
- `components/charts/CusumBar.tsx` — animated progress bar, flash-on-fire.
- `components/charts/AlphaHeatmap.tsx` — memoized flat grid, virtualized.
- `components/charts/DepthLadder.tsx` — dynamic levels, bid/ask, OBI bar.
- `components/charts/VolumeAtPrice.tsx` — horizontal `BarChart`.
- `components/charts/ConvictionScatter.tsx` — `ScatterChart` with regression line SVG overlay.
- `components/charts/DeliveryTrendChart.tsx` — `BarChart` + CUSUM fire overlay.

---

## 5. Existing Frontend Fixes

| Issue | Fix |
|-------|-----|
| `/dashboard/live` uses `setInterval` 2s polling | Replace with WebSocket connection to existing `/ws/live` endpoint |
| `TradingDashboard` renders hardcoded mock arrays | Remove mock data; connect to real API endpoints |
| `BacktestRunner` prop name mismatch | Fix prop name to match what the parent component passes |
| TypeScript `any` casts in existing dashboard files | Replace with proper types when touching those files (in-scope files only) |

---

## 6. Performance Constraints

- Watchlist virtualization: only render rows in viewport (react-window or manual windowing).
- Heatmap: `useMemo` on the full symbol array, update only changed cells.
- WebSocket frame processing: dispatch via `requestAnimationFrame` batching — never block main thread with >500 symbol updates.
- Recharts charts: fixed `width`/`height` (no `ResponsiveContainer` on the hot-path charts) to avoid layout thrash.
- No `useEffect` chains for data — all WS/SSE writes go directly to Zustand, components read via selectors.

---

## 7. Testing

- Unit tests for all hooks using `renderHook` + mock WebSocket/EventSource.
- Unit tests for Zustand store reducers (pure functions, no mocks needed).
- `DepthLadder` component test: verify it renders `depth_levels` rows from frame, not a hardcoded count.
- Rate limit test: assert ingestor never calls re-subscribe more than once per 2s polling interval.
- API Gateway depth endpoint test: assert `depth:focused_symbol` Redis key is set on connect and cleared on disconnect.

---

## Out of Scope

- IDE file save/load
- Options page
- Backtest runner beyond the prop fix
- Any new backend Kafka topics beyond `market-depth`
- Authentication changes

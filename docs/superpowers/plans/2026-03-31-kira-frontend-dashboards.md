# KIRA Frontend Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Order Flow and EOD Conviction dashboards to the KIRA frontend, wire them to real backend signals via WebSocket/SSE, and fix critical existing frontend issues.

**Architecture:** Strategy runtime writes microstructure state (Kalman α, Hawkes λ, CUSUM C) to Redis after each tick. The API Gateway exposes WebSocket endpoints that read from Redis (orderflow) and Kafka (depth), plus SSE/REST for the conviction dashboard. The Next.js frontend uses Zustand stores + custom hooks to consume these feeds.

**Tech Stack:** Python (FastAPI, redis, confluent-kafka, sse-starlette), Next.js 14, Recharts 3, Zustand 5, TypeScript.

**All work on `develop` branch. Python tests run inside Docker.**

---

## File Map

**New backend files:**
- `services/strategy_runtime/tests/test_redis_publishing.py` — tests for Redis state write
- `services/api_gateway/tests/__init__.py`
- `services/api_gateway/tests/test_ws_orderflow.py`
- `services/api_gateway/tests/test_ws_depth.py`
- `services/api_gateway/tests/test_conviction.py`

**Modified backend files:**
- `services/strategy_runtime/main_legacy.py` — add Redis publish in `_process_tick_microstructure`
- `services/api_gateway/main.py` — fix redis_client init, add WS/SSE/REST endpoints
- `services/api_gateway/requirements.txt` — add redis, sse-starlette

**New frontend files:**
- `frontend/src/types/orderflow.ts`
- `frontend/src/types/conviction.ts`
- `frontend/src/stores/orderflowStore.ts`
- `frontend/src/stores/convictionStore.ts`
- `frontend/src/hooks/useOrderFlowWS.ts`
- `frontend/src/hooks/useMarketDepthWS.ts`
- `frontend/src/hooks/useConvictionSSE.ts`
- `frontend/src/hooks/useConvictionTrend.ts`
- `frontend/src/components/charts/AlphaAreaChart.tsx`
- `frontend/src/components/charts/HawkesLineChart.tsx`
- `frontend/src/components/charts/CusumBar.tsx`
- `frontend/src/components/charts/AlphaHeatmap.tsx`
- `frontend/src/components/charts/DepthLadder.tsx`
- `frontend/src/components/charts/ConvictionScatter.tsx`
- `frontend/src/components/charts/DeliveryTrendChart.tsx`
- `frontend/src/components/GlobalStatusBar.tsx`
- `frontend/src/app/dashboard/layout.tsx`
- `frontend/src/app/dashboard/orderflow/page.tsx`
- `frontend/src/app/dashboard/conviction/page.tsx`

**Modified frontend files:**
- `frontend/src/app/dashboard/live/page.tsx` — replace setInterval polling with WebSocket
- `frontend/src/components/TradingDashboard.tsx` — remove hardcoded mock data

---

## Task 1: Strategy Runtime — Publish Microstructure State to Redis

**Files:**
- Modify: `services/strategy_runtime/main_legacy.py`
- Create: `services/strategy_runtime/tests/test_redis_publishing.py`

Context: `_process_tick_microstructure()` at line ~140 computes Kalman α / Hawkes λ / CUSUM C but only logs results. We need it to write the latest per-symbol state to Redis so the API Gateway can read it. `redis` is already in requirements.txt.

- [ ] **Step 1: Write the failing test**

Create `services/strategy_runtime/tests/test_redis_publishing.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _make_tick(symbol="NSE_EQ|RELIANCE", ltp=2480.0, volume=1000.0, prev_price=2470.0):
    return {
        "instrument_key": symbol,
        "ltp": ltp,
        "volume": volume,
        "prev_price": prev_price,
        "obi": 0.3,
        "exchange_timestamp": 1700000000000,
        "atr": 15.0,
        "bid_price": 2479.0,
        "ask_price": 2481.0,
    }


def test_redis_hash_written_after_tick():
    """After processing a tick, Redis hset is called with the symbol key and state fields."""
    import importlib
    import main_legacy as ml

    mock_redis = MagicMock()
    mock_engine = MagicMock()
    mock_engine.update_tick.return_value = False
    mock_engine.get_state.return_value = {
        "alpha_kalman": 0.00423,
        "lambda_hawkes": 14820.0,
        "cusum_c": 3.8,
        "variance": 0.000142,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 0

    with patch.object(ml, '_MICRO_ENGINE', mock_engine), \
         patch.object(ml, '_SYM_REGISTRY', mock_registry), \
         patch.object(ml, '_HAS_MICRO_ENGINE', True), \
         patch.object(ml, '_REDIS', mock_redis):
        ml._process_tick_microstructure(_make_tick())

    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    key = call_args[0][0]
    assert key == "microstructure:NSE_EQ|RELIANCE"
    mapping = call_args[1].get("mapping") or call_args[0][1]
    assert "alpha" in mapping
    assert "lambda_hawkes" in mapping
    assert "cusum_c" in mapping


def test_redis_cusum_fire_published():
    """When CUSUM fires, Redis publish is called on the cusum-fires channel."""
    import main_legacy as ml

    mock_redis = MagicMock()
    mock_engine = MagicMock()
    mock_engine.update_tick.return_value = True  # fire!
    mock_engine.get_state.return_value = {
        "alpha_kalman": 0.00423,
        "lambda_hawkes": 14820.0,
        "cusum_c": 0.0,
        "variance": 0.000142,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 0

    with patch.object(ml, '_MICRO_ENGINE', mock_engine), \
         patch.object(ml, '_SYM_REGISTRY', mock_registry), \
         patch.object(ml, '_HAS_MICRO_ENGINE', True), \
         patch.object(ml, '_REDIS', mock_redis):
        ml._process_tick_microstructure(_make_tick())

    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[0][0]
    assert channel == "cusum-fires"


def test_redis_none_does_not_crash():
    """If _REDIS is None (Redis unavailable), function completes without error."""
    import main_legacy as ml

    mock_engine = MagicMock()
    mock_engine.update_tick.return_value = False
    mock_engine.get_state.return_value = {
        "alpha_kalman": 0.0, "lambda_hawkes": 0.0, "cusum_c": 0.0, "variance": 0.0,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 0

    with patch.object(ml, '_MICRO_ENGINE', mock_engine), \
         patch.object(ml, '_SYM_REGISTRY', mock_registry), \
         patch.object(ml, '_HAS_MICRO_ENGINE', True), \
         patch.object(ml, '_REDIS', None):
        ml._process_tick_microstructure(_make_tick())  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec strategy_runtime python3 -m pytest tests/test_redis_publishing.py -v
```

Expected: FAIL — `AttributeError: module 'main_legacy' has no attribute '_REDIS'`

- [ ] **Step 3: Add Redis client to strategy_runtime/main_legacy.py**

At the top of `services/strategy_runtime/main_legacy.py`, after the existing imports (around line 10), add:

```python
import redis as redis_lib

_REDIS: redis_lib.Redis | None = None

def _init_redis() -> redis_lib.Redis | None:
    try:
        r = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "redis_state"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        r.ping()
        return r
    except Exception as e:
        logger.warning("Redis unavailable, microstructure state will not be published: %s", e)
        return None
```

- [ ] **Step 4: Update `_process_tick_microstructure` to write state**

Replace the body of `_process_tick_microstructure` from the `if cusum_fired:` block to the end of the function (currently just a logger.info call). The full replacement for `_process_tick_microstructure` (lines ~140–185 in main_legacy.py):

```python
def _process_tick_microstructure(tick: dict) -> None:
    """Feed enriched tick into MicrostructureEngine. Publishes state to Redis."""
    if not _HAS_MICRO_ENGINE:
        return

    instrument_key = str(tick.get("instrument_token") or tick.get("instrument_key", ""))
    if not instrument_key:
        return

    sym_id = _SYM_REGISTRY.register(instrument_key)
    if sym_id is None:
        return

    ltp = float(tick.get("ltp") or tick.get("last_price") or 0.0)
    volume = float(tick.get("volume") or 0.0)
    obi = float(tick.get("obi") or 0.0)
    ts_ms = float(tick.get("exchange_timestamp") or 0)
    ts_seconds = ts_ms / 1000.0

    prev_price = float(tick.get("prev_price") or ltp)
    actual_return = (ltp - prev_price) / prev_price if prev_price > 0 else 0.0

    cusum_fired = _MICRO_ENGINE.update_tick(sym_id, actual_return, 0.0, volume, ts_seconds)
    state = _MICRO_ENGINE.get_state(sym_id)

    atr = float(tick.get("atr") or 15.0)
    kyle_lam = compute_kyle_lambda(atr=atr, avg_daily_volume=max(volume, 1.0))
    bid = float(tick.get("bid_price") or 0.0)
    ask = float(tick.get("ask_price") or 0.0)
    spread = abs(ask - bid) if ask > bid else 0.05

    q = kelly_with_market_impact(
        alpha_kalman=state["alpha_kalman"],
        lambda_hawkes=state["lambda_hawkes"],
        obi=obi,
        spread=spread,
        kyle_lambda=kyle_lam,
    )

    if _REDIS is not None:
        try:
            import json as _json
            mapping = {
                "alpha": str(state["alpha_kalman"]),
                "lambda_hawkes": str(state["lambda_hawkes"]),
                "cusum_c": str(state["cusum_c"]),
                "variance": str(state.get("variance", 0.0)),
                "q_star": str(q),
                "kyle_lambda": str(kyle_lam),
                "symbol": instrument_key,
                "ts_ms": str(int(ts_ms)),
            }
            _REDIS.hset(f"microstructure:{instrument_key}", mapping=mapping)
            if cusum_fired:
                _REDIS.publish("cusum-fires", _json.dumps({
                    "symbol": instrument_key,
                    "q_star": q,
                    "alpha": state["alpha_kalman"],
                    "ts_ms": int(ts_ms),
                }))
        except Exception:
            pass  # never crash the tick pipeline

    if cusum_fired:
        logger.info(
            "CUSUM FIRE | %s | q*=%d | alpha=%.5f | hawkes=%.1f",
            instrument_key, q, state["alpha_kalman"], state["lambda_hawkes"]
        )
```

- [ ] **Step 5: Initialize Redis in `run_engine()`**

In `run_engine()` (around line 185), before the `# 0. Wait for Kafka` comment, add:

```python
    global _REDIS
    _REDIS = _init_redis()
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker compose exec strategy_runtime python3 -m pytest tests/test_redis_publishing.py -v
```

Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add services/strategy_runtime/main_legacy.py \
        services/strategy_runtime/tests/test_redis_publishing.py
git commit -m "feat(strategy_runtime): publish microstructure state to Redis per tick"
```

---

## Task 2: API Gateway — Fix Redis + Add `/ws/orderflow`

**Files:**
- Modify: `services/api_gateway/main.py`
- Modify: `services/api_gateway/requirements.txt`
- Create: `services/api_gateway/tests/__init__.py`
- Create: `services/api_gateway/tests/test_ws_orderflow.py`

Context: `redis_client` is referenced in main.py at lines ~1376 and ~1411 but never initialized — this is a silent bug. We fix that and add the `/ws/orderflow` WebSocket endpoint that polls Redis every 50ms and broadcasts all symbol states to connected clients.

- [ ] **Step 1: Add dependencies**

Append to `services/api_gateway/requirements.txt`:

```
redis
sse-starlette
websockets
httpx
pytest
pytest-asyncio
```

- [ ] **Step 2: Write the failing test**

Create `services/api_gateway/tests/__init__.py` (empty).

Create `services/api_gateway/tests/test_ws_orderflow.py`:

```python
import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock


def _make_redis_scan_response(symbols):
    """Returns (cursor, [keys]) as redis SCAN would."""
    keys = [f"microstructure:{s}" for s in symbols]
    return (0, keys)


def _make_redis_hgetall(alpha="0.00423", lam="14820.0", cusum_c="3.8",
                        variance="0.000142", q_star="45", kyle_lambda="0.0002",
                        symbol="NSE_EQ|RELIANCE", ts_ms="1700000000000"):
    return {
        "alpha": alpha, "lambda_hawkes": lam, "cusum_c": cusum_c,
        "variance": variance, "q_star": q_star, "kyle_lambda": kyle_lambda,
        "symbol": symbol, "ts_ms": ts_ms,
    }


@pytest.mark.asyncio
async def test_ws_orderflow_sends_snapshot():
    """WebSocket /ws/orderflow sends a JSON array of symbol states within 200ms."""
    from httpx import AsyncClient, ASGITransport
    import main as app_module

    mock_redis = MagicMock()
    mock_redis.scan.return_value = _make_redis_scan_response(["NSE_EQ|RELIANCE"])
    mock_redis.hgetall.return_value = _make_redis_hgetall()

    with patch.object(app_module, 'redis_client', mock_redis):
        transport = ASGITransport(app=app_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream("GET", "/ws/orderflow",
                                 headers={"upgrade": "websocket",
                                          "connection": "upgrade",
                                          "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ==",
                                          "sec-websocket-version": "13"}) as resp:
                # For WebSocket tests, we verify the endpoint exists and
                # the redis calls are invoked correctly
                pass

    # Simpler assertion: verify the redis scan is called
    # (Full WS protocol testing requires starlette.testclient)
    from starlette.testclient import TestClient
    with patch.object(app_module, 'redis_client', mock_redis):
        client = TestClient(app_module.app)
        with client.websocket_connect("/ws/orderflow") as ws:
            data = ws.receive_text()
            payload = json.loads(data)
            assert isinstance(payload, list)
            assert len(payload) == 1
            assert payload[0]["symbol"] == "NSE_EQ|RELIANCE"
            assert "alpha" in payload[0]
            assert "cusum_c" in payload[0]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
docker compose exec api_gateway python3 -m pytest tests/test_ws_orderflow.py -v
```

Expected: FAIL — ImportError or AttributeError (no redis_client, no /ws/orderflow)

- [ ] **Step 4: Add Redis initialization to api_gateway/main.py**

After the existing imports at the top of `services/api_gateway/main.py`, add:

```python
import redis as redis_sync
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
```

After the `load_dotenv()` call, add Redis initialization:

```python
# --- REDIS CLIENT ---
def _init_redis_client():
    try:
        r = redis_sync.Redis(
            host=os.getenv("REDIS_HOST", "redis_state"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        r.ping()
        return r
    except Exception as e:
        print(f"Warning: Redis unavailable: {e}")
        return None

redis_client = _init_redis_client()
```

- [ ] **Step 5: Add `/ws/orderflow` endpoint to api_gateway/main.py**

Append before the final `if __name__ == "__main__"` block (or at the end of the route definitions):

```python
# ─── ORDER FLOW WEBSOCKET ───────────────────────────────────────────────────

class _OrderFlowManager:
    """Tracks connected WebSocket clients."""
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active = [c for c in self.active if c is not ws]

    async def broadcast(self, payload: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


_of_manager = _OrderFlowManager()


def _read_all_microstructure() -> list[dict]:
    """Read all microstructure:* keys from Redis synchronously."""
    if redis_client is None:
        return []
    try:
        _, keys = redis_client.scan(match="microstructure:*", count=1000)
        if not keys:
            return []
        result = []
        for key in keys:
            raw = redis_client.hgetall(key)
            if not raw:
                continue
            result.append({
                "symbol": raw.get("symbol", key.split(":", 1)[-1]),
                "alpha": float(raw.get("alpha", 0)),
                "lambda_hawkes": float(raw.get("lambda_hawkes", 0)),
                "cusum_c": float(raw.get("cusum_c", 0)),
                "variance": float(raw.get("variance", 0)),
                "q_star": int(float(raw.get("q_star", 0))),
                "kyle_lambda": float(raw.get("kyle_lambda", 0)),
                "ts_ms": int(float(raw.get("ts_ms", 0))),
                "cusum_fired": False,
            })
        return result
    except Exception:
        return []


@app.websocket("/ws/orderflow")
async def ws_orderflow(websocket: WebSocket):
    """Stream microstructure state for all symbols every 50ms."""
    await _of_manager.connect(websocket)
    try:
        while True:
            loop = asyncio.get_event_loop()
            states = await loop.run_in_executor(None, _read_all_microstructure)
            import json as _json
            # Sort by |alpha| + lambda_hawkes/1e5 descending (watchlist order)
            states.sort(
                key=lambda s: abs(s["alpha"]) + s["lambda_hawkes"] / 1e5,
                reverse=True,
            )
            await websocket.send_text(_json.dumps(states))
            await asyncio.sleep(0.05)  # 50ms cadence
    except (WebSocketDisconnect, Exception):
        _of_manager.disconnect(websocket)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
docker compose exec api_gateway python3 -m pytest tests/test_ws_orderflow.py -v
```

Expected: 1 passed

- [ ] **Step 7: Commit**

```bash
git add services/api_gateway/main.py \
        services/api_gateway/requirements.txt \
        services/api_gateway/tests/__init__.py \
        services/api_gateway/tests/test_ws_orderflow.py
git commit -m "feat(api_gateway): fix Redis init, add /ws/orderflow WebSocket endpoint"
```

---

## Task 3: API Gateway — `/ws/depth/{symbol}`

**Files:**
- Modify: `services/api_gateway/main.py`
- Create: `services/api_gateway/tests/test_ws_depth.py`

Context: The ingestion service already subscribes equities in `full` mode and publishes depth (`buy`/`sell` arrays) inside each tick on Kafka topic `market.equity.ticks`. The depth endpoint consumes that topic, filters by symbol, and streams frames. `depth_levels = len(depth.buy)` — never hardcoded.

- [ ] **Step 1: Write the failing test**

Create `services/api_gateway/tests/test_ws_depth.py`:

```python
import pytest
import json
from unittest.mock import patch, MagicMock


def _make_envelope(symbol="NSE_EQ|TCS", ltp=3820.0, depth_buy=None, depth_sell=None):
    import uuid
    if depth_buy is None:
        depth_buy = [
            {"price": 3819.0, "quantity": 500},
            {"price": 3818.5, "quantity": 300},
            {"price": 3818.0, "quantity": 200},
            {"price": 3817.5, "quantity": 150},
            {"price": 3817.0, "quantity": 100},
        ]
    if depth_sell is None:
        depth_sell = [
            {"price": 3820.0, "quantity": 400},
            {"price": 3820.5, "quantity": 350},
            {"price": 3821.0, "quantity": 250},
            {"price": 3821.5, "quantity": 180},
            {"price": 3822.0, "quantity": 120},
        ]
    payload = {
        "symbol": symbol,
        "ltp": ltp,
        "v": 1000,
        "depth": {"buy": depth_buy, "sell": depth_sell},
        "timestamp": 1700000000000,
    }
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": "market.tick",
        "source": "upstox_ingestor",
        "payload": payload,
    }
    return json.dumps(envelope).encode()


def test_depth_frame_structure():
    """_parse_depth_frame extracts bids, asks, depth_levels, ltp correctly."""
    import main as app_module

    raw = _make_envelope()
    frame = app_module._parse_depth_frame(raw, "NSE_EQ|TCS")

    assert frame is not None
    assert frame["symbol"] == "NSE_EQ|TCS"
    assert frame["ltp"] == 3820.0
    assert frame["depth_levels"] == 5
    assert len(frame["bids"]) == 5
    assert len(frame["asks"]) == 5
    assert frame["bids"][0]["price"] == 3819.0
    assert frame["asks"][0]["price"] == 3820.0


def test_depth_frame_wrong_symbol_returns_none():
    """_parse_depth_frame returns None if the message is for a different symbol."""
    import main as app_module

    raw = _make_envelope(symbol="NSE_EQ|INFY")
    frame = app_module._parse_depth_frame(raw, "NSE_EQ|TCS")
    assert frame is None


def test_depth_frame_no_depth_returns_none():
    """_parse_depth_frame returns None if depth is empty."""
    import main as app_module

    raw = _make_envelope(depth_buy=[], depth_sell=[])
    frame = app_module._parse_depth_frame(raw, "NSE_EQ|TCS")
    assert frame is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec api_gateway python3 -m pytest tests/test_ws_depth.py -v
```

Expected: FAIL — AttributeError: module 'main' has no attribute '_parse_depth_frame'

- [ ] **Step 3: Add `_parse_depth_frame` + `/ws/depth/{symbol}` to api_gateway/main.py**

Append after the `/ws/orderflow` block:

```python
# ─── MARKET DEPTH WEBSOCKET ──────────────────────────────────────────────────

def _parse_depth_frame(raw_bytes: bytes, target_symbol: str) -> dict | None:
    """Parse a KafkaEnvelope bytes into a depth frame for target_symbol.
    Returns None if the message is for a different symbol or has no depth.
    """
    try:
        envelope = json.loads(raw_bytes.decode("utf-8"))
        payload = envelope.get("payload", {})
        symbol = payload.get("symbol", "")
        if symbol != target_symbol:
            return None
        depth = payload.get("depth", {})
        bids = depth.get("buy", [])
        asks = depth.get("sell", [])
        if not bids and not asks:
            return None
        return {
            "symbol": symbol,
            "ltp": float(payload.get("ltp", 0)),
            "depth_levels": len(bids),
            "bids": bids,
            "asks": asks,
            "ts_ms": int(payload.get("timestamp", 0)),
        }
    except Exception:
        return None


@app.websocket("/ws/depth/{symbol}")
async def ws_depth(websocket: WebSocket, symbol: str):
    """Stream Upstox V3 market depth for a single symbol."""
    await websocket.accept()
    from confluent_kafka import Consumer, KafkaError
    import uuid as _uuid

    group_id = f"ws-depth-{_uuid.uuid4().hex[:8]}"
    conf = {
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka_bus:9092"),
        "group.id": group_id,
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    }

    loop = asyncio.get_event_loop()

    def _consume_one():
        consumer = Consumer(conf)
        consumer.subscribe(["market.equity.ticks"])
        try:
            while True:
                msg = consumer.poll(0.05)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    break
                frame = _parse_depth_frame(msg.value(), symbol)
                if frame is not None:
                    return frame
        finally:
            consumer.close()
        return None

    try:
        while True:
            frame = await loop.run_in_executor(None, _consume_one)
            if frame is not None:
                await websocket.send_text(json.dumps(frame))
    except (WebSocketDisconnect, Exception):
        pass
```

- [ ] **Step 4: Run tests**

```bash
docker compose exec api_gateway python3 -m pytest tests/test_ws_depth.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add services/api_gateway/main.py \
        services/api_gateway/tests/test_ws_depth.py
git commit -m "feat(api_gateway): add /ws/depth/{symbol} WebSocket for Upstox V3 market depth"
```

---

## Task 4: API Gateway — SSE Conviction + REST Trend + WS Live

**Files:**
- Modify: `services/api_gateway/main.py`
- Create: `services/api_gateway/tests/test_conviction.py`

Context: The `eod_bhavcopy` PostgreSQL table (created by eod_ingestor in Task 6 of the previous plan) has columns: `trade_date DATE`, `symbol TEXT`, `conviction_score FLOAT`, `total_volume BIGINT`, `delivery_qty BIGINT`. The API Gateway also needs a `/ws/live` endpoint for the live page fix in Task 11.

- [ ] **Step 1: Write the failing test**

Create `services/api_gateway/tests/test_conviction.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import date


def _mock_pg_rows(symbol="RELIANCE", score=0.74):
    return [(
        date(2026, 3, 29), symbol, score, 1_000_000, 740_000
    )]


def test_conviction_trend_returns_list():
    """GET /api/conviction/trend/{symbol} returns a list of up to 20 rows."""
    from starlette.testclient import TestClient
    import main as app_module

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = _mock_pg_rows()
    mock_conn.cursor.return_value = mock_cur

    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # cache miss

    with patch.object(app_module, 'redis_client', mock_redis), \
         patch('main.get_pg_conn', return_value=mock_conn):
        client = TestClient(app_module.app)
        resp = client.get("/api/conviction/trend/RELIANCE")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["symbol"] == "RELIANCE"
    assert "conviction_score" in data[0]
    assert "trade_date" in data[0]


def test_conviction_trend_uses_redis_cache():
    """Second call for same symbol returns cached result without hitting DB."""
    from starlette.testclient import TestClient
    import json
    import main as app_module

    cached = json.dumps([{"trade_date": "2026-03-29", "symbol": "TCS",
                          "conviction_score": 0.82, "total_volume": 500000,
                          "delivery_qty": 410000}])
    mock_redis = MagicMock()
    mock_redis.get.return_value = cached

    mock_conn = MagicMock()

    with patch.object(app_module, 'redis_client', mock_redis), \
         patch('main.get_pg_conn', return_value=mock_conn):
        client = TestClient(app_module.app)
        resp = client.get("/api/conviction/trend/TCS")

    assert resp.status_code == 200
    mock_conn.cursor.assert_not_called()  # DB not hit on cache hit
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec api_gateway python3 -m pytest tests/test_conviction.py -v
```

Expected: FAIL — 404 Not Found for `/api/conviction/trend/RELIANCE`

- [ ] **Step 3: Add conviction endpoints + `/ws/live` to api_gateway/main.py**

Append after the depth WebSocket block:

```python
# ─── CONVICTION REST + SSE ───────────────────────────────────────────────────
from sse_starlette.sse import EventSourceResponse

_TREND_CACHE_TTL = 1800  # 30 minutes


@app.get("/api/conviction/trend/{symbol}")
def conviction_trend(symbol: str, conn=Depends(get_pg_conn)):
    """Return 20 trading days of EOD bhavcopy data for a symbol. Redis-cached 30 min."""
    cache_key = f"conviction_trend:{symbol}"

    if redis_client is not None:
        cached = redis_client.get(cache_key)
        if cached:
            import json as _j
            return _j.loads(cached)

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT trade_date, symbol, conviction_score, total_volume, delivery_qty
            FROM eod_bhavcopy
            WHERE symbol = %s
            ORDER BY trade_date DESC
            LIMIT 20
            """,
            (symbol,),
        )
        rows = cur.fetchall()
        cur.close()
        result = [
            {
                "trade_date": str(r[0]),
                "symbol": r[1],
                "conviction_score": float(r[2]) if r[2] is not None else 0.0,
                "total_volume": int(r[3]) if r[3] else 0,
                "delivery_qty": int(r[4]) if r[4] else 0,
            }
            for r in rows
        ]
        if redis_client is not None:
            import json as _j
            redis_client.set(cache_key, _j.dumps(result), ex=_TREND_CACHE_TTL)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_ranked_list(conn) -> list[dict]:
    """Query eod_bhavcopy + Redis microstructure states, return sorted ranking."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT symbol,
                   AVG(conviction_score) AS avg_conv,
                   MAX(trade_date)       AS latest_date
            FROM eod_bhavcopy
            WHERE trade_date >= CURRENT_DATE - INTERVAL '5 days'
            GROUP BY symbol
            ORDER BY avg_conv DESC
            LIMIT 200
            """,
        )
        rows = cur.fetchall()
        cur.close()
    except Exception:
        rows = []

    result = []
    for r in rows:
        symbol, avg_conv, latest_date = r[0], float(r[1] or 0), str(r[2])
        micro: dict = {}
        if redis_client is not None:
            try:
                raw = redis_client.hgetall(f"microstructure:{symbol}")
                if raw:
                    micro = {
                        "alpha": float(raw.get("alpha", 0)),
                        "lambda_hawkes": float(raw.get("lambda_hawkes", 0)),
                        "cusum_c": float(raw.get("cusum_c", 0)),
                        "q_star": int(float(raw.get("q_star", 0))),
                    }
            except Exception:
                pass
        result.append({
            "symbol": symbol,
            "avg_conviction": avg_conv,
            "latest_date": latest_date,
            **micro,
        })

    # Sort: avg_conviction × sign(alpha) desc
    result.sort(
        key=lambda x: x["avg_conviction"] * (1 if x.get("alpha", 0) >= 0 else -1),
        reverse=True,
    )
    return result


@app.get("/api/conviction/stream")
async def conviction_stream(conn=Depends(get_pg_conn)):
    """SSE stream: sends ranked list at connect + on each CUSUM fire."""
    import json as _j

    async def _generator():
        # 1. Initial snapshot
        ranked = await asyncio.get_event_loop().run_in_executor(
            None, _build_ranked_list, conn
        )
        yield {"event": "ranked_list", "data": _j.dumps(ranked)}

        # 2. Listen for CUSUM fires via Redis pub/sub and re-send on each fire
        if redis_client is None:
            return

        pubsub = redis_client.pubsub()
        pubsub.subscribe("cusum-fires")
        try:
            while True:
                message = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: pubsub.get_message(timeout=30)
                )
                if message and message["type"] == "message":
                    fire_data = _j.loads(message["data"])
                    yield {"event": "cusum_fire", "data": _j.dumps(fire_data)}
                    # Re-send updated ranked list
                    ranked = await asyncio.get_event_loop().run_in_executor(
                        None, _build_ranked_list, conn
                    )
                    yield {"event": "ranked_list", "data": _j.dumps(ranked)}
        except Exception:
            pass
        finally:
            pubsub.unsubscribe("cusum-fires")

    return EventSourceResponse(_generator())


# ─── LIVE WS (replaces 2s polling in /dashboard/live) ───────────────────────

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """Stream live trading status every 1s for the live dashboard."""
    await websocket.accept()
    import json as _j
    try:
        while True:
            try:
                resp = _http_session.get(
                    "http://strategy_runtime:8000/live/status", timeout=2
                )
                data = resp.json() if resp.status_code == 200 else {"status": "stopped"}
            except Exception:
                data = {"status": "stopped", "message": "Runtime unavailable"}
            await websocket.send_text(_j.dumps(data))
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, Exception):
        pass
```

- [ ] **Step 4: Run tests**

```bash
docker compose exec api_gateway python3 -m pytest tests/test_conviction.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add services/api_gateway/main.py \
        services/api_gateway/tests/test_conviction.py
git commit -m "feat(api_gateway): add /api/conviction/stream SSE, /api/conviction/trend REST, /ws/live WebSocket"
```

---

## Task 5: Frontend — Types + Zustand Stores

**Files:**
- Create: `frontend/src/types/orderflow.ts`
- Create: `frontend/src/types/conviction.ts`
- Create: `frontend/src/stores/orderflowStore.ts`
- Create: `frontend/src/stores/convictionStore.ts`

Context: Zustand 5 is already installed. No `any` types — every field is explicit.

- [ ] **Step 1: Create `frontend/src/types/orderflow.ts`**

```typescript
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
```

- [ ] **Step 2: Create `frontend/src/types/conviction.ts`**

```typescript
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
```

- [ ] **Step 3: Create `frontend/src/stores/orderflowStore.ts`**

```typescript
import { create } from 'zustand';
import type { SymbolState, DepthFrame, SignalEvent, CusumFire, WsStatus } from '@/types/orderflow';

const MAX_SIGNAL_FEED = 100;
const MAX_CUSUM_FIRES = 50;

interface OrderFlowStore {
  symbols: Record<string, SymbolState>;
  watchlist: string[];           // sorted symbol keys
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
```

- [ ] **Step 4: Create `frontend/src/stores/convictionStore.ts`**

```typescript
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
```

- [ ] **Step 5: Run TypeScript check**

```bash
cd /app/frontend && npx tsc --noEmit
```

Expected: 0 errors (ignoring pre-existing `.next/types` stale errors from deleted vektor page)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/ frontend/src/stores/
git commit -m "feat(frontend): add orderflow + conviction types and Zustand stores"
```

---

## Task 6: Frontend — WebSocket + SSE Hooks

**Files:**
- Create: `frontend/src/hooks/useOrderFlowWS.ts`
- Create: `frontend/src/hooks/useMarketDepthWS.ts`
- Create: `frontend/src/hooks/useConvictionSSE.ts`
- Create: `frontend/src/hooks/useConvictionTrend.ts`

Context: All hooks use exponential backoff reconnect (base 1s, cap 30s). Hooks write directly to Zustand stores — no intermediate state.

- [ ] **Step 1: Create `frontend/src/hooks/useOrderFlowWS.ts`**

```typescript
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

          // Derive signal events from CUSUM-fired symbols
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
                side: s.alpha >= 0 ? 'BUY' : 'SELL',
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
        retryRef.current = setTimeout(connect, delay + Math.random() * 200);
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
```

- [ ] **Step 2: Create `frontend/src/hooks/useMarketDepthWS.ts`**

```typescript
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
```

- [ ] **Step 3: Create `frontend/src/hooks/useConvictionSSE.ts`**

```typescript
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
        retryRef.current = setTimeout(connect, delay + Math.random() * 200);
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
```

- [ ] **Step 4: Create `frontend/src/hooks/useConvictionTrend.ts`**

```typescript
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
        // set empty on failure so we don't retry indefinitely
        setTrendData(symbol, []);
      });
  }, [symbol, trendData, setTrendData]);

  return symbol ? (trendData[symbol] ?? null) : null;
}
```

- [ ] **Step 5: TypeScript check**

```bash
cd /app/frontend && npx tsc --noEmit
```

Expected: 0 new errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/
git commit -m "feat(frontend): add WebSocket + SSE hooks for orderflow and conviction"
```

---

## Task 7: Frontend — Chart Components

**Files:** All under `frontend/src/components/charts/`

Context: Bloomberg palette: `#34d399` (green), `#f87171` (red), `#f59e0b` (amber), `#60a5fa` (blue), `#a78bfa` (purple), `#0a0a0f` (bg), `#1f2937` (border). Fixed dimensions on all charts (no ResponsiveContainer on hot-path charts).

- [ ] **Step 1: Create `frontend/src/components/charts/AlphaAreaChart.tsx`**

```typescript
'use client';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';

interface AlphaTick {
  ts_ms: number;
  alpha: number;
}

interface Props {
  data: AlphaTick[];
  width?: number;
  height?: number;
}

export function AlphaAreaChart({ data, width = 320, height = 80 }: Props) {
  return (
    <AreaChart width={width} height={height} data={data}
      margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
      <defs>
        <linearGradient id="alphaGreen" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
          <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
        </linearGradient>
        <linearGradient id="alphaRed" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%" stopColor="#f87171" stopOpacity={0.3} />
          <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
        </linearGradient>
      </defs>
      <XAxis dataKey="ts_ms" hide />
      <YAxis tick={{ fontSize: 8, fill: '#4b5563' }} width={30} />
      <Tooltip
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 10 }}
        formatter={(v: number) => [v.toFixed(5), 'α']}
        labelFormatter={() => ''}
      />
      <ReferenceLine y={0} stroke="#1f2937" strokeWidth={1} />
      <Area type="monotone" dataKey="alpha"
        stroke="#34d399" strokeWidth={1.5}
        fill="url(#alphaGreen)"
        dot={false} isAnimationActive={false} />
    </AreaChart>
  );
}
```

- [ ] **Step 2: Create `frontend/src/components/charts/HawkesLineChart.tsx`**

```typescript
'use client';
import { LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';

interface HawkesTick {
  ts_ms: number;
  lambda: number;
}

interface Props {
  data: HawkesTick[];
  width?: number;
  height?: number;
}

export function HawkesLineChart({ data, width = 320, height = 60 }: Props) {
  return (
    <LineChart width={width} height={height} data={data}
      margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
      <XAxis dataKey="ts_ms" hide />
      <YAxis tick={{ fontSize: 8, fill: '#4b5563' }} width={30} />
      <Tooltip
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 10 }}
        formatter={(v: number) => [v.toFixed(0), 'λ']}
        labelFormatter={() => ''}
      />
      <Line type="monotone" dataKey="lambda"
        stroke="#f59e0b" strokeWidth={1.5}
        dot={false} isAnimationActive={false} />
    </LineChart>
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/charts/CusumBar.tsx`**

```typescript
'use client';
import { useEffect, useRef, useState } from 'react';

interface Props {
  value: number;   // 0 → 5.0
  threshold?: number;
  fired?: boolean;
}

export function CusumBar({ value, threshold = 5.0, fired = false }: Props) {
  const [flash, setFlash] = useState(false);
  const prevFired = useRef(false);

  useEffect(() => {
    if (fired && !prevFired.current) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 600);
      return () => clearTimeout(t);
    }
    prevFired.current = fired;
  }, [fired]);

  const pct = Math.min((value / threshold) * 100, 100);
  const color = pct > 80 ? '#f87171' : pct > 50 ? '#f59e0b' : '#34d399';

  return (
    <div style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ color: '#4b5563', fontSize: 9, fontFamily: 'monospace' }}>CUSUM C</span>
        <span style={{ color, fontSize: 9, fontFamily: 'monospace', fontWeight: 700 }}>
          {value.toFixed(2)} / {threshold.toFixed(1)}
        </span>
      </div>
      <div style={{
        height: 8, background: '#1f2937', borderRadius: 2, overflow: 'hidden',
        border: flash ? '1px solid #f87171' : '1px solid transparent',
        transition: 'border-color 0.1s',
      }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: color,
          borderRadius: 2, transition: 'width 0.1s linear, background 0.2s',
        }} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create `frontend/src/components/charts/AlphaHeatmap.tsx`**

```typescript
'use client';
import { useMemo } from 'react';
import type { SymbolState } from '@/types/orderflow';

interface Props {
  symbols: SymbolState[];
  onSelect?: (symbol: string) => void;
}

function alphaToColor(alpha: number): string {
  const intensity = Math.min(Math.abs(alpha) * 200, 1);
  if (alpha > 0) {
    const g = Math.round(52 + intensity * 160);
    return `rgb(30,${g},80)`;
  } else {
    const r = Math.round(100 + intensity * 150);
    return `rgb(${r},30,30)`;
  }
}

export const AlphaHeatmap = ({ symbols, onSelect }: Props) => {
  const cells = useMemo(
    () => symbols.map((s) => ({ symbol: s.symbol, color: alphaToColor(s.alpha) })),
    [symbols]
  );

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
      {cells.map(({ symbol, color }) => (
        <div
          key={symbol}
          title={symbol}
          onClick={() => onSelect?.(symbol)}
          style={{
            width: 8, height: 8, borderRadius: 1,
            background: color, cursor: 'pointer',
          }}
        />
      ))}
    </div>
  );
};
```

- [ ] **Step 5: Create `frontend/src/components/charts/DepthLadder.tsx`**

```typescript
'use client';
import type { DepthFrame, DepthLevel } from '@/types/orderflow';

interface Props {
  frame: DepthFrame | null;
}

function LevelRow({ level, side }: { level: DepthLevel; side: 'bid' | 'ask' }) {
  const color = side === 'bid' ? '#34d399' : '#f87171';
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 6px',
      fontFamily: 'monospace', fontSize: 9 }}>
      <span style={{ color }}>{level.price.toFixed(2)}</span>
      <span style={{ color: '#9ca3af' }}>{level.quantity.toLocaleString()}</span>
    </div>
  );
}

export function DepthLadder({ frame }: Props) {
  if (!frame) {
    return (
      <div style={{ color: '#4b5563', fontSize: 9, fontFamily: 'monospace', padding: 8 }}>
        Select a symbol to view order book depth
      </div>
    );
  }

  const { bids, asks, ltp, depth_levels } = frame;
  const totalBidQty = bids.reduce((s, l) => s + l.quantity, 0);
  const totalAskQty = asks.reduce((s, l) => s + l.quantity, 0);
  const obi = totalBidQty + totalAskQty > 0
    ? (totalBidQty - totalAskQty) / (totalBidQty + totalAskQty)
    : 0;

  return (
    <div style={{ fontFamily: 'monospace' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px',
        borderBottom: '1px solid #1f2937', marginBottom: 4 }}>
        <span style={{ color: '#4b5563', fontSize: 8 }}>DEPTH ({depth_levels} levels)</span>
        <span style={{ color: '#60a5fa', fontSize: 9, fontWeight: 700 }}>LTP {ltp.toFixed(2)}</span>
        <span style={{ color: obi >= 0 ? '#34d399' : '#f87171', fontSize: 8 }}>
          OBI {obi.toFixed(3)}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
        <div>
          <div style={{ color: '#4b5563', fontSize: 7, padding: '0 6px', marginBottom: 2 }}>BIDS</div>
          {bids.map((l, i) => <LevelRow key={i} level={l} side="bid" />)}
        </div>
        <div>
          <div style={{ color: '#4b5563', fontSize: 7, padding: '0 6px', marginBottom: 2 }}>ASKS</div>
          {asks.map((l, i) => <LevelRow key={i} level={l} side="ask" />)}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create `frontend/src/components/charts/ConvictionScatter.tsx`**

```typescript
'use client';
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';
import type { RankedSymbol } from '@/types/conviction';

interface Props {
  symbols: RankedSymbol[];
  width?: number;
  height?: number;
}

export function ConvictionScatter({ symbols, width = 400, height = 200 }: Props) {
  const data = symbols
    .filter((s) => s.cusum_c !== undefined)
    .map((s) => ({ x: s.cusum_c ?? 0, y: s.avg_conviction, name: s.symbol }));

  return (
    <ScatterChart width={width} height={height}
      margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
      <XAxis dataKey="x" type="number" name="CUSUM C"
        tick={{ fontSize: 8, fill: '#4b5563' }}
        label={{ value: 'CUSUM C →', position: 'insideBottom', offset: -4, fontSize: 8, fill: '#4b5563' }} />
      <YAxis dataKey="y" type="number" name="Conv"
        tick={{ fontSize: 8, fill: '#4b5563' }}
        domain={[0, 1]} />
      <Tooltip
        cursor={{ strokeDasharray: '3 3', stroke: '#1f2937' }}
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 9 }}
        formatter={(v: number, name: string) => [v.toFixed(3), name]}
      />
      <ReferenceLine y={0.6} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1} />
      <Scatter data={data} fill="#60a5fa" opacity={0.7} />
    </ScatterChart>
  );
}
```

- [ ] **Step 7: Create `frontend/src/components/charts/DeliveryTrendChart.tsx`**

```typescript
'use client';
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell } from 'recharts';
import type { TrendRow } from '@/types/conviction';

interface Props {
  rows: TrendRow[];
  firedays?: string[];  // trade_date strings where CUSUM fired
  width?: number;
  height?: number;
}

function convColor(score: number): string {
  if (score >= 0.75) return '#34d399';
  if (score >= 0.50) return '#1e4a2f';
  if (score >= 0.30) return '#1e3a5f';
  return '#1f2937';
}

export function DeliveryTrendChart({ rows, firedays = [], width = 420, height = 100 }: Props) {
  const sorted = [...rows].sort((a, b) =>
    a.trade_date < b.trade_date ? -1 : 1
  );

  return (
    <BarChart width={width} height={height} data={sorted}
      margin={{ top: 4, right: 4, bottom: 12, left: -20 }}>
      <XAxis dataKey="trade_date"
        tickFormatter={(v: string) => v.slice(5)}
        tick={{ fontSize: 7, fill: '#4b5563' }} />
      <YAxis domain={[0, 1]} tick={{ fontSize: 7, fill: '#4b5563' }} width={24} />
      <Tooltip
        contentStyle={{ background: '#111827', border: '1px solid #1f2937', fontSize: 9 }}
        formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, 'Delivery']}
      />
      <Bar dataKey="conviction_score" isAnimationActive={false}>
        {sorted.map((row) => (
          <Cell
            key={row.trade_date}
            fill={firedays.includes(row.trade_date) ? '#f87171' : convColor(row.conviction_score)}
          />
        ))}
      </Bar>
    </BarChart>
  );
}
```

- [ ] **Step 8: TypeScript check**

```bash
cd /app/frontend && npx tsc --noEmit
```

Expected: 0 new errors

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/charts/
git commit -m "feat(frontend): add Bloomberg-style chart components for orderflow + conviction"
```

---

## Task 8: Frontend — Order Flow Page

**Files:**
- Create: `frontend/src/app/dashboard/orderflow/page.tsx`

Context: Three-column layout (Watchlist | Drilldown+Depth | Detail). Mounts `useOrderFlowWS` once at page level. All data from `useOrderFlowStore`. CUSUM-fired symbols pinned to top of watchlist with red background.

- [ ] **Step 1: Create `frontend/src/app/dashboard/orderflow/page.tsx`**

```typescript
'use client';
import { useState, useMemo, useRef, useEffect } from 'react';
import { useOrderFlowStore } from '@/stores/orderflowStore';
import { useOrderFlowWS } from '@/hooks/useOrderFlowWS';
import { useMarketDepthWS } from '@/hooks/useMarketDepthWS';
import { AlphaAreaChart } from '@/components/charts/AlphaAreaChart';
import { HawkesLineChart } from '@/components/charts/HawkesLineChart';
import { CusumBar } from '@/components/charts/CusumBar';
import { AlphaHeatmap } from '@/components/charts/AlphaHeatmap';
import { DepthLadder } from '@/components/charts/DepthLadder';
import type { SymbolState } from '@/types/orderflow';

const BG = '#0a0a0f';
const PANEL_BG = '#0d1117';
const BORDER = '#1f2937';
const MONO = 'ui-monospace, "Geist Mono", monospace';

// Accumulate up to 200 ticks per symbol for sparklines
function useAlphaHistory(symbols: Record<string, SymbolState>, selectedSymbol: string | null) {
  const historyRef = useRef<Record<string, { ts_ms: number; alpha: number }[]>>({});
  const hawkesRef = useRef<Record<string, { ts_ms: number; lambda: number }[]>>({});

  if (selectedSymbol && symbols[selectedSymbol]) {
    const s = symbols[selectedSymbol];
    const ah = historyRef.current[selectedSymbol] ?? [];
    const last = ah[ah.length - 1];
    if (!last || last.ts_ms !== s.ts_ms) {
      historyRef.current[selectedSymbol] = [...ah, { ts_ms: s.ts_ms, alpha: s.alpha }].slice(-200);
      const hh = hawkesRef.current[selectedSymbol] ?? [];
      hawkesRef.current[selectedSymbol] = [...hh, { ts_ms: s.ts_ms, lambda: s.lambda_hawkes }].slice(-200);
    }
  }

  return {
    alphaHistory: selectedSymbol ? (historyRef.current[selectedSymbol] ?? []) : [],
    hawkesHistory: selectedSymbol ? (hawkesRef.current[selectedSymbol] ?? []) : [],
  };
}

type DrillTab = 'drilldown' | 'depth';

export default function OrderFlowPage() {
  useOrderFlowWS();
  const { symbols, watchlist, selectedSymbol, signalFeed, cusumFires,
          depthData, wsStatus, setSelectedSymbol } = useOrderFlowStore();
  const [drillTab, setDrillTab] = useState<DrillTab>('drilldown');

  useMarketDepthWS(drillTab === 'depth' ? selectedSymbol : null);

  const { alphaHistory, hawkesHistory } = useAlphaHistory(symbols, selectedSymbol);

  const sorted = useMemo(() => {
    const firedSet = new Set(cusumFires.slice(0, 20).map((f) => f.symbol));
    const fired = watchlist.filter((s) => firedSet.has(s));
    const rest = watchlist.filter((s) => !firedSet.has(s));
    return [...fired, ...rest];
  }, [watchlist, cusumFires]);

  const selected = selectedSymbol ? symbols[selectedSymbol] : null;
  const firedToday = cusumFires.filter((f) => selectedSymbol && f.symbol === selectedSymbol).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh',
      background: BG, fontFamily: MONO, color: '#9ca3af', overflow: 'hidden' }}>

      {/* Status Strip */}
      <div style={{ background: '#111827', borderBottom: `1px solid ${BORDER}`,
        padding: '4px 12px', display: 'flex', gap: 16, alignItems: 'center', flexShrink: 0 }}>
        <span style={{ color: wsStatus === 'connected' ? '#34d399' : '#f87171', fontSize: 9, fontWeight: 700 }}>
          ⬤ {wsStatus.toUpperCase()}
        </span>
        <span style={{ color: '#60a5fa', fontSize: 9 }}>{watchlist.length} SYMBOLS</span>
        <span style={{ color: '#f87171', fontSize: 9 }}>⚡ {cusumFires.length} FIRES TODAY</span>
        <span style={{ color: '#6b7280', fontSize: 9, marginLeft: 'auto' }}>
          ⚡ /dashboard/orderflow
        </span>
      </div>

      {/* Main 3-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr 220px',
        flex: 1, overflow: 'hidden', gap: 0 }}>

        {/* ── Watchlist ── */}
        <div style={{ borderRight: `1px solid ${BORDER}`, overflowY: 'auto', background: PANEL_BG }}>
          <div style={{ padding: '4px 8px', borderBottom: `1px solid ${BORDER}`,
            fontSize: 8, color: '#4b5563', fontWeight: 700, letterSpacing: '0.1em' }}>
            WATCHLIST ↑ α+λ/1e5
          </div>
          {sorted.map((sym) => {
            const s = symbols[sym];
            if (!s) return null;
            const fired = cusumFires.slice(0, 20).some((f) => f.symbol === sym);
            return (
              <div key={sym} onClick={() => setSelectedSymbol(sym)}
                style={{
                  padding: '4px 8px', cursor: 'pointer', borderBottom: `1px solid ${BORDER}`,
                  background: fired
                    ? 'rgba(248,113,113,0.10)'
                    : selectedSymbol === sym ? '#111827' : 'transparent',
                }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ fontSize: 10, fontWeight: 700,
                    color: fired ? '#f87171' : selectedSymbol === sym ? '#60a5fa' : '#9ca3af' }}>
                    {sym.replace('NSE_EQ|', '')}
                  </span>
                  <span style={{ fontSize: 9, color: s.alpha >= 0 ? '#34d399' : '#f87171' }}>
                    {s.alpha >= 0 ? '+' : ''}{s.alpha.toFixed(4)}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 8, color: '#f59e0b' }}>{s.lambda_hawkes.toFixed(0)} λ</span>
                  <span style={{ fontSize: 8, color: '#6b7280' }}>{s.cusum_c.toFixed(1)}/5.0</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Drilldown / Depth ── */}
        <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Tab bar */}
          <div style={{ display: 'flex', borderBottom: `1px solid ${BORDER}`, flexShrink: 0 }}>
            {(['drilldown', 'depth'] as DrillTab[]).map((tab) => (
              <button key={tab} onClick={() => setDrillTab(tab)}
                style={{
                  padding: '5px 14px', fontSize: 9, fontWeight: 700, cursor: 'pointer',
                  border: 'none', outline: 'none', fontFamily: MONO,
                  background: drillTab === tab ? BG : PANEL_BG,
                  color: drillTab === tab ? '#60a5fa' : '#6b7280',
                  borderBottom: drillTab === tab ? `2px solid #60a5fa` : '2px solid transparent',
                }}>
                {tab.toUpperCase()}
              </button>
            ))}
            {selectedSymbol && (
              <span style={{ marginLeft: 12, alignSelf: 'center', fontSize: 9,
                color: '#4b5563' }}>{selectedSymbol.replace('NSE_EQ|', '')}</span>
            )}
          </div>

          <div style={{ flex: 1, padding: 10, overflowY: 'auto', background: BG }}>
            {drillTab === 'drilldown' ? (
              <>
                {/* Alpha Chart */}
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 8, color: '#4b5563', marginBottom: 3 }}>KALMAN α — last 200 ticks</div>
                  <AlphaAreaChart data={alphaHistory} width={480} height={80} />
                </div>
                {/* Hawkes Chart */}
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 8, color: '#4b5563', marginBottom: 3 }}>HAWKES λ DECAY</div>
                  <HawkesLineChart data={hawkesHistory} width={480} height={60} />
                </div>
                {/* CUSUM Bar */}
                <div style={{ marginBottom: 12 }}>
                  <CusumBar
                    value={selected?.cusum_c ?? 0}
                    fired={selected?.cusum_fired ?? false}
                  />
                </div>
                {/* Heatmap */}
                <div>
                  <div style={{ fontSize: 8, color: '#4b5563', marginBottom: 4 }}>
                    α HEATMAP — {watchlist.length} symbols
                  </div>
                  <AlphaHeatmap
                    symbols={Object.values(symbols)}
                    onSelect={setSelectedSymbol}
                  />
                </div>
              </>
            ) : (
              <DepthLadder frame={depthData} />
            )}
          </div>
        </div>

        {/* ── Detail Panel ── */}
        <div style={{ borderLeft: `1px solid ${BORDER}`, background: PANEL_BG,
          padding: 10, overflowY: 'auto' }}>
          <div style={{ fontSize: 8, color: '#4b5563', fontWeight: 700,
            letterSpacing: '0.1em', marginBottom: 8 }}>
            {selected ? selected.symbol.replace('NSE_EQ|', '') : 'SELECT SYMBOL'}
          </div>
          {selected ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                { label: 'KALMAN α', value: selected.alpha.toFixed(5),
                  color: selected.alpha >= 0 ? '#34d399' : '#f87171' },
                { label: 'HAWKES λ', value: selected.lambda_hawkes.toFixed(0), color: '#f59e0b' },
                { label: 'CUSUM C', value: `${selected.cusum_c.toFixed(2)} / 5.0`,
                  color: selected.cusum_c > 4 ? '#f87171' : '#9ca3af' },
                { label: 'σ² VAR', value: selected.variance.toFixed(6), color: '#a78bfa' },
                { label: 'KYLE λ', value: selected.kyle_lambda.toFixed(4), color: '#60a5fa' },
                { label: 'q* SIZE', value: String(selected.q_star),
                  color: selected.q_star > 0 ? '#34d399' : '#6b7280' },
                { label: 'FIRES TODAY', value: String(firedToday),
                  color: firedToday > 0 ? '#f87171' : '#6b7280' },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ borderBottom: `1px solid ${BORDER}`, paddingBottom: 5 }}>
                  <div style={{ fontSize: 7, color: '#4b5563', marginBottom: 1 }}>{label}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color }}>{value}</div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ color: '#4b5563', fontSize: 9 }}>
              Click a symbol in the watchlist to see details
            </div>
          )}
        </div>
      </div>

      {/* Signal Ticker */}
      <div style={{ height: 22, background: '#111827', borderTop: `1px solid ${BORDER}`,
        overflow: 'hidden', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 24, animation: 'scroll 30s linear infinite',
          fontSize: 8, whiteSpace: 'nowrap', padding: '0 12px' }}>
          {signalFeed.map((e, i) => (
            <span key={i} style={{ color: e.side === 'FIRE' ? '#f87171' : e.side === 'BUY' ? '#34d399' : '#f87171' }}>
              {new Date(e.ts_ms).toTimeString().slice(0, 8)}{' '}
              {e.symbol.replace('NSE_EQ|', '')}{' '}
              {e.side === 'FIRE' ? '⚡ FIRE' : e.side}{' '}
              q*={e.q_star} α={e.alpha.toFixed(4)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: TypeScript + lint check**

```bash
cd /app/frontend && npx tsc --noEmit && npm run lint
```

Expected: 0 errors, 0 warnings

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/dashboard/orderflow/
git commit -m "feat(frontend): add Order Flow dashboard page (Bloomberg Layout C)"
```

---

## Task 9: Frontend — Conviction Page

**Files:**
- Create: `frontend/src/app/dashboard/conviction/page.tsx`

- [ ] **Step 1: Create `frontend/src/app/dashboard/conviction/page.tsx`**

```typescript
'use client';
import { useState } from 'react';
import { useConvictionStore } from '@/stores/convictionStore';
import { useConvictionSSE } from '@/hooks/useConvictionSSE';
import { useConvictionTrend } from '@/hooks/useConvictionTrend';
import { ConvictionScatter } from '@/components/charts/ConvictionScatter';
import { DeliveryTrendChart } from '@/components/charts/DeliveryTrendChart';
import type { RankedSymbol } from '@/types/conviction';

const BG = '#0a0a0f';
const PANEL_BG = '#0d1117';
const BORDER = '#1f2937';
const MONO = 'ui-monospace, "Geist Mono", monospace';

type ConvTab = 'selection' | 'correlation' | 'trend';

function ConvBar({ score }: { score: number }) {
  const pct = score * 100;
  const color = pct >= 70 ? '#34d399' : pct >= 50 ? '#60a5fa' : '#4b5563';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <div style={{ width: 60, height: 6, background: '#1f2937', borderRadius: 2 }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 9, color, fontFamily: MONO }}>{score.toFixed(2)}</span>
    </div>
  );
}

function SelectionTab({ symbols, onSelect, selectedSymbol }:
  { symbols: RankedSymbol[]; onSelect: (s: string) => void; selectedSymbol: string | null }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 9, fontFamily: MONO }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BORDER}` }}>
            {['#', 'SYMBOL', 'CONV SCORE (5d)', 'KALMAN α', 'HAWKES λ', 'CUSUM C', 'q*'].map(h => (
              <th key={h} style={{ padding: '4px 8px', color: '#4b5563', textAlign: 'left', fontWeight: 700 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((s, i) => {
            const fired = (s.cusum_c ?? 0) >= 5.0;
            return (
              <tr key={s.symbol} onClick={() => onSelect(s.symbol)}
                style={{
                  borderBottom: `1px solid ${BORDER}`, cursor: 'pointer',
                  background: fired ? 'rgba(248,113,113,0.07)'
                    : selectedSymbol === s.symbol ? '#111827' : 'transparent',
                }}>
                <td style={{ padding: '3px 8px', color: '#4b5563' }}>{i + 1}</td>
                <td style={{ padding: '3px 8px', color: fired ? '#f87171' : '#60a5fa', fontWeight: 700 }}>
                  {s.symbol.replace('NSE_EQ|', '')}
                  {fired && <span style={{ marginLeft: 4, fontSize: 7 }}>⚡</span>}
                </td>
                <td style={{ padding: '3px 8px' }}><ConvBar score={s.avg_conviction} /></td>
                <td style={{ padding: '3px 8px',
                  color: (s.alpha ?? 0) >= 0 ? '#34d399' : '#f87171' }}>
                  {s.alpha !== undefined ? `${s.alpha >= 0 ? '+' : ''}${s.alpha.toFixed(4)}` : '—'}
                </td>
                <td style={{ padding: '3px 8px', color: '#f59e0b' }}>
                  {s.lambda_hawkes?.toFixed(0) ?? '—'}
                </td>
                <td style={{ padding: '3px 8px', color: '#9ca3af' }}>
                  {s.cusum_c !== undefined ? `${s.cusum_c.toFixed(1)}/5.0` : '—'}
                </td>
                <td style={{ padding: '3px 8px', color: '#f59e0b', fontWeight: 700 }}>
                  {s.q_star ?? '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function ConvictionPage() {
  useConvictionSSE();
  const { rankedSymbols, sseStatus } = useConvictionStore();
  const [activeTab, setActiveTab] = useState<ConvTab>('selection');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const trendRows = useConvictionTrend(activeTab === 'trend' ? selectedSymbol : null);

  const tabs: { id: ConvTab; label: string }[] = [
    { id: 'selection', label: 'STOCK SELECTION' },
    { id: 'correlation', label: 'INTRADAY CORRELATION' },
    { id: 'trend', label: 'TREND' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh',
      background: BG, fontFamily: MONO, color: '#9ca3af', overflow: 'hidden' }}>

      {/* Status Strip */}
      <div style={{ background: '#111827', borderBottom: `1px solid ${BORDER}`,
        padding: '4px 12px', display: 'flex', gap: 16, alignItems: 'center', flexShrink: 0 }}>
        <span style={{ color: sseStatus === 'connected' ? '#34d399' : '#f87171', fontSize: 9, fontWeight: 700 }}>
          ⬤ SSE {sseStatus.toUpperCase()}
        </span>
        <span style={{ color: '#f59e0b', fontSize: 9 }}>◈ /dashboard/conviction</span>
        <span style={{ color: '#6b7280', fontSize: 9, marginLeft: 'auto' }}>
          {rankedSymbols.length} symbols ranked
        </span>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${BORDER}`, flexShrink: 0,
        background: PANEL_BG }}>
        {tabs.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '5px 16px', fontSize: 9, fontWeight: 700, cursor: 'pointer',
              border: 'none', outline: 'none', fontFamily: MONO,
              background: activeTab === tab.id ? BG : PANEL_BG,
              color: activeTab === tab.id ? '#f59e0b' : '#6b7280',
              borderBottom: activeTab === tab.id ? '2px solid #f59e0b' : '2px solid transparent',
            }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>

        {activeTab === 'selection' && (
          <SelectionTab
            symbols={rankedSymbols}
            onSelect={(s) => { setSelectedSymbol(s); }}
            selectedSymbol={selectedSymbol}
          />
        )}

        {activeTab === 'correlation' && (
          <div>
            <div style={{ fontSize: 9, color: '#4b5563', marginBottom: 8 }}>
              SCATTER: Today&apos;s CUSUM C (x) vs EOD Conviction Score (y) — {rankedSymbols.length} symbols
            </div>
            <ConvictionScatter symbols={rankedSymbols} width={560} height={220} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginTop: 12 }}>
              {[
                { label: 'SYMBOLS TRACKED', value: String(rankedSymbols.length), color: '#60a5fa' },
                { label: 'HIGH CONV (>0.6)', value: String(rankedSymbols.filter(s => s.avg_conviction > 0.6).length), color: '#34d399' },
                { label: 'AVG CONVICTION', value: rankedSymbols.length > 0
                  ? (rankedSymbols.reduce((s, r) => s + r.avg_conviction, 0) / rankedSymbols.length).toFixed(3)
                  : '—', color: '#f59e0b' },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ background: '#111827', border: `1px solid ${BORDER}`,
                  borderRadius: 3, padding: '8px 10px' }}>
                  <div style={{ fontSize: 7, color: '#4b5563', marginBottom: 2 }}>{label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color }}>{value}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'trend' && (
          <div>
            <div style={{ fontSize: 9, color: '#4b5563', marginBottom: 8 }}>
              {selectedSymbol
                ? `20-DAY DELIVERY TREND — ${selectedSymbol.replace('NSE_EQ|', '')}`
                : 'Click a symbol in Stock Selection to view its 20-day trend'}
            </div>
            {selectedSymbol && trendRows && trendRows.length > 0 && (
              <DeliveryTrendChart rows={trendRows} width={480} height={120} />
            )}
            {selectedSymbol && trendRows && trendRows.length === 0 && (
              <div style={{ color: '#4b5563', fontSize: 9 }}>No delivery data found for {selectedSymbol}</div>
            )}
            {selectedSymbol && trendRows === null && (
              <div style={{ color: '#4b5563', fontSize: 9 }}>Loading…</div>
            )}
            {!selectedSymbol && (
              <div style={{ color: '#4b5563', fontSize: 9 }}>
                Go to Stock Selection tab, click a symbol, then return here.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: TypeScript + lint check**

```bash
cd /app/frontend && npx tsc --noEmit && npm run lint
```

Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/dashboard/conviction/
git commit -m "feat(frontend): add EOD Conviction dashboard (3 tabs: selection, correlation, trend)"
```

---

## Task 10: Frontend — Dashboard Layout + Nav

**Files:**
- Create: `frontend/src/components/GlobalStatusBar.tsx`
- Create: `frontend/src/app/dashboard/layout.tsx`

Context: Add a persistent sidebar nav and global status bar to all `/dashboard/*` routes. The existing dashboard pages (`/live`, `/edge`, etc.) will inherit this layout.

- [ ] **Step 1: Create `frontend/src/components/GlobalStatusBar.tsx`**

```typescript
'use client';
import { useEffect, useState } from 'react';

const MONO = 'ui-monospace, "Geist Mono", monospace';

export function GlobalStatusBar() {
  const [time, setTime] = useState('');

  useEffect(() => {
    const tick = () => {
      setTime(
        new Date().toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour12: false,
        })
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{
      background: '#111827', borderBottom: '1px solid #1f2937',
      padding: '3px 12px', display: 'flex', gap: 16, alignItems: 'center',
      fontFamily: MONO, fontSize: 9, flexShrink: 0, zIndex: 10,
    }}>
      <span style={{ color: '#34d399', fontWeight: 700 }}>⬤ NSE</span>
      <span style={{ color: '#60a5fa' }}>KIRA</span>
      <span style={{ color: '#6b7280', marginLeft: 'auto' }}>{time} IST</span>
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/src/app/dashboard/layout.tsx`**

```typescript
import Link from 'next/link';
import { GlobalStatusBar } from '@/components/GlobalStatusBar';

const MONO = 'ui-monospace, "Geist Mono", monospace';
const SIDEBAR_BG = '#0d1117';
const BORDER = '#1f2937';

const NAV_ITEMS = [
  { href: '/', icon: '⌂', label: 'HOME' },
  { href: '/dashboard/live', icon: '◉', label: 'LIVE' },
  { href: '/dashboard/orderflow', icon: '⚡', label: 'FLOW', highlight: '#34d399' },
  { href: '/dashboard/conviction', icon: '◈', label: 'CONV', highlight: '#f59e0b' },
  { href: '/dashboard/edge', icon: '◇', label: 'EDGE' },
  { href: '/dashboard/options', icon: 'Ψ', label: 'OPT' },
  { href: '/dashboard/backtest', icon: '▶', label: 'TEST' },
  { href: '/ide', icon: '{}', label: 'IDE' },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <GlobalStatusBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Sidebar */}
        <nav style={{
          width: 52, background: SIDEBAR_BG, borderRight: `1px solid ${BORDER}`,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          padding: '8px 0', gap: 2, flexShrink: 0,
        }}>
          <div style={{ color: '#60a5fa', fontSize: 11, fontWeight: 900,
            marginBottom: 10, padding: 6, fontFamily: MONO }}>K</div>
          {NAV_ITEMS.map(({ href, icon, label, highlight }) => (
            <Link key={href} href={href} style={{ textDecoration: 'none' }}>
              <div style={{
                width: 38, padding: '6px 4px', borderRadius: 4, textAlign: 'center',
                cursor: 'pointer', fontFamily: MONO,
                background: highlight ? `rgba(${highlight === '#34d399' ? '52,211,153' : '245,158,11'},0.12)` : 'transparent',
                border: highlight ? `1px solid ${highlight}33` : '1px solid transparent',
              }}>
                <div style={{ fontSize: 14 }}>{icon}</div>
                <div style={{ fontSize: 7, marginTop: 1,
                  color: highlight ?? '#6b7280', fontWeight: highlight ? 700 : 400 }}>
                  {label}
                </div>
              </div>
            </Link>
          ))}
          <Link href="/settings" style={{ marginTop: 'auto', textDecoration: 'none' }}>
            <div style={{ width: 38, padding: '6px 4px', borderRadius: 4,
              textAlign: 'center', fontFamily: MONO }}>
              <div style={{ fontSize: 14 }}>⚙</div>
              <div style={{ fontSize: 7, color: '#6b7280' }}>SET</div>
            </div>
          </Link>
        </nav>
        {/* Page content */}
        <main style={{ flex: 1, overflow: 'hidden' }}>{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd /app/frontend && npx tsc --noEmit
```

Expected: 0 new errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/GlobalStatusBar.tsx \
        frontend/src/app/dashboard/layout.tsx
git commit -m "feat(frontend): add dashboard sidebar nav and global status bar"
```

---

## Task 11: Frontend — Existing Fixes

**Files:**
- Modify: `frontend/src/app/dashboard/live/page.tsx`
- Modify: `frontend/src/components/TradingDashboard.tsx`

### Fix 1: Replace 2s polling with WebSocket in live/page.tsx

The current code (line 154): `const interval = setInterval(pollStatus, 2000);`

The API Gateway now has `/ws/live` (Task 4) that pushes status every 1s.

- [ ] **Step 1: Replace the polling effect in `frontend/src/app/dashboard/live/page.tsx`**

Find the `useEffect` block that contains `setInterval(pollStatus, 2000)` and `setInterval` for trades (approximately lines 80–160). Replace both polling intervals with a single WebSocket effect:

```typescript
  // WebSocket for live status — replaces setInterval polling
  useEffect(() => {
    const API_HOST = process.env.NEXT_PUBLIC_API_HOST || 'localhost:8080';
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${proto}://${API_HOST}/ws/live`;
    let ws: WebSocket | null = null;
    let retryDelay = 1000;
    let cancelled = false;

    // Keep fetching trades via REST (low frequency, no need for WS)
    const fetchTrades = async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/live/trades`);
        if (res.ok) {
          const data = await res.json();
          setTrades(data);
        }
      } catch { /* ignore */ }
    };

    const tradesInterval = setInterval(fetchTrades, 10000); // every 10s is sufficient
    fetchTrades();

    function connect() {
      if (cancelled) return;
      ws = new WebSocket(wsUrl);
      ws.onopen = () => { retryDelay = 1000; };
      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          setStatus(data);
          setLoading(false);
        } catch { /* skip */ }
      };
      ws.onerror = () => ws?.close();
      ws.onclose = () => {
        if (cancelled) return;
        setTimeout(connect, Math.min(retryDelay, 30000) + Math.random() * 200);
        retryDelay *= 2;
      };
    }

    connect();
    return () => {
      cancelled = true;
      clearInterval(tradesInterval);
      ws?.close();
    };
  }, [API_URL]);
```

Also remove the old `pollStatus` function and the `useEffect` blocks that called `setInterval(pollStatus, 2000)` and the separate trades interval.

- [ ] **Step 2: TypeScript check on live page**

```bash
cd /app/frontend && npx tsc --noEmit
```

Expected: 0 new errors

### Fix 2: Remove mock data from TradingDashboard

- [ ] **Step 3: Replace mock data in `frontend/src/components/TradingDashboard.tsx`**

Remove the hardcoded `useState` initializers for `portfolio`, `positions`, and `orders`. Replace with API-fetched state:

```typescript
"use client";
import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ArrowUpRight, ArrowDownRight, DollarSign, Wallet, Activity } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

interface Portfolio {
  equity: number;
  pnl_daily: number;
  pnl_percent: number;
  cash: number;
  margin_used: number;
}

interface Position {
  symbol: string;
  qty: number;
  avg_price: number;
  ltp: number;
  pnl: number;
}

interface Order {
  id: string;
  time: string;
  symbol: string;
  type: string;
  qty: number;
  price: number;
  status: string;
}

const EMPTY_PORTFOLIO: Portfolio = {
  equity: 0, pnl_daily: 0, pnl_percent: 0, cash: 0, margin_used: 0,
};

export function TradingDashboard() {
  const [portfolio, setPortfolio] = useState<Portfolio>(EMPTY_PORTFOLIO);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/live/status`);
        if (res.ok) {
          const data = await res.json();
          if (data.equity !== undefined) {
            setPortfolio({
              equity: data.equity ?? 0,
              pnl_daily: data.pnl_daily ?? 0,
              pnl_percent: data.pnl_percent ?? 0,
              cash: data.cash ?? 0,
              margin_used: data.margin_used ?? 0,
            });
          }
          if (Array.isArray(data.holdings)) {
            setPositions(
              data.holdings.map((h: Record<string, unknown>) => ({
                symbol: String(h.symbol ?? ''),
                qty: Number(h.quantity ?? 0),
                avg_price: Number(h.avg_price ?? 0),
                ltp: Number(h.current_price ?? 0),
                pnl: Number(h.unrealized_pnl ?? 0),
              }))
            );
          }
        }
      } catch { /* API unavailable */ }

      try {
        const res = await fetch(`${API_URL}/api/v1/live/trades`);
        if (res.ok) {
          const data: Order[] = await res.json();
          setOrders(data);
        }
      } catch { /* ignore */ }
    };

    load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Equity</CardTitle>
            <Wallet className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">₹{portfolio.equity.toLocaleString()}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Daily P&amp;L</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${portfolio.pnl_daily >= 0 ? "text-green-500" : "text-red-500"}`}>
              {portfolio.pnl_daily >= 0 ? "+" : ""}₹{portfolio.pnl_daily.toLocaleString()}
            </div>
            <p className="text-xs text-muted-foreground flex items-center">
              {portfolio.pnl_percent >= 0 ? <ArrowUpRight className="h-4 w-4 mr-1" /> : <ArrowDownRight className="h-4 w-4 mr-1" />}
              {portfolio.pnl_percent.toFixed(2)}% today
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Margin Used</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">₹{portfolio.margin_used.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">Cash: ₹{portfolio.cash.toLocaleString()}</p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="positions" className="w-full">
        <TabsList>
          <TabsTrigger value="positions">Active Positions ({positions.length})</TabsTrigger>
          <TabsTrigger value="orders">Order History</TabsTrigger>
        </TabsList>
        <TabsContent value="positions">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead>Avg Price</TableHead>
                <TableHead>LTP</TableHead>
                <TableHead>P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p) => (
                <TableRow key={p.symbol}>
                  <TableCell className="font-mono text-sm">{p.symbol}</TableCell>
                  <TableCell>{p.qty}</TableCell>
                  <TableCell>₹{p.avg_price.toFixed(2)}</TableCell>
                  <TableCell>₹{p.ltp.toFixed(2)}</TableCell>
                  <TableCell className={p.pnl >= 0 ? "text-green-500" : "text-red-500"}>
                    {p.pnl >= 0 ? "+" : ""}₹{p.pnl.toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
              {positions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">No open positions</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TabsContent>
        <TabsContent value="orders">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.map((o, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-xs">{String(o.time)}</TableCell>
                  <TableCell className="font-mono text-sm">{o.symbol}</TableCell>
                  <TableCell>{o.type ?? (o as Record<string, unknown>).side}</TableCell>
                  <TableCell>{o.qty ?? (o as Record<string, unknown>).quantity}</TableCell>
                  <TableCell>₹{Number(o.price).toFixed(2)}</TableCell>
                  <TableCell>
                    <Badge variant={String(o.status) === 'FILLED' ? 'default' : 'secondary'}>
                      {String(o.status)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 4: Clear stale `.next/types` cache**

```bash
rm -rf /app/frontend/.next/types/app/dashboard/vektor
```

This removes the stale type declarations for the deleted vektor page that cause false TS errors.

- [ ] **Step 5: Final TypeScript + lint check**

```bash
cd /app/frontend && npx tsc --noEmit && npm run lint
```

Expected: 0 errors, 0 warnings

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/dashboard/live/page.tsx \
        frontend/src/components/TradingDashboard.tsx
git commit -m "fix(frontend): replace 2s polling with WebSocket in live page, remove mock data from TradingDashboard"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Order Flow dashboard (Layout C, Bloomberg, watchlist, drilldown, depth tab) → Tasks 7–8
- ✅ Upstox V3 depth (dynamic levels from `depth_levels` field, never hardcoded) → Tasks 3, 7
- ✅ Free tier rate limits (single WS connection, no per-tick REST, Redis cache) → Tasks 1–4
- ✅ EOD Conviction dashboard (3 tabs) → Task 9
- ✅ SSE for conviction → Tasks 4, 6, 9
- ✅ REST trend endpoint with Redis cache → Task 4
- ✅ Zustand stores → Task 5
- ✅ WebSocket hooks with exponential backoff → Task 6
- ✅ Global status bar + sidebar nav → Task 10
- ✅ Live page polling fix → Task 11
- ✅ TradingDashboard mock data removal → Task 11
- ✅ TypeScript `any` elimination → addressed throughout (explicit types in all new files)

**Type consistency check:** `SymbolState`, `DepthFrame`, `DepthLevel`, `SignalEvent`, `CusumFire`, `WsStatus` defined in Task 5 types, used consistently in hooks (Task 6), charts (Task 7), and pages (Tasks 8–9). `RankedSymbol`, `TrendRow`, `CorrelationStats` defined in Task 5 and used in conviction components.

**No placeholders found.**

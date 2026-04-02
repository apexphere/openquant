# OpenQuant MCP Server — Interface Specification

**Transport:** stdio
**Invocation:** `python -m openquant_mcp`
**Upstream:** jesse server on `localhost:{JESSE_PORT}` (default `9000`)
**Auth:** `POST /auth/login` with password from env `PASSWORD` (default `openquant123`)

---

## 1. MCP Tools

### 1.1 `backtest`

Run a strategy backtest. Writes trade-level data to disk (NOT returned through Claude). Returns summary only.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `strategy` | string | yes | — | Strategy class name (e.g. `RegimeRouterV2`) |
| `symbol` | string | no | `BTC-USDT` | Trading pair |
| `timeframe` | string | no | `15m` | Candle timeframe |
| `start` | string | yes | — | Start date `YYYY-MM-DD` |
| `finish` | string | yes | — | Finish date `YYYY-MM-DD` |
| `session_id` | string | yes | — | Caller-generated unique ID for result filename |

**Behavior:**

1. Authenticate with jesse server
2. `POST /backtest` with session payload (exchange defaults to `Bybit USDT Perpetual`, balance `10000`, fee `0.00055`, warmup `210`, data_routes auto-include `1D` and `4h`)
3. Poll `POST /backtest/sessions/{session_id}` every 3s until `status` is `finished`, `stopped`, or `terminated` (timeout: 600s)
4. Fetch full session via `POST /backtest/sessions/{session_id}`
5. Transform trades per field mapping (Section 2)
6. Write result file to `~/.trading-harness/backtest-results/{session_id}.json` (schema in Section 3)
7. Return summary only

**Returns:**

```json
{
  "session_id": "abc-123",
  "total_trades": 42,
  "sharpe": 1.85,
  "pnl": 12.34,
  "win_rate": 0.62,
  "max_drawdown": -8.5,
  "result_file": "/Users/me/.trading-harness/backtest-results/abc-123.json"
}
```

**Error cases:** see Section 4.

---

### 1.2 `results`

List recent sessions or fetch a specific session's metrics.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `session_id` | string | no | — | If omitted, lists recent sessions |

**Without `session_id` — list mode:**

Returns array of up to 10 recent sessions.

```json
[
  {
    "id": "abc-123",
    "status": "finished",
    "strategy": "RegimeRouterV2",
    "pnl": 12.34,
    "created_at": 1711929600000
  }
]
```

Fields per session: `id` (string), `status` (string), `strategy` (string, extracted from `state.form.routes[0].strategy` or `strategy_name`), `pnl` (float, from `net_profit_percentage`), `created_at` (int, ms timestamp).

**With `session_id` — detail mode:**

Returns full session metrics.

```json
{
  "session_id": "abc-123",
  "status": "finished",
  "metrics": {
    "total_trades": 42,
    "sharpe": 1.85,
    "win_rate": 0.62,
    "max_drawdown": -8.5,
    "pnl": 12.34,
    "annual_return": 28.5,
    "sortino_ratio": 2.1,
    "calmar_ratio": 3.4,
    "profit_factor": 1.8,
    "expectancy_percentage": 0.29,
    "longs_count": 30,
    "shorts_count": 12
  },
  "regime_periods": [
    {
      "start": 1719792000000,
      "end": 1722470400000,
      "regime": "bullish"
    }
  ],
  "trade_count": 42
}
```

**Error:** `"Session not found: {session_id}"` if the session does not exist.

---

### 1.3 `optimize`

Run parameter optimization with training/testing split.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `strategy` | string | yes | — | Strategy class name |
| `symbol` | string | no | `BTC-USDT` | Trading pair |
| `timeframe` | string | no | `15m` | Candle timeframe |
| `training_start` | string | yes | — | Training period start `YYYY-MM-DD` |
| `training_finish` | string | yes | — | Training period finish `YYYY-MM-DD` |
| `testing_start` | string | yes | — | Testing period start `YYYY-MM-DD` |
| `testing_finish` | string | yes | — | Testing period finish `YYYY-MM-DD` |
| `trials` | int | no | `100` | Number of optimization trials |
| `objective` | string | no | `sharpe` | Objective function: `sharpe`, `sortino`, or `calmar` |

**Behavior:**

1. Authenticate with jesse server
2. `POST /optimization` with payload (exchange `Bybit USDT Perpetual`, balance `10000`, fee `0.001`, warmup `210`, cpu_cores `4`)
3. Optimization runs asynchronously. Return immediately after submission with the session ID.
4. Caller can poll via `results` tool to check status.

**Returns:**

```json
{
  "session_id": "opt-456",
  "status": "started",
  "message": "Optimization submitted. Poll with results tool or check dashboard."
}
```

Note: Optimization can take minutes to hours. The MCP server does NOT block waiting for completion. Results are viewable in the dashboard at `localhost:9000` or via `POST /optimization/sessions/{session_id}`.

---

### 1.4 `write_strategy`

Write or overwrite a strategy file.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | — | Strategy class name (e.g. `MyStrategy`) |
| `code` | string | yes | — | Full Python source code |

**Behavior:**

1. Create directory `strategies/{name}/` if it doesn't exist
2. Write `code` to `strategies/{name}/__init__.py`
3. Return confirmation

**Returns:**

```json
{
  "status": "ok",
  "file_path": "strategies/MyStrategy/__init__.py"
}
```

**Validation:** The `name` param must be a valid Python identifier (alphanumeric + underscore, no path traversal). Reject names containing `/`, `..`, or whitespace.

**Error:** `"Invalid strategy name: {name}"` for invalid names.

---

### 1.5 `read_strategy`

Read a strategy's source code.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | — | Strategy class name |

**Returns:**

```json
{
  "name": "RegimeRouterV2",
  "code": "from openquant.strategies import Strategy\n..."
}
```

**Error:** `"Strategy not found: {name}"` if `strategies/{name}/__init__.py` does not exist.

---

### 1.6 `list_strategies`

List all available strategy names.

No parameters.

**Returns:**

```json
{
  "strategies": ["BBMeanReversion", "RegimeRouter", "RegimeRouterV2", "TrendBreak", "VolSqueeze"]
}
```

**Behavior:** List subdirectories of `strategies/` that contain an `__init__.py` file. Exclude non-strategy files (e.g. `PLAYBOOK.md`). Sort alphabetically.

---

### 1.7 `detector_preview`

Preview regime labels for a detector over a date range.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `detector_type` | string | yes | — | Detector name (e.g. `supertrend_v5`) |
| `symbol` | string | no | `BTC-USDT` | Trading pair |
| `start` | string | yes | — | Start date `YYYY-MM-DD` |
| `finish` | string | yes | — | Finish date `YYYY-MM-DD` |
| `params` | object | no | `{}` | Override detector parameters |

**Behavior:**

1. Authenticate with jesse server
2. `POST /detector-optimization/preview` with `{detector_type, params, exchange, symbol, start_date, finish_date}`
3. Return regime periods

**Returns:**

```json
{
  "detector_type": "supertrend_v5",
  "regime_periods": [
    {
      "regime": "bullish",
      "start_date": "2025-06-15",
      "end_date": "2025-08-20",
      "days": 66,
      "start_price": 65000.0,
      "end_price": 72000.0,
      "pct_change": 10.8
    }
  ]
}
```

**Error:** `"Server not running"` if connection refused. `"Detector error: {message}"` if the server returns an error.

---

## 2. Field Mapping Contract

### 2.1 Trade Fields

jesse `ClosedTrade.to_dict_with_orders` produces the source fields. The MCP server transforms them for the harness result file.

| jesse field | harness field | transform |
|---|---|---|
| `id` | `id` | pass-through (UUID string) |
| `opened_at` | `entry_timestamp` | pass-through (already ms, BigIntegerField) |
| `closed_at` | `exit_timestamp` | pass-through (already ms, BigIntegerField) |
| `symbol` | `symbol` | pass-through |
| `type` | `side` | rename only — values are `"long"` or `"short"` |
| `entry_price` | `entry_price` | pass-through (float) |
| `exit_price` | `exit_price` | pass-through (float) |
| `qty` | `qty` | pass-through (float) |
| `PNL` | `pnl` | rename (float, net of fees) |
| `PNL_percentage` | `pnl_pct` | rename (float, percentage) |
| `fee` | `fee` | pass-through (float) |
| _(none)_ | `slippage` | hardcode `0.0` |
| `exit_trace.regime_at_exit` | `regime` | extract from nested dict, default `"_unlabeled"` if missing |

### 2.2 Summary Metrics

| jesse metric (from `session.metrics`) | harness field | transform |
|---|---|---|
| `sharpe_ratio` | `sharpe` | rename (float) |
| `win_rate` | `win_rate` | rename (float, 0.0–1.0) |
| `max_drawdown` | `max_drawdown` | rename (float, negative percentage) |
| `total` | `total_trades` | rename (int) |
| `net_profit_percentage` | `pnl` | rename (float, percentage) |

---

## 3. Backtest Result File Schema

Written to `~/.trading-harness/backtest-results/{session_id}.json`.

The MCP server MUST create the directory `~/.trading-harness/backtest-results/` if it does not exist.

```json
{
  "session_id": "string (UUID)",
  "strategy": "string",
  "symbol": "string",
  "timeframe": "string",
  "start": "string (YYYY-MM-DD)",
  "finish": "string (YYYY-MM-DD)",
  "summary": {
    "total_trades": "int",
    "sharpe": "float",
    "win_rate": "float (0.0-1.0)",
    "max_drawdown": "float (negative %)",
    "pnl": "float (%)"
  },
  "trades": [
    {
      "id": "string (UUID)",
      "entry_timestamp": "int (Unix ms)",
      "exit_timestamp": "int (Unix ms)",
      "symbol": "string",
      "side": "string (long|short)",
      "entry_price": "float",
      "exit_price": "float",
      "qty": "float",
      "pnl": "float",
      "pnl_pct": "float",
      "fee": "float",
      "slippage": 0.0,
      "regime": "string"
    }
  ],
  "regime_periods": [
    {
      "start": "int (Unix ms)",
      "end": "int (Unix ms)",
      "regime": "string"
    }
  ]
}
```

### Constraints

- `session_id` MUST match the `session_id` param passed to the `backtest` tool
- `total_trades` MUST equal `len(trades)`
- All timestamps MUST be Unix milliseconds (>= 1e12)
- `entry_timestamp < exit_timestamp` for every trade
- `side` MUST be `"long"` or `"short"`
- `regime` defaults to `"_unlabeled"` when `exit_trace` is missing or `regime_at_exit` is null
- `slippage` is always `0.0` (backtest has no slippage)
- File encoding: UTF-8, no BOM

---

## 4. Error Response Contract

All errors are returned as MCP tool errors with a descriptive string. The MCP server MUST NOT raise unhandled exceptions.

| Failure Mode | Error String | When |
|---|---|---|
| Server not running | `"Server not running. Start with: jesse run"` | Connection refused on `localhost:{port}` |
| Authentication failed | `"Authentication failed: invalid password"` | `/auth/login` returns non-200 |
| Backtest timeout | `"Backtest timed out after 600s"` | Poll loop exceeds 600s |
| Optimization timeout | _(N/A — optimize returns immediately)_ | — |
| Session not found | `"Session not found: {session_id}"` | `/backtest/sessions/{id}` returns empty |
| Strategy not found | `"Strategy not found: {name}"` | `strategies/{name}/__init__.py` missing |
| Invalid strategy name | `"Invalid strategy name: {name}"` | Name contains `/`, `..`, whitespace, or non-identifier chars |
| Invalid params | `"Invalid parameter: {detail}"` | Missing required param, wrong type, bad date format |
| Backtest failed | `"Backtest failed: {exception}"` | Session status is `stopped` with exception |
| Detector error | `"Detector error: {message}"` | Server returns error for detector preview |
| File write error | `"Failed to write result file: {detail}"` | Disk error writing to `~/.trading-harness/` |

---

## 5. Resolved Questions

1. **`jesse results --json-output`** — Returns full session JSON including `metrics`, `trades` array (with `to_dict_with_orders` fields: `id`, `type`, `entry_price`, `exit_price`, `qty`, `PNL`, `PNL_percentage`, `fee`, `opened_at`, `closed_at`, `entry_trace`, `exit_trace`), and `regime_periods`.

2. **Timestamps** — All `opened_at` / `closed_at` are Unix milliseconds. The model uses `BigIntegerField`. Jesse helpers multiply by 1000 internally.

3. **Regime on trades** — Available via `exit_trace.regime_at_exit` (set in `closed_trade_service._build_exit_trace`). At session level, `regime_periods` is a top-level field on the session object.

4. **`jesse optimize`** — Async. `POST /optimization` returns 202 immediately. Results stored in `OptimizationSession` with `best_trials` containing `trial`, `params`, `fitness`, `dna`, `training_metrics`, `testing_metrics` per candidate. Requires four separate date params: `training_start_date`, `training_finish_date`, `testing_start_date`, `testing_finish_date`.

5. **`write_strategy`** — Writes to `strategies/{name}/__init__.py`. Directory is created if missing. Overwrite is safe — the file is not imported until a backtest references the strategy name.

---

## 6. MCP Client Configuration

```json
{
  "mcpServers": {
    "openquant": {
      "command": "python",
      "args": ["-m", "openquant_mcp"],
      "env": {
        "JESSE_PORT": "9000"
      }
    }
  }
}
```

The server reads `JESSE_PORT` from environment (default `9000`). The password is read from the jesse `.env` file via `openquant.services.env.ENV_VALUES['PASSWORD']` (default `openquant123`).

---

## 7. Implementation Notes for Dev

- **HTTP client:** All jesse API calls use `POST` (even reads). Auth token goes in `Authorization` header (no `Bearer` prefix).
- **Polling:** Backtest poll interval 3s, timeout 600s. Check `session.status` for `finished` / `stopped` / `terminated`.
- **Result file directory:** `Path.home() / ".trading-harness" / "backtest-results"` — create with `mkdir(parents=True, exist_ok=True)`.
- **Strategy directory:** Relative to CWD — `Path("strategies")`. This assumes the MCP server is launched from the openquant project root.
- **JSON serialization:** Use `default=str` to handle UUIDs. Clean NaN/Inf values before writing (jesse already does this for API responses).

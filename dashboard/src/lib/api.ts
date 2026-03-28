import type {
  BacktestSession,
  BacktestSessionDetail,
  ChartData,
  OptimizationSession,
  CandleExisting,
} from "./types";

const API_BASE = "http://localhost:9000";

// Read auth token from environment or fallback
const AUTH_TOKEN = process.env.NEXT_PUBLIC_OPENQUANT_TOKEN ?? "";

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(AUTH_TOKEN ? { Authorization: AUTH_TOKEN } : {}),
    ...(options.headers as Record<string, string> ?? {}),
  };

  const res = await fetch(url, { ...options, headers });

  if (!res.ok) {
    if (res.status === 401) throw new Error("AUTH_FAILED");
    if (res.status === 404) throw new Error("NOT_FOUND");
    throw new Error(`API_ERROR: ${res.status}`);
  }

  // CORS detection: opaque response
  if (res.type === "opaque") {
    throw new Error("CORS_ERROR");
  }

  return res.json();
}

export async function fetchSessions(): Promise<BacktestSession[]> {
  const data = await apiFetch<{ sessions: BacktestSession[] }>(
    "/backtest/sessions",
    { method: "POST", body: JSON.stringify({}) }
  );
  return data.sessions ?? [];
}

export async function fetchSession(
  id: string
): Promise<BacktestSessionDetail> {
  const data = await apiFetch<{ session: BacktestSessionDetail }>(
    `/backtest/sessions/${id}`,
    { method: "POST", body: JSON.stringify({}) }
  );
  return data.session;
}

export async function fetchChartData(
  id: string
): Promise<ChartData | null> {
  const data = await apiFetch<{ chart_data: ChartData | null }>(
    `/backtest/sessions/${id}/chart-data`,
    { method: "POST", body: JSON.stringify({}) }
  );
  return data.chart_data;
}

export async function fetchOptimizationSessions(): Promise<
  OptimizationSession[]
> {
  const data = await apiFetch<{ sessions: OptimizationSession[] }>(
    "/optimization/sessions",
    { method: "POST", body: JSON.stringify({}) }
  );
  return data.sessions ?? [];
}

export async function fetchOptimizationSession(
  id: string
): Promise<OptimizationSession> {
  const data = await apiFetch<{ session: OptimizationSession }>(
    `/optimization/sessions/${id}`,
    { method: "POST", body: JSON.stringify({}) }
  );
  return data.session;
}

export async function fetchCandlesExisting(): Promise<CandleExisting[]> {
  const data = await apiFetch<{ data: CandleExisting[] }>(
    "/candles/existing",
    { method: "POST", body: JSON.stringify({}) }
  );
  return data.data ?? [];
}

export async function runBacktest(params: {
  exchange: string;
  routes: Array<{ symbol: string; timeframe: string; strategy: string }>;
  data_routes: Array<{ symbol: string; timeframe: string }>;
  start_date: string;
  finish_date: string;
  hyperparameters?: Record<string, any>;
}): Promise<{ message: string }> {
  const id = crypto.randomUUID();
  return apiFetch("/backtest", {
    method: "POST",
    body: JSON.stringify({
      id,
      exchange: params.exchange,
      routes: params.routes,
      data_routes: params.data_routes,
      config: {},
      start_date: params.start_date,
      finish_date: params.finish_date,
      debug_mode: false,
      export_csv: false,
      export_json: false,
      export_chart: true,
      export_tradingview: false,
      fast_mode: false,
      benchmark: true,
      hyperparameters: params.hyperparameters ?? null,
    }),
  });
}

export async function fetchSystemInfo(): Promise<{
  has_live: boolean;
  is_initiated: boolean;
}> {
  return apiFetch("/system/general-info", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

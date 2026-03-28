"use client";
import useSWR from "swr";
import {
  fetchSessions,
  fetchSession,
  fetchChartData,
} from "@/lib/api";

export function useBacktestSessions() {
  return useSWR("backtest-sessions", fetchSessions, {
    refreshInterval: 0,
    revalidateOnFocus: false,
  });
}

export function useBacktestSession(id: string | null) {
  return useSWR(
    id ? `backtest-session-${id}` : null,
    () => (id ? fetchSession(id) : null),
    { revalidateOnFocus: false }
  );
}

export function useChartData(id: string | null) {
  return useSWR(
    id ? `chart-data-${id}` : null,
    () => (id ? fetchChartData(id) : null),
    { revalidateOnFocus: false }
  );
}

"use client";
import useSWR from "swr";
import {
  fetchOptimizationSessions,
  fetchOptimizationSession,
} from "@/lib/api";

export function useOptimizationSessions() {
  return useSWR("optimization-sessions", fetchOptimizationSessions, {
    refreshInterval: 0,
    revalidateOnFocus: false,
  });
}

export function useOptimizationSession(id: string | null) {
  return useSWR(
    id ? `optimization-session-${id}` : null,
    () => (id ? fetchOptimizationSession(id) : null),
    { revalidateOnFocus: false }
  );
}

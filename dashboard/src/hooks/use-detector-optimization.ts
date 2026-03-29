"use client";
import useSWR from "swr";
import {
  fetchDetectorOptimizationSessions,
  fetchDetectorOptimizationSession,
} from "@/lib/api";

export function useDetectorOptimizationSessions() {
  return useSWR(
    "detector-optimization-sessions",
    fetchDetectorOptimizationSessions,
    { refreshInterval: 10000, revalidateOnFocus: true }
  );
}

export function useDetectorOptimizationSession(studyName: string | null) {
  return useSWR(
    studyName ? `detector-optimization-session-${studyName}` : null,
    () => (studyName ? fetchDetectorOptimizationSession(studyName) : null),
    { refreshInterval: 10000, revalidateOnFocus: true }
  );
}

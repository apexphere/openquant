import useSWR from "swr";
import {
  fetchResearchNotesBySession,
  fetchResearchNotesByStrategy,
  fetchStrategiesWithNotes,
} from "@/lib/api";

export function useSessionResearchNotes(sessionId: string | null) {
  return useSWR(
    sessionId ? `research-notes-session-${sessionId}` : null,
    () => (sessionId ? fetchResearchNotesBySession(sessionId) : null),
    { revalidateOnFocus: false }
  );
}

export function useStrategyResearchNotes(strategyName: string | null) {
  return useSWR(
    strategyName ? `research-notes-strategy-${strategyName}` : null,
    () => (strategyName ? fetchResearchNotesByStrategy(strategyName) : null),
    { revalidateOnFocus: false }
  );
}

export function useStrategiesWithNotes() {
  return useSWR("strategies-with-notes", fetchStrategiesWithNotes, {
    revalidateOnFocus: false,
  });
}

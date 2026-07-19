"use client";

import { useEffect, useReducer, useState } from "react";

import {
  eventStreamUrl,
  initialInvestigationEventState,
  parseInvestigationEvent,
  reduceInvestigationEvent,
} from "@/lib/investigation-events";

export function useInvestigationEvents(ticketId: string | null) {
  const [state, dispatch] = useReducer(
    reduceInvestigationEvent,
    ticketId ?? "",
    initialInvestigationEventState,
  );
  const [connection, setConnection] = useState<
    "IDLE" | "CONNECTING" | "OPEN" | "CLOSED" | "ERROR"
  >(ticketId ? "CONNECTING" : "IDLE");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticketId) return;
    const source = new EventSource(eventStreamUrl(ticketId));

    source.onopen = () => {
      setConnection("OPEN");
      setError(null);
    };
    source.addEventListener("investigation", (message) => {
      try {
        const event = parseInvestigationEvent((message as MessageEvent<string>).data);
        dispatch(event);
      } catch (eventError) {
        setError(eventError instanceof Error ? eventError.message : "Invalid SSE event");
      }
    });
    source.addEventListener("stream_end", () => {
      source.close();
      setConnection("CLOSED");
    });
    source.onerror = () => {
      setConnection("ERROR");
      setError("Mất kết nối event stream; trình duyệt sẽ tự kết nối lại.");
    };
    return () => source.close();
  }, [ticketId]);

  return { state, connection, error };
}

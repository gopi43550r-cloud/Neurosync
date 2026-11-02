import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { InvestigationEvent, InvestigationProgress } from "../api/types";

const EVENT_TYPES = [
  "investigation_started",
  "agent_selected",
  "document_processed",
  "claim_extracted",
  "conflict_detected",
  "hypothesis_generated",
  "evidence_evaluated",
  "hypothesis_verified",
  "conclusion_reached",
  "iteration_completed",
  "investigation_paused",
  "investigation_resumed",
  "investigation_completed",
  "investigation_cancelled",
  "human_review_requested",
  "evidence_added",
  "hypothesis_updated",
  "reevaluation_scheduled",
];

export type StreamState = "connecting" | "open" | "reconnecting" | "ended" | "error";

const MAX_BUFFER = 500;
const BACKFILL_PAGE_SIZE = 100;

/**
 * Subscribes to an investigation's live progress stream.
 *
 * Reliability notes:
 * - The panel is **seeded from the persisted event log** via the blackboard
 *   events endpoint, so it is populated immediately and survives reloads even
 *   before the stream connects.
 * - Events are **de-duplicated by id**, so reconnection (which replays from the
 *   server's `Last-Event-ID`) or backfill/live overlap never double-renders.
 * - The browser's `EventSource` reconnects automatically; we surface that as a
 *   `reconnecting` state. Progress comes from authoritative `progress` frames
 *   emitted by the server (real backend state), not a client-side simulation.
 */
export function useInvestigationEvents(
  investigationId: number | null,
  onEvent?: (event: InvestigationEvent) => void
) {
  const [events, setEvents] = useState<InvestigationEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const [progress, setProgress] = useState<InvestigationProgress | null>(null);
  const [reconnectKey, setReconnectKey] = useState(0);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const seenRef = useRef<Set<number>>(new Set());

  const mergeEvents = useCallback((incoming: InvestigationEvent[]) => {
    const fresh = incoming.filter((e) => typeof e.id === "number" && !seenRef.current.has(e.id));
    if (fresh.length === 0) return;
    fresh.forEach((e) => seenRef.current.add(e.id));
    setEvents((prev) => [...prev, ...fresh].sort((a, b) => a.id - b.id).slice(-MAX_BUFFER));
  }, []);

  const reconnect = useCallback(() => setReconnectKey((k) => k + 1), []);

  useEffect(() => {
    if (investigationId == null) return;
    let disposed = false;
    seenRef.current = new Set();
    setEvents([]);
    setProgress(null);
    setState("connecting");

    // 1. Seed from the persisted event log (also acts as a fallback source).
    api
      .blackboardEvents({ investigation_id: investigationId, page_size: BACKFILL_PAGE_SIZE })
      .then((page) => {
        if (disposed) return;
        const ordered = (page.items as unknown as InvestigationEvent[]).sort(
          (a, b) => a.id - b.id
        );
        ordered.forEach((e) => seenRef.current.add(e.id));
        setEvents(ordered.slice(-MAX_BUFFER));
      })
      .catch(() => {
        /* the live stream will still populate the panel */
      });

    // 2. Live stream.
    const source = new EventSource(api.eventsUrl(investigationId));

    const handle = (raw: MessageEvent) => {
      try {
        const event = JSON.parse(raw.data) as InvestigationEvent;
        mergeEvents([event]);
        handlerRef.current?.(event);
      } catch {
        /* ignore malformed frames */
      }
    };

    EVENT_TYPES.forEach((type) => source.addEventListener(type, handle as EventListener));
    source.addEventListener("progress", (raw) => {
      try {
        setProgress(JSON.parse((raw as MessageEvent).data) as InvestigationProgress);
      } catch {
        /* ignore */
      }
    });
    source.addEventListener("stream_error", () => {
      setState("error");
      source.close();
    });
    source.addEventListener("stream_end", () => {
      setState("ended");
      source.close();
    });
    source.onopen = () => setState("open");
    source.onerror = () => {
      // EventSource reconnects on its own unless we closed it: distinguish a
      // transient drop (reconnecting) from a permanent failure (error/ended).
      if (source.readyState === EventSource.CLOSED) {
        setState((prev) => (prev === "ended" ? "ended" : "error"));
      } else {
        setState("reconnecting");
      }
    };

    return () => {
      disposed = true;
      source.close();
    };
  }, [investigationId, reconnectKey, mergeEvents]);

  return { events, state, progress, reconnect };
}

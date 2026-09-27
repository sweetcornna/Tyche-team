import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, subscribeRun } from "../../api/client";
import type { ExperimentEvent, RunDetail, RunEvent, StageInfo } from "../../api/types";
import { useStore } from "../../lib/store";

export interface RunData {
  detail: RunDetail | undefined;
  error: ApiError | undefined;
  events: RunEvent[];
  experimentEvents: ExperimentEvent[];
  connected: boolean;
  reload: () => void;
}

const stageKey = (stages: StageInfo[]) => stages.map((s) => `${s.name}:${s.status}`).join("|");

/** Live view of one run: detail + events, kept current by the SSE stream. */
export function useRun(id: string): RunData {
  const { upsertRun } = useStore();
  const [detail, setDetail] = useState<RunDetail>();
  const [error, setError] = useState<ApiError>();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [experimentEvents, setExperimentEvents] = useState<ExperimentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [nonce, setNonce] = useState(0);
  const lastStages = useRef("");
  const refetchTimer = useRef<number>();

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  // Full detail (plan, review, paper, usage) — refetched when stages change.
  useEffect(() => {
    let cancelled = false;
    api
      .run(id)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        setError(undefined);
        lastStages.current = stageKey(d.stages);
      })
      .catch((e: ApiError) => !cancelled && setError(e));
    return () => {
      cancelled = true;
    };
  }, [id, nonce]);

  // Event history, then live stream.
  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | undefined;
    setEvents([]);
    setExperimentEvents([]);
    setConnected(false);
    api
      .events(id, 0, 5000)
      .then(({ events: history, next }) => {
        if (cancelled) return;
        setEvents(history);
        unsubscribe = subscribeRun(id, next, {
          status: setConnected,
          event: (e) => setEvents((all) => (all.some((x) => x.seq === e.seq) ? all : [...all, e])),
          experiment: (e) => setExperimentEvents((all) => [...all.slice(-400), e]),
          summary: (s) => {
            setDetail((d) => (d ? { ...d, ...s, stages: s.stages ?? d.stages } : d));
            upsertRun(s);
            const key = stageKey(s.stages ?? []);
            if (key !== lastStages.current) {
              lastStages.current = key;
              window.clearTimeout(refetchTimer.current);
              refetchTimer.current = window.setTimeout(reload, 400);
            }
          },
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      unsubscribe?.();
      window.clearTimeout(refetchTimer.current);
    };
  }, [id, reload, upsertRun]);

  return { detail, error, events, experimentEvents, connected, reload };
}

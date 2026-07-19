"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  InvestigationControlApiError,
  investigationControlApi,
  type ControlSummary,
  type InvestigationRun,
  type RunMode,
  type SoftPromptConfiguration,
} from "@/lib/investigation-control";

/** Poll queue stats (Pending / Checking / Reject / Approve) while the app is open. */
const SUMMARY_POLL_MS = 5_000;
/** Faster poll while a batch run is PENDING/RUNNING. */
const ACTIVE_RUN_POLL_MS = 2_000;
const ACTIVE_STATUSES = new Set(["PENDING", "RUNNING"]);

function messageFor(error: unknown): string {
  if (error instanceof InvestigationControlApiError) return error.message;
  return "Không thể tải trạng thái investigation. Vui lòng thử lại.";
}

export interface InvestigationControlState {
  summary: ControlSummary | null;
  runs: InvestigationRun[];
  configuration: SoftPromptConfiguration | null;
  isLoading: boolean;
  isMutating: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setMode: (mode: RunMode) => Promise<boolean>;
  startManualRun: () => Promise<boolean>;
  saveSoftPrompt: (value: string) => Promise<boolean>;
  resetSoftPrompt: () => Promise<boolean>;
  clearError: () => void;
}

export function useInvestigationControl(): InvestigationControlState {
  const [summary, setSummary] = useState<ControlSummary | null>(null);
  const [runs, setRuns] = useState<InvestigationRun[]>([]);
  const [configuration, setConfiguration] =
    useState<SoftPromptConfiguration | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [nextSummary, history, nextConfiguration] = await Promise.all([
        investigationControlApi.getSummary(),
        investigationControlApi.listRuns(20),
        investigationControlApi.getConfiguration(),
      ]);
      if (!mountedRef.current) return;
      setSummary(nextSummary);
      setRuns(history.items);
      setConfiguration(nextConfiguration);
      setError(null);
    } catch (caught) {
      if (mountedRef.current) setError(messageFor(caught));
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
  }, []);

  // Load once, then poll summary every 5s while the tab is visible.
  useEffect(() => {
    mountedRef.current = true;
    void refresh();

    let intervalId: number | undefined;

    const stopPolling = () => {
      if (intervalId !== undefined) {
        window.clearInterval(intervalId);
        intervalId = undefined;
      }
    };

    const startPolling = () => {
      if (intervalId !== undefined) return;
      intervalId = window.setInterval(() => {
        if (document.visibilityState === "visible") {
          void refresh();
        }
      }, SUMMARY_POLL_MS);
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void refresh();
        startPolling();
      } else {
        stopPolling();
      }
    };

    if (document.visibilityState === "visible") {
      startPolling();
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      mountedRef.current = false;
      stopPolling();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);

  const activeRun = summary?.active_run ?? null;
  useEffect(() => {
    if (!activeRun || !ACTIVE_STATUSES.has(activeRun.status)) return;

    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const nextRun = await investigationControlApi.getRun(activeRun.run_id);
        if (cancelled || !mountedRef.current) return;
        setSummary((current) =>
          current ? { ...current, active_run: nextRun } : current,
        );
        setRuns((current) => [
          nextRun,
          ...current.filter((item) => item.run_id !== nextRun.run_id),
        ]);
        if (!ACTIVE_STATUSES.has(nextRun.status)) {
          await refresh();
          return;
        }
      } catch (caught) {
        if (!cancelled && mountedRef.current) setError(messageFor(caught));
      }
      if (!cancelled) timer = window.setTimeout(poll, ACTIVE_RUN_POLL_MS);
    };

    timer = window.setTimeout(poll, ACTIVE_RUN_POLL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeRun, refresh]);

  const mutate = useCallback(
    async (operation: () => Promise<void>): Promise<boolean> => {
      if (isMutating) return false;
      setIsMutating(true);
      setError(null);
      try {
        await operation();
        return true;
      } catch (caught) {
        if (mountedRef.current) setError(messageFor(caught));
        if (
          caught instanceof InvestigationControlApiError &&
          caught.status === 409
        ) {
          await refresh();
        }
        return false;
      } finally {
        if (mountedRef.current) setIsMutating(false);
      }
    },
    [isMutating, refresh],
  );

  const setMode = useCallback(
    async (mode: RunMode) =>
      mutate(async () => {
        await investigationControlApi.setMode(mode);
        await refresh();
      }),
    [mutate, refresh],
  );

  const startManualRun = useCallback(
    async () =>
      mutate(async () => {
        const run = await investigationControlApi.createRun("MANUAL");
        if (!mountedRef.current) return;
        setSummary((current) =>
          current ? { ...current, active_run: run } : current,
        );
        setRuns((current) => [
          run,
          ...current.filter((item) => item.run_id !== run.run_id),
        ]);
      }),
    [mutate],
  );

  const saveSoftPrompt = useCallback(
    async (value: string) =>
      mutate(async () => {
        const saved = await investigationControlApi.saveConfiguration(value);
        if (mountedRef.current) setConfiguration(saved);
      }),
    [mutate],
  );

  const resetSoftPrompt = useCallback(
    async () => saveSoftPrompt(""),
    [saveSoftPrompt],
  );

  const clearError = useCallback(() => setError(null), []);

  return {
    summary,
    runs,
    configuration,
    isLoading,
    isMutating,
    error,
    refresh,
    setMode,
    startManualRun,
    saveSoftPrompt,
    resetSoftPrompt,
    clearError,
  };
}

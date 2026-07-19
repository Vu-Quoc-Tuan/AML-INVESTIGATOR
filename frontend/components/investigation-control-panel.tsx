"use client";

import { AlertCircle, Clock3, History, Loader2, RefreshCw } from "lucide-react";

import type { InvestigationControlState } from "@/hooks/use-investigation-control";
import type { InvestigationRun, RunMode } from "@/lib/investigation-control";

const TERMINAL_LABELS: Record<string, string> = {
  COMPLETED: "Hoàn tất",
  COMPLETED_WITH_ERRORS: "Hoàn tất có lỗi",
  FAILED: "Thất bại",
  INTERRUPTED: "Bị gián đoạn",
  PENDING: "Đang chờ",
  RUNNING: "Đang chạy",
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function RunLine({ run }: { run: InvestigationRun }) {
  const isActive = run.status === "PENDING" || run.status === "RUNNING";
  const emptyDrain =
    !isActive &&
    run.status === "COMPLETED" &&
    run.completed_count === 0 &&
    run.failed_count === 0;
  const triggerStyle =
    run.trigger === "AUTO"
      ? "bg-blue-50 text-blue-800 ring-blue-200"
      : "bg-slate-100 text-slate-700 ring-slate-200";
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3 text-sm">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 font-medium text-slate-800">
          <span
            className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ${triggerStyle}`}
          >
            {run.trigger}
          </span>
          <span>{TERMINAL_LABELS[run.status] ?? run.status}</span>
          {emptyDrain ? (
            <span className="text-xs font-normal text-slate-500">queue rỗng</span>
          ) : null}
        </p>
        <p className="mt-0.5 text-xs text-slate-500">
          {formatTimestamp(run.created_at)} · {run.run_id.slice(0, 8)}
        </p>
      </div>
      <div className="flex items-center gap-2 text-xs font-medium text-slate-600">
        {isActive ? <Loader2 className="size-3.5 animate-spin text-blue-600" /> : null}
        <span>{run.completed_count} xong</span>
        <span aria-hidden="true">·</span>
        <span className={run.failed_count ? "text-red-700" : undefined}>
          {run.failed_count} lỗi
        </span>
      </div>
    </li>
  );
}

export function InvestigationControlPanel({
  control,
  onGoHistory,
}: {
  control: InvestigationControlState;
  /** MANUAL: open History to run one PENDING ticket at a time. */
  onGoHistory?: () => void;
}) {
  const { summary, runs, isLoading, isMutating, error } = control;
  const activeRun = summary?.active_run;
  const active = activeRun?.status === "PENDING" || activeRun?.status === "RUNNING";
  const interactionDisabled = isMutating || active;
  const pending = summary?.queue.pending ?? 0;

  const changeMode = (mode: RunMode) => {
    if (mode !== summary?.mode) void control.setMode(mode);
  };

  return (
    <section
      aria-labelledby="investigation-control-title"
      className="overflow-hidden rounded-xl bg-white ring-1 ring-slate-200"
    >
      <div className="flex flex-col gap-5 border-b border-slate-200 p-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 id="investigation-control-title" className="text-lg font-semibold text-slate-950">
              Điều khiển investigation
            </h2>
            {active ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
                <span className="size-1.5 rounded-full bg-blue-600" />
                {TERMINAL_LABELS[activeRun.status]}
              </span>
            ) : null}
          </div>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
            <strong>MANUAL</strong>: vào Lịch sử, bấm <strong>Chạy</strong> từng dòng PENDING (một
            ticket một lần). <strong>AUTO</strong>: scheduler 02:00 drain cả queue (batch).
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl bg-slate-100 p-1" aria-label="Investigation mode">
            {(["MANUAL", "AUTO"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                disabled={interactionDisabled || isLoading}
                aria-pressed={summary?.mode === mode}
                aria-busy={isMutating}
                onClick={() => changeMode(mode)}
                className={`rounded-lg px-3 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                  summary?.mode === mode
                    ? "bg-white text-slate-950 shadow-sm"
                    : "text-slate-600 hover:text-slate-950"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={isLoading || isMutating}
            aria-label="Làm mới trạng thái"
            onClick={() => void control.refresh()}
            className="grid size-10 place-items-center rounded-xl text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error ? (
        <div role="alert" className="m-5 flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="grid lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
        <div className="p-5 lg:border-r lg:border-slate-200">
          {isLoading && !summary ? (
            <div className="space-y-3" aria-label="Đang tải trạng thái">
              <div className="h-5 w-40 animate-pulse rounded bg-slate-200" />
              <div className="h-20 animate-pulse rounded-xl bg-slate-100" />
            </div>
          ) : (
            <>
              <p className="text-sm font-medium text-slate-800">
                Chế độ hiện tại:{" "}
                <span className="text-blue-700">{summary?.mode ?? "—"}</span>
                {summary?.mode === "MANUAL" ? (
                  <span className="ml-2 text-xs font-normal text-slate-500">
                    · {pending} ticket PENDING
                  </span>
                ) : null}
              </p>

              {summary?.mode === "AUTO" ? (
                <div className="mt-4 flex gap-3 rounded-xl bg-blue-50 p-4 text-sm leading-6 text-blue-900 ring-1 ring-blue-100">
                  <Clock3 className="mt-0.5 size-5 shrink-0" />
                  <p>
                    AUTO: cron/scheduler gọi batch drain lúc 02:00 (Asia/Ho_Chi_Minh). Queue rỗng
                    thì batch kết thúc 0 ticket (bình thường). Không chạy từng dòng trên History.
                  </p>
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  <div className="rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-700 ring-1 ring-slate-200">
                    MANUAL <strong>không</strong> chạy batch cả queue. Vào{" "}
                    <strong>Lịch sử đáng ngờ</strong>, chỉ dòng <strong>PENDING</strong> có nút{" "}
                    <strong>Chạy</strong> — mỗi lần một ticket.
                  </div>
                  <button
                    type="button"
                    onClick={() => onGoHistory?.()}
                    className="inline-flex h-11 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                  >
                    <History className="size-4" />
                    Mở Lịch sử · chạy từng PENDING
                  </button>
                </div>
              )}

              {activeRun ? (
                <div className="mt-5 border-t border-slate-200 pt-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                    <span className="font-medium text-slate-800">
                      Batch {activeRun.trigger} · {activeRun.run_id.slice(0, 8)}
                    </span>
                    <span className="text-slate-600">
                      {activeRun.completed_count} hoàn tất · {activeRun.failed_count} lỗi
                    </span>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className="border-t border-slate-200 p-5 lg:border-t-0">
          <h3 className="text-sm font-semibold text-slate-900">Lịch sử batch</h3>
          <p className="mt-1 text-xs text-slate-500">
            AUTO = drain queue (scheduler). MANUAL = batch API (trigger đúng như DB).
          </p>
          {runs.length ? (
            <ul className="mt-2 divide-y divide-slate-200">
              {runs.slice(0, 5).map((run) => (
                <RunLine key={run.run_id} run={run} />
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm leading-6 text-slate-600">
              Chưa có batch. Ticket lẻ chạy ở tab Lịch sử (không tạo dòng batch).
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Download,
  FileText,
  History,
  LayoutDashboard,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  ShieldAlert,
  Workflow,
  XCircle,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Handle,
  MarkerType,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { AgentSettingsPanel } from "@/components/agent-settings-panel";
import { FinalOutputWithCitations } from "@/components/final-output-with-citations";
import { InvestigationControlPanel } from "@/components/investigation-control-panel";
import { useInvestigationEvents } from "@/hooks/use-investigation-events";
import {
  useInvestigationControl,
  type InvestigationControlState,
} from "@/hooks/use-investigation-control";
import { ApiError } from "@/lib/api";
import { InvestigationControlApiError } from "@/lib/investigation-control";
import type {
  AgentRuntimeStatus,
  InvestigationEvent,
} from "@/lib/investigation-events";
import {
  LLM_AGENTS,
  WORKFLOW_EDGES,
  WORKFLOW_NODES,
  type WorkflowNodeDefinition,
  type WorkflowNodeIcon,
} from "@/lib/workflow-catalog";
import { getFlowTrends, type FlowTrendPoint } from "@/lib/metrics";
import {
  getTicket,
  listTickets,
  reviewTicket,
  runTicket,
  type ReviewDecision,
  type TicketDetail,
  type TicketStatus,
  type TicketSummary,
} from "@/lib/tickets";
// getTicket used on WorkflowPage for APPROVE/REJECT footer

type PageKey = "dashboard" | "history" | "workflow" | "config";
/** History list badge labels (not the same as raw queue status). */
type Status =
  | "Pending"
  | "Running"
  | "Review"
  | "Approved"
  | "Rejected"
  | "False"
  | "Failed"
  | "Done";

const navItems: { key: PageKey; label: string; icon: typeof LayoutDashboard }[] = [
  { key: "dashboard", label: "Trang chủ", icon: LayoutDashboard },
  { key: "history", label: "Lịch sử đáng ngờ", icon: History },
  { key: "workflow", label: "Luồng Agent", icon: Network },
  { key: "config", label: "Cấu hình Agent", icon: Settings2 },
];

function ticketMessage(ticket: TicketSummary): string {
  // Decision is shown as a compact pill in Actions — do not repeat long review text.
  if (ticket.review_decision) return "—";
  if (ticket.message && ticket.message.trim()) {
    const msg = ticket.message.trim();
    if (/analyst\s+(approved|rejected)|review:\s*/i.test(msg)) return "—";
    return msg;
  }
  if (ticket.overall_risk_level) {
    return `Risk: ${ticket.overall_risk_level} · ML ${ticket.ml_confidence.toFixed(2)}`;
  }
  if (ticket.status === "PENDING") return "Waiting for multi-agent — press Run";
  if (ticket.status === "PROCESSING") return "Multi-agent running";
  if (ticket.status === "FAILED") return "Investigation failed";
  return "Investigation finished";
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof InvestigationControlApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

const statusStyles: Record<Status, string> = {
  Pending: "bg-amber-50 text-amber-700 ring-amber-200",
  Running: "bg-blue-50 text-blue-700 ring-blue-200",
  Review: "bg-violet-50 text-violet-700 ring-violet-200",
  Approved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  Rejected: "bg-red-50 text-red-700 ring-red-200",
  False: "bg-slate-100 text-slate-700 ring-slate-300",
  Failed: "bg-orange-50 text-orange-800 ring-orange-200",
  Done: "bg-slate-50 text-slate-600 ring-slate-200",
};

const statusLabels: Record<Status, string> = {
  Pending: "Pending",
  Running: "Running",
  Review: "Review",
  Approved: "APPROVED",
  Rejected: "REJECTED",
  False: "FALSE",
  Failed: "Failed",
  Done: "Done",
};

function useCount(target: number) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const reducedTimer = window.setTimeout(() => setCount(target), 0);
      return () => window.clearTimeout(reducedTimer);
    }

    let frame = 0;
    const total = 42;
    const timer = window.setInterval(() => {
      frame += 1;
      const progress = 1 - Math.pow(1 - frame / total, 4);
      setCount(Math.round(target * progress));
      if (frame >= total) window.clearInterval(timer);
    }, 18);

    return () => window.clearInterval(timer);
  }, [target]);

  return count;
}

function cn(...classes: Array<string | false | undefined>) {
  return classes.filter(Boolean).join(" ");
}

type StatItem = {
  title: "Pending" | "Checking" | "Reject" | "Approve";
  value: number;
  description: string;
  color: "yellow" | "blue" | "red" | "green";
  icon: typeof Clock3;
};

function StatCard({ item }: { item: StatItem }) {
  const count = useCount(item.value);
  const Icon = item.icon;
  const palette = {
    yellow: "bg-amber-50 text-amber-700 ring-amber-200",
    blue: "bg-blue-50 text-blue-700 ring-blue-200",
    red: "bg-red-50 text-red-700 ring-red-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  }[item.color];

  return (
    <motion.div
      whileHover={{ y: -3 }}
      className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70 transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between">
        <div className={cn("grid size-11 place-items-center rounded-xl ring-1", palette)}>
          <Icon className={cn("size-5", item.title === "Checking" && "animate-spin")} />
        </div>
        <span className={cn("mt-1 size-2.5 rounded-full", {
          Pending: "bg-amber-400",
          Checking: "bg-blue-500",
          Reject: "bg-red-500",
          Approve: "bg-emerald-500",
        }[item.title])} />
      </div>
      <div className="mt-5">
        <p className="text-sm font-medium text-slate-600">{item.title}</p>
        <p className="mt-2 text-3xl font-semibold tracking-normal text-slate-950">{count.toLocaleString()}</p>
        <p className="mt-2 text-sm leading-6 text-slate-600">{item.description}</p>
      </div>
    </motion.div>
  );
}

function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-3xl font-semibold tracking-normal text-slate-950">{title}</h1>
      {subtitle && <p className="max-w-3xl text-base leading-7 text-slate-600">{subtitle}</p>}
    </div>
  );
}

function DashboardPage({
  control,
  onGoHistory,
}: {
  control: InvestigationControlState;
  onGoHistory?: () => void;
}) {
  const queue = control.summary?.queue;
  const stats: StatItem[] = [
    {
      title: "Pending",
      value: queue?.pending ?? 0,
      description: "Chờ multi-agent (PENDING trong queue)",
      color: "yellow",
      icon: Clock3,
    },
    {
      title: "Checking",
      value: queue?.processing ?? 0,
      description: "Đang chạy multi-agent (PROCESSING)",
      color: "blue",
      icon: Loader2,
    },
    {
      title: "Reject",
      value: queue?.rejected ?? 0,
      description: "Analyst bấm REJECT sau khi agent nghi rửa tiền",
      color: "red",
      icon: XCircle,
    },
    {
      title: "Approve",
      value: queue?.approved ?? 0,
      description: "Analyst bấm APPROVE sau khi agent nghi rửa tiền",
      color: "green",
      icon: CheckCircle2,
    },
  ];

  const [trendDays, setTrendDays] = useState(7);
  const [trendPoints, setTrendPoints] = useState<FlowTrendPoint[]>([]);
  const [trendLoading, setTrendLoading] = useState(true);
  const [trendError, setTrendError] = useState<string | null>(null);

  const loadTrends = useCallback(async (days: number) => {
    setTrendLoading(true);
    setTrendError(null);
    try {
      const response = await getFlowTrends(days);
      setTrendPoints(response.items);
    } catch (err) {
      setTrendError(errorMessage(err));
      setTrendPoints([]);
    } finally {
      setTrendLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTrends(trendDays);
  }, [loadTrends, trendDays]);

  // Refresh chart when investigation control summary reloads (e.g. after a run).
  useEffect(() => {
    if (control.summary) {
      void loadTrends(trendDays);
    }
  }, [control.summary?.queue?.pending, control.summary?.queue?.completed, control.summary?.queue?.failed, loadTrends, trendDays]);

  const chartData = useMemo(
    () =>
      trendPoints.map((point) => ({
        ...point,
        label: `${point.day} ${point.date.slice(5)}`,
      })),
    [trendPoints],
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title="AML-Investigator"
        subtitle="Queue realtime và các batch multi-agent được đồng bộ từ backend."
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((item) => (
          <StatCard key={item.title} item={item} />
        ))}
      </div>
      <InvestigationControlPanel control={control} onGoHistory={onGoHistory} />
      <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Detection flow trends</h2>
            <p className="mt-1 text-sm text-slate-600">
              Số outcome detection lưu DB theo ngày (queued + blocked). ALLOWED không lưu nên không có trên chart.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <span className="flex items-center gap-2">
              <span className="size-2 rounded-full bg-blue-600" />
              Durable outcomes (queued+blocked)
            </span>
            <span className="flex items-center gap-2">
              <span className="size-2 rounded-full bg-red-500" />
              Queued for investigation
            </span>
            <select
              value={trendDays}
              onChange={(event) => setTrendDays(Number(event.target.value))}
              className="rounded-xl bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-200 outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
            </select>
            <button
              type="button"
              onClick={() => void loadTrends(trendDays)}
              className="inline-flex h-9 items-center gap-2 rounded-xl bg-white px-3 text-sm font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            >
              <RefreshCw className={cn("size-4", trendLoading && "animate-spin")} />
              Refresh
            </button>
          </div>
        </div>
        {trendError && (
          <p className="mb-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
            {trendError}
          </p>
        )}
        <div className="h-[360px] w-full">
          {trendLoading && chartData.length === 0 ? (
            <div className="grid h-full place-items-center text-sm text-slate-500">Loading trends…</div>
          ) : (
            <ResponsiveContainer>
              <AreaChart data={chartData} margin={{ left: 0, right: 12, top: 12, bottom: 0 }}>
                <defs>
                  <linearGradient id="volume" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="5%" stopColor="#2563EB" stopOpacity={0.28} />
                    <stop offset="95%" stopColor="#2563EB" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="flagged" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="5%" stopColor="#EF4444" stopOpacity={0.22} />
                    <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "#64748B", fontSize: 12 }} />
                <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: "#64748B", fontSize: 12 }} />
                <Tooltip
                  contentStyle={{ borderRadius: 12, borderColor: "#E2E8F0", boxShadow: "0 8px 24px rgba(15, 23, 42, 0.08)" }}
                  formatter={(value) => (typeof value === "number" ? value.toLocaleString() : value)}
                  labelFormatter={(_, payload) => {
                    const point = payload?.[0]?.payload as FlowTrendPoint | undefined;
                    return point?.date ?? "";
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="volume"
                  stroke="#2563EB"
                  strokeWidth={3}
                  fill="url(#volume)"
                  name="Durable outcomes"
                />
                <Area
                  type="monotone"
                  dataKey="flagged"
                  stroke="#EF4444"
                  strokeWidth={3}
                  fill="url(#flagged)"
                  name="Queued candidates"
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>
    </div>
  );
}

function displayTicketStatus(ticket: TicketSummary): Status {
  const raw = (ticket.display_status || "").toUpperCase();
  if (raw === "APPROVED" || ticket.review_decision === "APPROVED") return "Approved";
  if (raw === "REJECTED" || ticket.review_decision === "REJECTED") return "Rejected";
  if (raw === "FALSE" || ticket.review_decision === "FALSE") return "False";
  if (raw === "AWAITING_REVIEW" || ticket.can_review) return "Review";
  if (raw === "RUNNING" || ticket.status === "PROCESSING") return "Running";
  if (raw === "FAILED" || ticket.status === "FAILED") return "Failed";
  if (raw === "PENDING" || ticket.status === "PENDING") return "Pending";
  if (ticket.status === "COMPLETED") return "Done";
  return "Pending";
}

function HistoryPage({
  onGoWorkflow,
}: {
  onGoWorkflow?: (ticketId: string) => void;
}) {
  const pageSize = 6;
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<TicketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  const loadPage = useCallback(async (nextPage: number) => {
    setLoading(true);
    setError(null);
    try {
      const offset = (nextPage - 1) * pageSize;
      const response = await listTickets({ limit: pageSize, offset });
      setItems(response.items);
      setHasMore(response.count === pageSize);
      setPage(nextPage);
    } catch (err) {
      setError(errorMessage(err));
      setItems([]);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPage(1);
  }, [loadPage]);

  /** Open agent flow for any ticket (pending/running/done) — SSE replays history. */
  const openTicketFlow = (ticketId: string) => {
    onGoWorkflow?.(ticketId);
  };

  const onRunTicket = async (ticketId: string) => {
    setActionBusy(ticketId);
    setError(null);
    try {
      await runTicket(ticketId);
      onGoWorkflow?.(ticketId);
      await loadPage(page);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setActionBusy(null);
    }
  };

  const onReview = async (ticketId: string, decision: ReviewDecision) => {
    setActionBusy(ticketId);
    setError(null);
    try {
      const updated = await reviewTicket(ticketId, decision);
      setItems((current) =>
        current.map((item) => (item.ticket_id === ticketId ? { ...item, ...updated } : item)),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setActionBusy(null);
    }
  };

  const startIndex = items.length === 0 ? 0 : (page - 1) * pageSize + 1;
  const endIndex = (page - 1) * pageSize + items.length;
  const anyProcessing = items.some((item) => item.status === "PROCESSING");

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <PageHeader
          title="Lịch sử đáng ngờ"
          subtitle="Click ID để mở Luồng Agent (SSE + log). PENDING: nút Run (một ticket một lúc). APPROVE/REJECT hiện dưới luồng khi xong và nghi rửa tiền."
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void loadPage(page)}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50"
          >
            <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
          </button>
        </div>
      </div>

      {error && (
        <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">{error}</p>
      )}

      <section className="rounded-xl bg-white p-3 shadow-sm ring-1 ring-slate-200/70">
        <div className="hidden grid-cols-[1.1fr_0.9fr_1.2fr_1.3fr_1.1fr] px-4 py-3 text-xs font-semibold text-slate-500 md:grid">
          <span>ID</span>
          <span>Status</span>
          <span>Transaction</span>
          <span>Message</span>
          <span>Actions</span>
        </div>
        <div className="space-y-2">
          {loading && items.length === 0 && (
            <p className="px-4 py-8 text-center text-sm text-slate-500">Loading tickets…</p>
          )}
          {!loading && items.length === 0 && (
            <div className="space-y-2 px-4 py-8 text-center text-sm text-slate-600">
              <p className="font-medium text-slate-800">Chưa có ticket trong queue</p>
              <p>
                Dashboard có thể vẫn hiện batch MANUAL “Hoàn tất · 0 ticket” — đó chỉ là
                lần bấm chạy khi queue rỗng, không tạo dòng History.
              </p>
              <p className="text-slate-500">
                Cần detection ghi candidate (Kafka validated → worker) rồi Refresh.
              </p>
            </div>
          )}
          {items.map((row) => {
            const uiStatus = displayTicketStatus(row);
            const label = row.case_id || row.ticket_id;
            const busy = actionBusy === row.ticket_id;
            return (
              <div
                key={row.ticket_id}
                className="grid w-full gap-3 rounded-xl bg-slate-50 p-4 md:grid-cols-[1.1fr_0.9fr_1.2fr_1.3fr_1.1fr] md:items-center"
              >
                <button
                  type="button"
                  onClick={() => openTicketFlow(row.ticket_id)}
                  className="truncate text-left font-medium text-slate-950 hover:text-blue-700"
                  title="Open agent flow for this ticket"
                >
                  {label}
                </button>
                <span className="flex justify-center md:justify-start">
                  <span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-medium ring-1", statusStyles[uiStatus])}>
                    {statusLabels[uiStatus]}
                  </span>
                </span>
                <span className="truncate text-sm text-slate-700">{row.transaction_id || row.event_id}</span>
                <span className="line-clamp-2 text-sm text-slate-600" title={ticketMessage(row)}>
                  {ticketMessage(row)}
                </span>
                <div className="flex min-h-8 flex-wrap items-center justify-center gap-2">
                  {row.status === "PENDING" && row.can_run && (
                    <button
                      type="button"
                      disabled={busy || anyProcessing || actionBusy !== null}
                      title={
                        anyProcessing
                          ? "Another ticket is RUNNING — wait before the next Run"
                          : "Run multi-agent for this PENDING ticket"
                      }
                      onClick={() => void onRunTicket(row.ticket_id)}
                      className="inline-flex h-8 items-center rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      {busy ? "…" : "Run"}
                    </button>
                  )}
                  {row.can_review && (
                    <>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void onReview(row.ticket_id, "APPROVED")}
                        className="inline-flex h-8 items-center rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                      >
                        APPROVE
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void onReview(row.ticket_id, "REJECTED")}
                        className="inline-flex h-8 items-center rounded-lg bg-red-600 px-3 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        REJECT
                      </button>
                    </>
                  )}
                  {!row.can_review && row.review_decision === "APPROVED" && (
                    <span className="inline-flex h-8 items-center rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white">
                      APPROVED
                    </span>
                  )}
                  {!row.can_review && row.review_decision === "REJECTED" && (
                    <span className="inline-flex h-8 items-center rounded-lg bg-red-600 px-3 text-xs font-semibold text-white">
                      REJECTED
                    </span>
                  )}
                  {!row.can_review && row.review_decision === "FALSE" && (
                    <span className="inline-flex h-8 items-center rounded-lg bg-slate-600 px-3 text-xs font-semibold text-white">
                      FALSE
                    </span>
                  )}
                  {!row.can_run && !row.can_review && !row.review_decision && row.status === "PROCESSING" && (
                    <span className="text-xs text-blue-700">…</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="flex items-center justify-between text-sm text-slate-600">
        <span>
          {items.length === 0
            ? "No cases on this page"
            : `Showing ${startIndex}-${endIndex} (page ${page})`}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void loadPage(page - 1)}
            disabled={page === 1 || loading}
            className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 disabled:hover:bg-white"
          >
            Previous
          </button>
          <span className="rounded-xl bg-blue-600 px-3 py-2 font-medium text-white">{page}</span>
          <button
            type="button"
            onClick={() => void loadPage(page + 1)}
            disabled={!hasMore || loading}
            className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 disabled:hover:bg-white"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

const workflowIconMap: Record<WorkflowNodeIcon, typeof BrainCircuit> = {
  planner: BrainCircuit,
  transaction: Network,
  kyc: ShieldCheck,
  screening: ShieldAlert,
  behavior: Workflow,
  report: FileText,
};

type WorkflowNodeData = WorkflowNodeDefinition & {
  runtimeStatus: AgentRuntimeStatus;
  selected: boolean;
};

const runtimeStatusStyles: Record<AgentRuntimeStatus, string> = {
  IDLE: "bg-slate-100 text-slate-600 ring-slate-200",
  RUNNING: "bg-blue-50 text-blue-700 ring-blue-200",
  COMPLETED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  FAILED: "bg-red-50 text-red-700 ring-red-200",
};

function WorkflowNode({ data }: { data: WorkflowNodeData }) {
  const Icon = workflowIconMap[data.icon];

  return (
    <div className={cn(
      "w-64 rounded-xl bg-white p-4 shadow-sm ring-1",
      data.selected ? "ring-2 ring-blue-500" : "ring-slate-200",
    )}>
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="flex items-center gap-3">
        <div className={cn(
          "grid size-10 shrink-0 place-items-center rounded-xl ring-1",
          "bg-blue-50 text-blue-700 ring-blue-100",
        )}>
          <Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <span className={cn(
            "inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1",
            runtimeStatusStyles[data.runtimeStatus],
          )}>{data.runtimeStatus}</span>
          <p className="font-semibold text-slate-950">{data.name}</p>
          <p className="truncate text-xs text-slate-500">{data.stage}</p>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

function eventLabel(event: InvestigationEvent): string {
  if (event.event_type === "TOOL_STARTED") return "Gọi tool";
  if (event.event_type === "TOOL_SUCCEEDED") return "Kết quả tool";
  if (event.event_type === "TOOL_FAILED") return "Tool lỗi — investigation đã dừng";
  if (event.event_type === "AGENT_STARTED") return "Agent bắt đầu";
  if (event.event_type === "AGENT_COMPLETED") return "Output agent";
  if (event.event_type === "AGENT_FAILED") return "Agent lỗi";
  return event.event_type;
}

function EventCard({ event }: { event: InvestigationEvent }) {
  return (
    <article className={cn(
      "rounded-xl border p-3",
      event.event_type.includes("FAILED")
        ? "border-red-200 bg-red-50"
        : "border-slate-200 bg-slate-50",
    )}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
            {eventLabel(event)}
          </p>
          {event.tool_name && <p className="mt-1 font-mono text-xs text-blue-700">{event.tool_name}</p>}
        </div>
        <time className="shrink-0 text-[11px] text-slate-500">
          {new Date(event.created_at).toLocaleTimeString("vi-VN")}
        </time>
      </div>
      <p className="mt-2 text-sm leading-5 text-slate-700">{event.summary}</p>
      {event.payload && (
        <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-2 text-[11px] leading-5 text-slate-600 ring-1 ring-slate-200">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      )}
    </article>
  );
}

function WorkflowPage({ ticketId }: { ticketId: string | null }) {
  const { state, connection, error } = useInvestigationEvents(ticketId);
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [ticketError, setTicketError] = useState<string | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [manualSelection, setManualSelection] = useState({
    agentId: LLM_AGENTS[0].id,
    atEventId: 0,
  });

  useEffect(() => {
    if (!ticketId) {
      setTicket(null);
      setTicketError(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const detail = await getTicket(ticketId);
        if (!cancelled) {
          setTicket(detail);
          setTicketError(null);
        }
      } catch (err) {
        if (!cancelled) setTicketError(errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticketId, state.technicalStatus, state.reviewDecision]);

  const selected = state.lastEventId > manualSelection.atEventId
    ? state.selectedAgentId ?? manualSelection.agentId
    : manualSelection.agentId;
  const selectedDefinition = LLM_AGENTS.find((agent) => agent.id === selected) ?? LLM_AGENTS[0];
  const selectedRuntime = state.agents[selected];
  const nodeTypes = useMemo(() => ({ workflow: WorkflowNode }), []);
  const nodes = useMemo(
    () => WORKFLOW_NODES.map((node) => ({
      id: node.id,
      type: "workflow",
      position: node.position,
      data: {
        ...node,
        runtimeStatus: state.agents[node.id]?.status ?? "IDLE",
        selected: node.id === selected,
      },
    })),
    [selected, state.agents]
  );
  const edges = useMemo(
    () => WORKFLOW_EDGES.map((edge) => ({
      ...edge,
      type: "smoothstep",
      animated: state.technicalStatus === "RUNNING",
      markerEnd: { type: MarkerType.ArrowClosed },
      style: {
        stroke: state.technicalStatus === "FAILED" ? "#F87171" : "#94A3B8",
        strokeWidth: 1.5,
      },
    })),
    [state.technicalStatus]
  );

  const canReview =
    Boolean(ticket?.can_review) ||
    (
      state.technicalStatus === "COMPLETED" &&
      !state.reviewDecision &&
      Boolean(
        (state.finalOutput as { is_laundering_suspect?: boolean } | null)
          ?.is_laundering_suspect
      )
    );

  const showFailedBanner =
    state.technicalStatus === "FAILED" ||
    Boolean(state.lastErrorSummary) ||
    Boolean(ticket?.last_error);

  const onReview = async (decision: ReviewDecision) => {
    if (!ticketId) return;
    setReviewBusy(true);
    try {
      const updated = await reviewTicket(ticketId, decision);
      setTicket(updated);
    } catch (err) {
      setTicketError(errorMessage(err));
    } finally {
      setReviewBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Luồng Agent"
        subtitle="Click ticket ID trên Lịch sử để mở luồng. SSE realtime khi đang chạy; khi xong xem log tool/agent và APPROVE/REJECT."
      />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full bg-white px-3 py-1.5 text-slate-600 ring-1 ring-slate-200">
          Ticket: <strong className="text-slate-900">{ticketId ?? "chưa chọn"}</strong>
        </span>
        <span className={cn(
          "rounded-full px-3 py-1.5 font-medium ring-1",
          connection === "OPEN"
            ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
            : connection === "ERROR"
              ? "bg-red-50 text-red-700 ring-red-200"
              : connection === "CONNECTING"
                ? "bg-amber-50 text-amber-800 ring-amber-200"
                : connection === "CLOSED"
                  ? "bg-slate-100 text-slate-700 ring-slate-300"
                  : "bg-slate-100 text-slate-600 ring-slate-200",
        )}>
          SSE: {ticketId ? connection : "IDLE (chưa chọn ticket)"}
        </span>
        <span className={cn(
          "rounded-full px-3 py-1.5 font-medium ring-1",
          runtimeStatusStyles[state.technicalStatus],
        )}>
          Investigation: {ticketId ? state.technicalStatus : "IDLE (chưa chọn ticket)"}
        </span>
        {ticket?.display_status && (
          <span className="rounded-full bg-white px-3 py-1.5 text-slate-700 ring-1 ring-slate-200">
            Status: <strong>{ticket.display_status}</strong>
          </span>
        )}
      </div>
      {!ticketId && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
          Click <strong>ID</strong> trên Lịch sử (hoặc bấm <strong>Run</strong> ticket PENDING) để mở
          luồng agent + SSE.
        </div>
      )}
      {(error || ticketError) && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error || ticketError}
        </div>
      )}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-3">
          <section className="h-[640px] overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200/70">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.18 }}
              minZoom={0.25}
              proOptions={{ hideAttribution: true }}
              nodesDraggable={false}
              nodesConnectable={false}
              onNodeClick={(_, node) => setManualSelection({
                agentId: node.id,
                atEventId: state.lastEventId,
              })}
            />
          </section>

          {/* Bottom strip: errors + approve/reject + short timeline */}
          <section className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200/70">
            {showFailedBanner && (
              <div className="mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                <p className="font-semibold">Investigation error</p>
                <p className="mt-1">
                  {state.lastErrorSummary
                    || ticket?.last_error
                    || "Multi-agent failed — xem log bên cạnh / timeline."}
                </p>
              </div>
            )}

            {state.technicalStatus === "RUNNING" && (
              <p className="mb-3 text-sm text-blue-700">
                Đang chạy realtime — log agent/tool cập nhật qua SSE…
              </p>
            )}

            {state.timeline.length > 0 && (
              <div className="mb-3 max-h-36 space-y-1 overflow-y-auto rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  Lịch sử (agent / tool / review)
                </p>
                {state.timeline.map((event) => (
                  <div key={event.id} className="flex gap-2 text-xs leading-5 text-slate-700">
                    <span className="shrink-0 font-mono text-slate-400">
                      {new Date(event.created_at).toLocaleTimeString("vi-VN")}
                    </span>
                    <span className={cn(
                      "font-medium",
                      event.event_type.includes("FAILED") ? "text-red-700" : "text-slate-800",
                    )}>
                      {event.event_type}
                    </span>
                    {event.agent_id && <span className="text-blue-700">{event.agent_id}</span>}
                    {event.tool_name && (
                      <span className="font-mono text-violet-700">{event.tool_name}</span>
                    )}
                    <span className="truncate text-slate-600">{event.summary}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="flex min-h-10 flex-wrap items-center justify-center gap-2">
              {canReview ? (
                <>
                  <button
                    type="button"
                    disabled={reviewBusy}
                    onClick={() => void onReview("APPROVED")}
                    className="inline-flex h-10 items-center rounded-xl bg-emerald-600 px-4 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    APPROVE
                  </button>
                  <button
                    type="button"
                    disabled={reviewBusy}
                    onClick={() => void onReview("REJECTED")}
                    className="inline-flex h-10 items-center rounded-xl bg-red-600 px-4 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                  >
                    REJECT
                  </button>
                </>
              ) : ticket?.review_decision === "APPROVED" ? (
                <span className="inline-flex h-10 items-center rounded-xl bg-emerald-600 px-4 text-sm font-semibold text-white">
                  APPROVED
                </span>
              ) : ticket?.review_decision === "REJECTED" ? (
                <span className="inline-flex h-10 items-center rounded-xl bg-red-600 px-4 text-sm font-semibold text-white">
                  REJECTED
                </span>
              ) : ticket?.review_decision === "FALSE" ? (
                <span className="inline-flex h-10 items-center rounded-xl bg-slate-600 px-4 text-sm font-semibold text-white">
                  FALSE
                </span>
              ) : null}
            </div>
          </section>
        </div>

        <section className="max-h-[860px] overflow-y-auto rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200/70">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">{selectedDefinition.name}</h2>
              <p className="mt-1 text-sm text-slate-500">{selectedDefinition.stage}</p>
            </div>
            <span className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium ring-1",
              runtimeStatusStyles[selectedRuntime?.status ?? "IDLE"],
            )}>{selectedRuntime?.status ?? "IDLE"}</span>
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-700">{selectedDefinition.role}</p>
          <div className="my-4 border-t border-slate-200" />
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Chi tiết agent (tool / output)
          </h3>
          <div className="mt-3 space-y-3">
            {selectedRuntime?.events.length ? (
              selectedRuntime.events.map((event) => <EventCard key={event.id} event={event} />)
            ) : (
              <p className="rounded-xl bg-slate-50 p-3 text-sm text-slate-500 ring-1 ring-slate-200">
                {state.technicalStatus === "RUNNING"
                  ? "Đang chạy — chờ event của agent này…"
                  : "Chưa có event cho agent này (chọn node khác hoặc Run ticket)."}
              </p>
            )}
          </div>
          {state.finalOutput && (
            <FinalOutputWithCitations finalOutput={state.finalOutput} />
          )}
          {!state.finalOutput && ticket?.result && (
            <FinalOutputWithCitations finalOutput={ticket.result as Record<string, unknown>} />
          )}
        </section>
      </div>
    </div>
  );
}

function ConfigPage({ control: _control }: { control: InvestigationControlState }) {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Cấu hình Agent"
        subtitle="Model và soft prompt riêng cho từng agent (không dùng chung một cấu hình)."
      />
      <AgentSettingsPanel />
    </div>
  );
}

export default function Home() {
  const [activePage, setActivePage] = useState<PageKey>("dashboard");
  const [workflowTicketId, setWorkflowTicketId] = useState<string | null>(null);
  const control = useInvestigationControl();
  const activeContent = {
    dashboard: (
      <DashboardPage
        control={control}
        onGoHistory={() => setActivePage("history")}
      />
    ),
    history: (
      <HistoryPage onGoWorkflow={(ticketId) => {
        setWorkflowTicketId(ticketId);
        setActivePage("workflow");
      }} />
    ),
    workflow: <WorkflowPage key={workflowTicketId ?? "empty"} ticketId={workflowTicketId} />,
    config: <ConfigPage control={control} />,
  }[activePage];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <header className="fixed inset-x-0 top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <button onClick={() => setActivePage("dashboard")} className="flex items-center gap-3">
            <img
              src="/logo.png"
              className="size-9 rounded-xl object-cover"
              alt="AML Logo"
            />
            <span className="hidden text-base font-semibold text-slate-950 sm:block">AML-Investigator</span>
          </button>

          <nav className="mx-auto hidden items-center gap-1 rounded-xl bg-slate-50 p-1 ring-1 ring-slate-200 lg:flex">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activePage === item.key;
              return (
                <button
                  key={item.key}
                  onClick={() => setActivePage(item.key)}
                  className={cn(
                    "inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition",
                    isActive ? "bg-white text-blue-700 shadow-sm" : "text-slate-600 hover:bg-white hover:text-slate-950"
                  )}
                >
                  <Icon className="size-4" />
                  {item.label}
                </button>
              );
            })}
          </nav>

          {/* <div className="ml-auto flex items-center gap-2">
            <div className="hidden h-10 w-64 items-center gap-2 rounded-xl bg-slate-50 px-3 text-sm text-slate-600 ring-1 ring-slate-200 md:flex">
              <Search className="size-4" />
              <input className="w-full bg-transparent outline-none placeholder:text-slate-500" placeholder="Search accounts, cases" />
            </div>
            <button className="grid size-10 place-items-center rounded-xl bg-white text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50 hover:text-slate-950" aria-label="Notifications">
              <Bell className="size-5" />
            </button>
            <button className="grid size-10 place-items-center rounded-xl bg-blue-100 text-sm font-semibold text-blue-700 ring-1 ring-blue-200" aria-label="User avatar">
              AI
            </button>
          </div> */}
        </div>

        <div className="flex gap-1 overflow-x-auto border-t border-slate-100 px-4 py-2 lg:hidden">
          {navItems.map((item) => (
            <button
              key={item.key}
              onClick={() => setActivePage(item.key)}
              className={cn(
                "shrink-0 rounded-xl px-3 py-2 text-sm font-medium transition",
                activePage === item.key ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-700"
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 pb-10 pt-28 sm:px-6 lg:px-8 lg:pt-24">
        <AnimatePresence mode="wait">
          <motion.div
            key={activePage}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
          >
            {activeContent}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

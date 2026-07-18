"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactElement } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Line,
  LineChart,
} from "recharts";
import {
  Bell,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Download,
  FileText,
  Filter,
  Gauge,
  History,
  LayoutDashboard,
  Loader2,
  Network,
  RefreshCw,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  XCircle,
  Zap,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Background,
  BackgroundVariant,
  Edge,
  Handle,
  MarkerType,
  Node,
  Position,
  ReactFlow,
} from "@xyflow/react";

type PageKey = "dashboard" | "history" | "workflow" | "monitoring" | "config";
type Status = "Pending" | "Checking" | "Reject" | "Safety" | "Approve";
type AgentState = "Idle" | "Thinking" | "Working" | "Completed";

const navItems: { key: PageKey; label: string; icon: typeof LayoutDashboard }[] = [
  { key: "dashboard", label: "Trang chủ", icon: LayoutDashboard },
  { key: "history", label: "Lịch sử đáng ngờ", icon: History },
  { key: "workflow", label: "Luồng Agent", icon: Network },
  { key: "config", label: "Cấu hình Agent", icon: Settings2 },
];

const stats = [
  {
    title: "Pending",
    value: 128,
    description: "Investigations awaiting triage",
    color: "yellow",
    icon: Clock3,
  },
  {
    title: "Checking",
    value: 64,
    description: "AI agents actively reviewing",
    color: "blue",
    icon: Loader2,
  },
  {
    title: "Reject",
    value: 21,
    description: "Cases rejected after review",
    color: "red",
    icon: XCircle,
  },
  {
    title: "Approve",
    value: 312,
    description: "Cases approved and archived",
    color: "green",
    icon: CheckCircle2,
  },
];

const flowData = [
  { day: "Mon", volume: 12800, flagged: 420 },
  { day: "Tue", volume: 15200, flagged: 610 },
  { day: "Wed", volume: 14150, flagged: 520 },
  { day: "Thu", volume: 17800, flagged: 740 },
  { day: "Fri", volume: 16900, flagged: 690 },
  { day: "Sat", volume: 19400, flagged: 910 },
  { day: "Sun", volume: 21300, flagged: 860 },
];

const investigations = [
  { id: "AML-2408-1182", status: "Pending", account: "US-4830-****-9921", action: "Awaiting planner review" },
  { id: "AML-2408-1183", status: "Checking", account: "SG-1190-****-0384", action: "Tracing layered transfers" },
  { id: "AML-2408-1184", status: "Safety", account: "GB-7201-****-5509", action: "Released by KYC match" },
  { id: "AML-2408-1185", status: "Reject", account: "VN-8812-****-4402", action: "Escalated for manual review" },
  { id: "AML-2408-1186", status: "Checking", account: "DE-4408-****-7102", action: "Detecting fan-in pattern" },
  { id: "AML-2408-1187", status: "Pending", account: "US-5510-****-2208", action: "Queued for risk scoring" },
] as const;

const agents = [
  {
    name: "Planner Agent",
    status: "Thinking" as AgentState,
    health: "99.8%",
    latency: "112 ms",
    tasks: 1248,
    action: "Prioritizing suspicious clusters",
    utilization: 62,
    icon: BrainCircuit,
    data: [{ v: 14 }, { v: 18 }, { v: 16 }, { v: 24 }, { v: 23 }, { v: 30 }, { v: 28 }],
  },
  {
    name: "Transaction Agent",
    status: "Working" as AgentState,
    health: "98.6%",
    latency: "184 ms",
    tasks: 984,
    action: "Tracing fund flow across accounts",
    utilization: 78,
    icon: Network,
    data: [{ v: 20 }, { v: 22 }, { v: 18 }, { v: 27 }, { v: 31 }, { v: 29 }, { v: 35 }],
  },
  {
    name: "Report Agent",
    status: "Idle" as AgentState,
    health: "100%",
    latency: "88 ms",
    tasks: 602,
    action: "Waiting for case evidence",
    utilization: 34,
    icon: FileText,
    data: [{ v: 8 }, { v: 11 }, { v: 9 }, { v: 14 }, { v: 12 }, { v: 16 }, { v: 15 }],
  },
  {
    name: "KYC Agent",
    status: "Completed" as AgentState,
    health: "99.1%",
    latency: "136 ms",
    tasks: 1096,
    action: "Validated beneficial ownership graph",
    utilization: 55,
    icon: ShieldCheck,
    data: [{ v: 12 }, { v: 15 }, { v: 18 }, { v: 16 }, { v: 21 }, { v: 20 }, { v: 24 }],
  },
];

const activityFeed = {
  "Planner Agent": [
    ["09:42", "Fetching transaction history..."],
    ["09:43", "Prioritizing entity risk clusters..."],
    ["09:44", "Routing high-velocity accounts..."],
  ],
  "Transaction Agent": [
    ["09:41", "Tracing fund flow..."],
    ["09:43", "Detecting fan-in..."],
    ["09:45", "Calculating graph metrics..."],
  ],
  "Report Agent": [
    ["09:38", "Generating report outline..."],
    ["09:40", "Attaching evidence summary..."],
    ["09:46", "Waiting for planner approval..."],
  ],
  "KYC Agent": [
    ["09:37", "Matching beneficial owners..."],
    ["09:39", "Screening sanctions aliases..."],
    ["09:44", "Completing identity confidence score..."],
  ],
};

const modelLevels = [
  { title: "Light", description: "Fast checks for low-risk queues.", icon: Zap },
  { title: "Medium", description: "Balanced reasoning for daily review.", icon: Gauge },
  { title: "Strong", description: "Deep multi-hop analysis for escalation.", icon: Sparkles },
];

const models = ["AML-Core-v2.1", "Graph-Net-Alpha", "Velocity-Engine-X", "Reasoning-Pro"];

const statusStyles: Record<Status, string> = {
  Pending: "bg-amber-50 text-amber-700 ring-amber-200",
  Checking: "bg-blue-50 text-blue-700 ring-blue-200",
  Reject: "bg-red-50 text-red-700 ring-red-200",
  Safety: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  Approve: "bg-emerald-50 text-emerald-700 ring-emerald-200",
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

function StatCard({ item }: { item: (typeof stats)[number] }) {
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

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-3xl font-semibold tracking-normal text-slate-950">{title}</h1>
      <p className="max-w-3xl text-base leading-7 text-slate-600">{subtitle}</p>
    </div>
  );
}

function DashboardPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="AML-Investigator"
        subtitle="AI-powered Anti-Money Laundering Investigation Platform"
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((item) => (
          <StatCard key={item.title} item={item} />
        ))}
      </div>
      <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Transaction Flow Trends</h2>
            <p className="mt-1 text-sm text-slate-600">Volume and flagged transaction patterns across the current week.</p>
          </div>
          <div className="flex items-center gap-4 text-sm text-slate-600">
            <span className="flex items-center gap-2"><span className="size-2 rounded-full bg-blue-600" />Transaction Volume</span>
            <span className="flex items-center gap-2"><span className="size-2 rounded-full bg-red-500" />Flagged Transactions</span>
          </div>
        </div>
        <div className="h-[360px] w-full">
          <ResponsiveContainer>
            <AreaChart data={flowData} margin={{ left: 0, right: 12, top: 12, bottom: 0 }}>
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
              <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: "#64748B", fontSize: 12 }} />
              <YAxis axisLine={false} tickLine={false} tick={{ fill: "#64748B", fontSize: 12 }} />
              <Tooltip
                contentStyle={{ borderRadius: 12, borderColor: "#E2E8F0", boxShadow: "0 8px 24px rgba(15, 23, 42, 0.08)" }}
                formatter={(value) => (typeof value === "number" ? value.toLocaleString() : value)}
              />
              <Area type="monotone" dataKey="volume" stroke="#2563EB" strokeWidth={3} fill="url(#volume)" name="Transaction Volume" />
              <Area type="monotone" dataKey="flagged" stroke="#EF4444" strokeWidth={3} fill="url(#flagged)" name="Flagged Transactions" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}

function HistoryPage() {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <PageHeader title="Lịch sử đáng ngờ" subtitle="Review suspicious investigations." />
        <div className="flex flex-wrap gap-2">
          <div className="flex h-10 min-w-56 items-center gap-2 rounded-xl bg-white px-3 text-sm text-slate-600 ring-1 ring-slate-200">
            <Search className="size-4" />
            <input className="w-full bg-transparent outline-none placeholder:text-slate-500" placeholder="Search investigations" />
          </div>
          <button className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50">
            <Filter className="size-4" /> Filter
          </button>
          <button className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700">
            <Download className="size-4" /> Export
          </button>
        </div>
      </div>

      <section className="rounded-xl bg-white p-3 shadow-sm ring-1 ring-slate-200/70">
        <div className="hidden grid-cols-[1.2fr_1fr_1.4fr_1.6fr] px-4 py-3 text-xs font-semibold text-slate-500 md:grid">
          <span>ID</span>
          <span>Status</span>
          <span>Account Number</span>
          <span>Action</span>
        </div>
        <div className="space-y-2">
          {investigations.map((row) => (
            <button
              key={row.id}
              onClick={() => setSelected(row.id)}
              className={cn(
                "grid w-full gap-3 rounded-xl bg-slate-50 p-4 text-left transition hover:bg-blue-50/70 hover:shadow-sm md:grid-cols-[1.2fr_1fr_1.4fr_1.6fr] md:items-center",
                selected === row.id && "bg-blue-50 ring-1 ring-blue-200"
              )}
            >
              <span className="font-medium text-slate-950">{row.id}</span>
              <span>
                <span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-medium ring-1", statusStyles[row.status])}>
                  {row.status}
                </span>
              </span>
              <span className="text-sm text-slate-700">{row.account}</span>
              <span className="text-sm text-slate-600">{row.action}</span>
            </button>
          ))}
        </div>
      </section>

      {selected && (
        <motion.aside
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-blue-200"
        >
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-1 size-5 text-blue-600" />
            <div>
              <h2 className="font-semibold text-slate-950">Investigation details opened</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                {selected} is ready for analyst review with transaction graph, KYC evidence, and agent rationale.
              </p>
            </div>
          </div>
        </motion.aside>
      )}

      <div className="flex items-center justify-between text-sm text-slate-600">
        <span>Showing 1-6 of 48 cases</span>
        <div className="flex gap-2">
          <button className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200 transition hover:bg-slate-50">Previous</button>
          <button className="rounded-xl bg-blue-600 px-3 py-2 font-medium text-white">1</button>
          <button className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200 transition hover:bg-slate-50">2</button>
          <button className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200 transition hover:bg-slate-50">Next</button>
        </div>
      </div>
    </div>
  );
}

function AgentNode({ data }: { data: { name: string; status: AgentState; icon: typeof Bot } }) {
  const Icon = data.icon;

  return (
    <div className="min-w-56 rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="flex items-center gap-3">
        <div className="grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-700 ring-1 ring-blue-100">
          <Icon className="size-5" />
        </div>
        <div>
          <p className="font-semibold text-slate-950">{data.name}</p>
          <p className="text-sm text-slate-600">Status: {data.status}{data.status === "Thinking" || data.status === "Working" ? "..." : ""}</p>
        </div>
      </div>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <motion.div
          className="h-full rounded-full bg-blue-600"
          animate={{ x: ["-65%", "110%"] }}
          transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          style={{ width: "60%" }}
        />
      </div>
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

function WorkflowPage() {
  const [selected, setSelected] = useState("Planner Agent");
  const nodeTypes = useMemo(() => ({ agent: AgentNode }), []);
  const nodes = useMemo<Node[]>(
    () => [
      { id: "planner", type: "agent", position: { x: 330, y: 20 }, data: { name: "Planner Agent", status: "Thinking", icon: BrainCircuit } },
      { id: "transaction", type: "agent", position: { x: 40, y: 250 }, data: { name: "Transaction Agent", status: "Working", icon: Network } },
      { id: "report", type: "agent", position: { x: 330, y: 250 }, data: { name: "Report Agent", status: "Idle", icon: FileText } },
      { id: "kyc", type: "agent", position: { x: 620, y: 250 }, data: { name: "KYC Agent", status: "Completed", icon: ShieldCheck } },
    ],
    []
  );
  const edges = useMemo<Edge[]>(
    () => [
      { id: "p-t", source: "planner", target: "transaction", type: "smoothstep", animated: true, markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#2563EB", strokeWidth: 2 } },
      { id: "p-r", source: "planner", target: "report", type: "smoothstep", animated: true, markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#2563EB", strokeWidth: 2 } },
      { id: "p-k", source: "planner", target: "kyc", type: "smoothstep", animated: true, markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#2563EB", strokeWidth: 2 } },
    ],
    []
  );

  return (
    <div className="space-y-6">
      <PageHeader title="Luồng Agent" subtitle="Visualize how AI agents collaborate across AML investigations." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="h-[560px] overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200/70">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView proOptions={{ hideAttribution: true }} nodesDraggable={false}>
            <Background color="#CBD5E1" gap={18} variant={BackgroundVariant.Dots} />
          </ReactFlow>
        </section>
        <section className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200/70">
          <h2 className="text-lg font-semibold text-slate-950">Active Agents</h2>
          <div className="mt-4 space-y-2">
            {agents.map((agent) => {
              const Icon = agent.icon;
              const isSelected = selected === agent.name;
              return (
                <button
                  key={agent.name}
                  onClick={() => setSelected(agent.name)}
                  className={cn("w-full rounded-xl p-3 text-left transition hover:bg-slate-50", isSelected && "bg-blue-50 ring-1 ring-blue-200")}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-3 font-medium text-slate-950">
                      <Icon className="size-4 text-blue-600" /> {agent.name}
                    </span>
                    <ChevronDown className={cn("size-4 text-slate-500 transition", isSelected && "rotate-180")} />
                  </div>
                  <AnimatePresence initial={false}>
                    {isSelected && (
                      <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                        <div className="mt-4 border-t border-slate-200 pt-3">
                          <p className="text-xs font-semibold text-slate-500">Recent Actions</p>
                          <div className="mt-3 space-y-3">
                            {activityFeed[agent.name as keyof typeof activityFeed].map(([time, action]) => (
                              <div key={time + action} className="flex gap-3 text-sm">
                                <span className="font-medium text-slate-500">{time}</span>
                                <span className="text-slate-700">{action}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function MonitoringPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Agent Monitoring" subtitle="Operational health, resource utilization, and throughput across active AML agents." />
      <div className="grid gap-4 lg:grid-cols-2">
        {agents.map((agent) => {
          const Icon = agent.icon;
          return (
            <section key={agent.name} className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70 transition hover:shadow-md">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="grid size-11 place-items-center rounded-xl bg-blue-50 text-blue-700 ring-1 ring-blue-100">
                    <Icon className="size-5" />
                  </div>
                  <div>
                    <h2 className="font-semibold text-slate-950">{agent.name}</h2>
                    <p className="mt-1 text-sm text-slate-600">Agent status: {agent.status}</p>
                  </div>
                </div>
                <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">Healthy</span>
              </div>
              <div className="mt-5 grid gap-4 sm:grid-cols-3">
                <Metric label="Health" value={agent.health} />
                <Metric label="Latency" value={agent.latency} />
                <Metric label="Tasks processed" value={agent.tasks.toLocaleString()} />
              </div>
              <div className="mt-5 rounded-xl bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-700">Current action</p>
                <p className="mt-1 text-sm text-slate-600">{agent.action}</p>
                <div className="mt-4 flex items-center justify-between text-xs font-medium text-slate-500">
                  <span>Resource utilization</span>
                  <span>{agent.utilization}%</span>
                </div>
                <div className="mt-2 h-2 rounded-full bg-slate-200">
                  <div className="h-full rounded-full bg-blue-600" style={{ width: `${agent.utilization}%` }} />
                </div>
              </div>
              <div className="mt-5 h-20">
                <ResponsiveContainer>
                  <LineChart data={agent.data}>
                    <Line dataKey="v" type="monotone" stroke="#2563EB" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <button className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50">
                  <RefreshCw className="size-4" /> Restart
                </button>
                <button className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700">
                  <Download className="size-4" /> Export logs
                </button>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function ConfigPage() {
  const [level, setLevel] = useState("Medium");
  const [model, setModel] = useState("AML-Core-v2.1");

  return (
    <div className="space-y-6">
      <PageHeader title="Cấu hình Agent" subtitle="Tune system instructions, model depth, and execution model for investigation agents." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,7fr)_minmax(280px,3fr)]">
        <section className="space-y-5">
          <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
            <h2 className="text-lg font-semibold text-slate-950">Chỉnh sửa lệnh hệ thống</h2>
            <textarea
              className="mt-4 min-h-72 w-full resize-y rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-900 outline-none ring-1 ring-slate-200 transition placeholder:text-slate-500 focus:bg-white focus:ring-2 focus:ring-blue-600"
              placeholder="Enter system prompt..."
              defaultValue={"You are an AML investigation agent. Prioritize explainable risk signals, preserve audit trails, and escalate cases with layered transfers, high-velocity inflows, or inconsistent KYC evidence."}
            />
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50">
                <RefreshCw className="size-4" /> Reset
              </button>
              <button className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700">
                <Save className="size-4" /> Save Configuration
              </button>
            </div>
          </div>

          <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
            <h2 className="text-lg font-semibold text-slate-950">Model Level</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {modelLevels.map((item) => {
                const Icon = item.icon;
                const selected = level === item.title;
                return (
                  <button
                    key={item.title}
                    onClick={() => setLevel(item.title)}
                    className={cn(
                      "rounded-xl bg-slate-50 p-4 text-left ring-1 ring-slate-200 transition hover:bg-blue-50",
                      selected && "bg-white ring-2 ring-blue-600 shadow-[0_0_0_4px_rgba(37,99,235,0.10)]"
                    )}
                  >
                    <Icon className={cn("size-5", selected ? "text-blue-600" : "text-slate-500")} />
                    <p className="mt-4 font-semibold text-slate-950">{item.title}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{item.description}</p>
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        <aside className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
          <h2 className="text-lg font-semibold text-slate-950">Available Models</h2>
          <div className="mt-4 space-y-2">
            {models.map((item) => {
              const selected = model === item;
              return (
                <button
                  key={item}
                  onClick={() => setModel(item)}
                  className={cn(
                    "flex w-full items-center justify-between rounded-xl px-4 py-3 text-left text-sm font-medium transition",
                    selected ? "bg-blue-600 text-white shadow-sm" : "bg-slate-50 text-slate-700 hover:bg-blue-50 hover:text-blue-700"
                  )}
                >
                  <span>{item}</span>
                  <span className={cn("size-2.5 rounded-full", selected ? "bg-white" : "bg-slate-300")} />
                </button>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
}

const pages: Record<PageKey, () => ReactElement> = {
  dashboard: DashboardPage,
  history: HistoryPage,
  workflow: WorkflowPage,
  monitoring: MonitoringPage,
  config: ConfigPage,
};

export default function Home() {
  const [activePage, setActivePage] = useState<PageKey>("dashboard");
  const ActivePage = pages[activePage];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <header className="fixed inset-x-0 top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <button onClick={() => setActivePage("dashboard")} className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-xl bg-blue-600 text-white">
              <ShieldCheck className="size-5" />
            </span>
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

          <div className="ml-auto flex items-center gap-2">
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
          </div>
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
            <ActivePage />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

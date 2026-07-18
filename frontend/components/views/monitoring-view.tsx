"use client";

import type {LucideIcon} from "lucide-react";
import {BrainCircuit, Download, FileText, Network, RefreshCw, ShieldCheck} from "lucide-react";
import {Line, LineChart, ResponsiveContainer} from "recharts";
import {useFormatter, useTranslations} from "next-intl";
import {agents, type AgentKey} from "@/data/mock-data";
import {PageHeader} from "@/components/page-header";

const agentIcons: Record<AgentKey, LucideIcon> = {planner: BrainCircuit, transaction: Network, report: FileText, kyc: ShieldCheck};

function Metric({label, value}: {label: string; value: string}) {
  return <div><p className="text-xs font-medium text-slate-500">{label}</p><p className="mt-1 text-lg font-semibold text-slate-950">{value}</p></div>;
}

export function MonitoringView() {
  const t = useTranslations("Monitoring");
  const agentText = useTranslations("Agents");
  const state = useTranslations("AgentState");
  const format = useFormatter();

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="grid gap-4 lg:grid-cols-2">
        {agents.map((agent) => {
          const Icon = agentIcons[agent.key];
          return (
            <section key={agent.key} className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70 transition hover:shadow-md">
              <div className="flex items-start justify-between gap-3"><div className="flex items-center gap-3"><div className="grid size-11 place-items-center rounded-xl bg-blue-50 text-blue-700 ring-1 ring-blue-100"><Icon className="size-5" /></div><div><h2 className="font-semibold text-slate-950">{agentText(`${agent.key}.name`)}</h2><p className="mt-1 text-sm text-slate-600">{t("agentStatus", {status: state(agent.status.toLowerCase())})}</p></div></div><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">{t("healthy")}</span></div>
              <div className="mt-5 grid gap-4 sm:grid-cols-3"><Metric label={t("health")} value={agent.health} /><Metric label={t("latency")} value={agent.latency} /><Metric label={t("tasks")} value={format.number(agent.tasks)} /></div>
              <div className="mt-5 rounded-xl bg-slate-50 p-4"><p className="text-sm font-medium text-slate-700">{t("currentAction")}</p><p className="mt-1 text-sm text-slate-600">{agentText(`${agent.key}.action`)}</p><div className="mt-4 flex items-center justify-between text-xs font-medium text-slate-500"><span>{t("utilization")}</span><span>{format.number(agent.utilization / 100, {style: "percent"})}</span></div><div className="mt-2 h-2 rounded-full bg-slate-200"><div className="h-full rounded-full bg-blue-600" style={{width: `${agent.utilization}%`}} /></div></div>
              <div className="mt-5 h-20"><ResponsiveContainer><LineChart data={agent.data}><Line dataKey="v" type="monotone" stroke="#2563EB" strokeWidth={2.5} dot={false} /></LineChart></ResponsiveContainer></div>
              <div className="mt-5 flex flex-wrap gap-2"><button type="button" className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-slate-200"><RefreshCw className="size-4" />{t("restart")}</button><button type="button" className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white"><Download className="size-4" />{t("exportLogs")}</button></div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

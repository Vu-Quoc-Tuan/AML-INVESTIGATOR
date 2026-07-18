"use client";

import {useMemo, useState} from "react";
import type {LucideIcon} from "lucide-react";
import {Bot, BrainCircuit, ChevronDown, FileText, Network, ShieldCheck} from "lucide-react";
import {AnimatePresence, motion} from "framer-motion";
import {useTranslations} from "next-intl";
import {Background, BackgroundVariant, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps} from "@xyflow/react";
import {activityFeed, agents, type AgentKey, type AgentState} from "@/data/mock-data";
import {cn} from "@/lib/ui";
import {PageHeader} from "@/components/page-header";

const agentIcons: Record<AgentKey, LucideIcon> = {planner: BrainCircuit, transaction: Network, report: FileText, kyc: ShieldCheck};
type AgentFlowNode = Node<{agentKey: AgentKey; status: AgentState; icon: LucideIcon}, "agent">;

function AgentNode({data}: NodeProps<AgentFlowNode>) {
  const t = useTranslations("Agents");
  const status = useTranslations("AgentState");
  const Icon = data.icon || Bot;
  const active = data.status === "Thinking" || data.status === "Working";

  return (
    <div className="min-w-56 rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="flex items-center gap-3">
        <div className="grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-700 ring-1 ring-blue-100"><Icon className="size-5" /></div>
        <div><p className="font-semibold text-slate-950">{t(`${data.agentKey}.name`)}</p><p className="text-sm text-slate-600">{t("statusLabel")}: {status(data.status.toLowerCase())}{active ? "..." : ""}</p></div>
      </div>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100"><motion.div className="h-full rounded-full bg-blue-600" animate={{x: ["-65%", "110%"]}} transition={{duration: 1.4, repeat: Infinity, ease: "easeInOut"}} style={{width: "60%"}} /></div>
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

export function WorkflowView() {
  const [selected, setSelected] = useState<AgentKey>("planner");
  const t = useTranslations("Workflow");
  const agentText = useTranslations("Agents");
  const nodeTypes = useMemo(() => ({agent: AgentNode}), []);
  const nodes = useMemo<AgentFlowNode[]>(() => agents.map((agent, index) => ({
    id: agent.key,
    type: "agent",
    position: index === 0 ? {x: 330, y: 20} : {x: 40 + (index - 1) * 290, y: 250},
    data: {agentKey: agent.key, status: agent.status, icon: agentIcons[agent.key]},
  })), []);
  const edges = useMemo<Edge[]>(() => (["transaction", "report", "kyc"] as AgentKey[]).map((target) => ({id: `planner-${target}`, source: "planner", target, type: "smoothstep", animated: true, markerEnd: {type: MarkerType.ArrowClosed}, style: {stroke: "#2563EB", strokeWidth: 2}})), []);

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="h-[560px] overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200/70">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView proOptions={{hideAttribution: true}} nodesDraggable={false}><Background color="#CBD5E1" gap={18} variant={BackgroundVariant.Dots} /></ReactFlow>
        </section>
        <section className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200/70">
          <h2 className="text-lg font-semibold text-slate-950">{t("activeAgents")}</h2>
          <div className="mt-4 space-y-2">
            {agents.map((agent) => {
              const Icon = agentIcons[agent.key];
              const active = selected === agent.key;
              return (
                <button key={agent.key} type="button" onClick={() => setSelected(agent.key)} className={cn("w-full rounded-xl p-3 text-left transition hover:bg-slate-50", active && "bg-blue-50 ring-1 ring-blue-200")}>
                  <div className="flex items-center justify-between gap-3"><span className="flex items-center gap-3 font-medium text-slate-950"><Icon className="size-4 text-blue-600" />{agentText(`${agent.key}.name`)}</span><ChevronDown className={cn("size-4 text-slate-500 transition", active && "rotate-180")} /></div>
                  <AnimatePresence initial={false}>{active && <motion.div initial={{height: 0, opacity: 0}} animate={{height: "auto", opacity: 1}} exit={{height: 0, opacity: 0}} className="overflow-hidden"><div className="mt-4 border-t border-slate-200 pt-3"><p className="text-xs font-semibold text-slate-500">{t("recentActions")}</p><div className="mt-3 space-y-3">{activityFeed[agent.key].map(([time, action]) => <div key={time + action} className="flex gap-3 text-sm"><span className="font-medium text-slate-500">{time}</span><span className="text-slate-700">{t(`activity.${action}`)}</span></div>)}</div></div></motion.div>}</AnimatePresence>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

"use client";

import {useEffect, useState} from "react";
import {Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis} from "recharts";
import {CheckCircle2, Clock3, Loader2, XCircle} from "lucide-react";
import {motion} from "framer-motion";
import {useFormatter, useTranslations} from "next-intl";
import {flowData, stats} from "@/data/mock-data";
import {cn} from "@/lib/ui";
import {PageHeader} from "@/components/page-header";

const statIcons = {pending: Clock3, checking: Loader2, reject: XCircle, approve: CheckCircle2};
const palettes = {
  yellow: "bg-amber-50 text-amber-700 ring-amber-200",
  blue: "bg-blue-50 text-blue-700 ring-blue-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};
const dots = {pending: "bg-amber-400", checking: "bg-blue-500", reject: "bg-red-500", approve: "bg-emerald-500"};

function useCount(target: number) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const timer = window.setTimeout(() => setCount(target), 0);
      return () => window.clearTimeout(timer);
    }
    let frame = 0;
    const total = 42;
    const timer = window.setInterval(() => {
      frame += 1;
      setCount(Math.round(target * (1 - Math.pow(1 - frame / total, 4))));
      if (frame >= total) window.clearInterval(timer);
    }, 18);
    return () => window.clearInterval(timer);
  }, [target]);

  return count;
}

function StatCard({item}: {item: (typeof stats)[number]}) {
  const t = useTranslations("Dashboard");
  const format = useFormatter();
  const count = useCount(item.value);
  const Icon = statIcons[item.key];

  return (
    <motion.div whileHover={{y: -3}} className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70 transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between">
        <div className={cn("grid size-11 place-items-center rounded-xl ring-1", palettes[item.color])}>
          <Icon className={cn("size-5", item.key === "checking" && "animate-spin")} />
        </div>
        <span className={cn("mt-1 size-2.5 rounded-full", dots[item.key])} />
      </div>
      <div className="mt-5">
        <p className="text-sm font-medium text-slate-600">{t(`stats.${item.key}.title`)}</p>
        <p className="mt-2 text-3xl font-semibold tracking-normal text-slate-950">{format.number(count)}</p>
        <p className="mt-2 text-sm leading-6 text-slate-600">{t(`stats.${item.key}.description`)}</p>
      </div>
    </motion.div>
  );
}

export function DashboardView() {
  const t = useTranslations("Dashboard");
  const format = useFormatter();
  const chartData = flowData.map((item) => ({...item, dayLabel: t(`days.${item.day}`)}));

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((item) => <StatCard key={item.key} item={item} />)}
      </div>
      <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">{t("chart.title")}</h2>
            <p className="mt-1 text-sm text-slate-600">{t("chart.description")}</p>
          </div>
          <div className="flex items-center gap-4 text-sm text-slate-600">
            <span className="flex items-center gap-2"><span className="size-2 rounded-full bg-blue-600" />{t("chart.volume")}</span>
            <span className="flex items-center gap-2"><span className="size-2 rounded-full bg-red-500" />{t("chart.flagged")}</span>
          </div>
        </div>
        <div className="h-[360px] w-full">
          <ResponsiveContainer>
            <AreaChart data={chartData} margin={{left: 0, right: 12, top: 12, bottom: 0}}>
              <defs>
                <linearGradient id="volume" x1="0" x2="0" y1="0" y2="1"><stop offset="5%" stopColor="#2563EB" stopOpacity={0.28} /><stop offset="95%" stopColor="#2563EB" stopOpacity={0} /></linearGradient>
                <linearGradient id="flagged" x1="0" x2="0" y1="0" y2="1"><stop offset="5%" stopColor="#EF4444" stopOpacity={0.22} /><stop offset="95%" stopColor="#EF4444" stopOpacity={0} /></linearGradient>
              </defs>
              <CartesianGrid stroke="#E2E8F0" vertical={false} />
              <XAxis dataKey="dayLabel" axisLine={false} tickLine={false} tick={{fill: "#64748B", fontSize: 12}} />
              <YAxis axisLine={false} tickLine={false} tick={{fill: "#64748B", fontSize: 12}} />
              <Tooltip contentStyle={{borderRadius: 12, borderColor: "#E2E8F0", boxShadow: "0 8px 24px rgba(15, 23, 42, 0.08)"}} formatter={(value) => typeof value === "number" ? format.number(value) : value} />
              <Area type="monotone" dataKey="volume" stroke="#2563EB" strokeWidth={3} fill="url(#volume)" name={t("chart.volume")} />
              <Area type="monotone" dataKey="flagged" stroke="#EF4444" strokeWidth={3} fill="url(#flagged)" name={t("chart.flagged")} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}

"use client";

import {useState} from "react";
import {Gauge, RefreshCw, Save, Sparkles, Zap} from "lucide-react";
import {useTranslations} from "next-intl";
import {models} from "@/data/mock-data";
import {cn} from "@/lib/ui";
import {PageHeader} from "@/components/page-header";

const levels = [{key: "light", icon: Zap}, {key: "medium", icon: Gauge}, {key: "strong", icon: Sparkles}] as const;
type LevelKey = (typeof levels)[number]["key"];

export function SettingsView() {
  const [level, setLevel] = useState<LevelKey>("medium");
  const [model, setModel] = useState("AML-Core-v2.1");
  const t = useTranslations("Settings");

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,7fr)_minmax(280px,3fr)]">
        <section className="space-y-5">
          <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
            <h2 className="text-lg font-semibold text-slate-950">{t("systemPrompt.title")}</h2>
            <textarea className="mt-4 min-h-72 w-full resize-y rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-900 outline-none ring-1 ring-slate-200 transition placeholder:text-slate-500 focus:bg-white focus:ring-2 focus:ring-blue-600" placeholder={t("systemPrompt.placeholder")} defaultValue="You are an AML investigation agent. Prioritize explainable risk signals, preserve audit trails, and escalate cases with layered transfers, high-velocity inflows, or inconsistent KYC evidence." />
            <div className="mt-4 flex flex-wrap justify-end gap-2"><button type="button" className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-slate-200"><RefreshCw className="size-4" />{t("systemPrompt.reset")}</button><button type="button" className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white"><Save className="size-4" />{t("systemPrompt.save")}</button></div>
          </div>
          <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
            <h2 className="text-lg font-semibold text-slate-950">{t("modelLevel.title")}</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {levels.map((item) => {const Icon = item.icon; const selected = level === item.key; return <button key={item.key} type="button" onClick={() => setLevel(item.key)} className={cn("rounded-xl bg-slate-50 p-4 text-left ring-1 ring-slate-200 transition hover:bg-blue-50", selected && "bg-white ring-2 ring-blue-600 shadow-[0_0_0_4px_rgba(37,99,235,0.10)]")}><Icon className={cn("size-5", selected ? "text-blue-600" : "text-slate-500")} /><p className="mt-4 font-semibold text-slate-950">{t(`modelLevel.${item.key}.name`)}</p><p className="mt-2 text-sm leading-6 text-slate-600">{t(`modelLevel.${item.key}.description`)}</p></button>;})}
            </div>
          </div>
        </section>
        <aside className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70"><h2 className="text-lg font-semibold text-slate-950">{t("availableModels")}</h2><div className="mt-4 space-y-2">{models.map((item) => {const selected = model === item; return <button key={item} type="button" onClick={() => setModel(item)} className={cn("flex w-full items-center justify-between rounded-xl px-4 py-3 text-left text-sm font-medium transition", selected ? "bg-blue-600 text-white shadow-sm" : "bg-slate-50 text-slate-700 hover:bg-blue-50 hover:text-blue-700")}><span>{item}</span><span className={cn("size-2.5 rounded-full", selected ? "bg-white" : "bg-slate-300")} /></button>;})}</div></aside>
      </div>
    </div>
  );
}

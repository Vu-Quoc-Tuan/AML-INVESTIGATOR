"use client";

import {useState} from "react";
import {Download, Filter, Search, ShieldAlert} from "lucide-react";
import {motion} from "framer-motion";
import {useTranslations} from "next-intl";
import {investigations, statusStyles, type Status} from "@/data/mock-data";
import {cn} from "@/lib/ui";
import {PageHeader} from "@/components/page-header";

const statusKeys: Record<Status, string> = {Pending: "pending", Checking: "checking", Reject: "reject", Safety: "safety", Approve: "approve"};

export function HistoryView() {
  const [selected, setSelected] = useState<string | null>(null);
  const t = useTranslations("History");
  const status = useTranslations("Status");

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <PageHeader title={t("title")} subtitle={t("subtitle")} />
        <div className="flex flex-wrap gap-2">
          <div className="flex h-10 min-w-56 items-center gap-2 rounded-xl bg-white px-3 text-sm text-slate-600 ring-1 ring-slate-200">
            <Search className="size-4" />
            <input className="w-full bg-transparent outline-none placeholder:text-slate-500" placeholder={t("search")} aria-label={t("search")} />
          </div>
          <button type="button" className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50"><Filter className="size-4" />{t("filter")}</button>
          <button type="button" className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700"><Download className="size-4" />{t("export")}</button>
        </div>
      </div>

      <section className="rounded-xl bg-white p-3 shadow-sm ring-1 ring-slate-200/70">
        <div className="hidden grid-cols-[1.2fr_1fr_1.4fr_1.6fr] px-4 py-3 text-xs font-semibold text-slate-500 md:grid">
          <span>{t("columns.id")}</span><span>{t("columns.status")}</span><span>{t("columns.account")}</span><span>{t("columns.action")}</span>
        </div>
        <div className="space-y-2">
          {investigations.map((row) => (
            <button key={row.id} type="button" onClick={() => setSelected(row.id)} className={cn("grid w-full gap-3 rounded-xl bg-slate-50 p-4 text-left transition hover:bg-blue-50/70 hover:shadow-sm md:grid-cols-[1.2fr_1fr_1.4fr_1.6fr] md:items-center", selected === row.id && "bg-blue-50 ring-1 ring-blue-200")}>
              <span className="font-medium text-slate-950">{row.id}</span>
              <span><span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-medium ring-1", statusStyles[row.status])}>{status(statusKeys[row.status])}</span></span>
              <span className="text-sm text-slate-700">{row.account}</span>
              <span className="text-sm text-slate-600">{t(`actions.${row.actionKey}`)}</span>
            </button>
          ))}
        </div>
      </section>

      {selected && (
        <motion.aside initial={{opacity: 0, y: 8}} animate={{opacity: 1, y: 0}} className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-blue-200">
          <div className="flex items-start gap-3"><ShieldAlert className="mt-1 size-5 text-blue-600" /><div><h2 className="font-semibold text-slate-950">{t("detailsTitle")}</h2><p className="mt-1 text-sm leading-6 text-slate-600">{t("detailsDescription", {id: selected})}</p></div></div>
        </motion.aside>
      )}

      <div className="flex items-center justify-between text-sm text-slate-600">
        <span>{t("pagination.summary", {from: 1, to: 6, total: 48})}</span>
        <div className="flex gap-2"><button type="button" className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200">{t("pagination.previous")}</button><button type="button" className="rounded-xl bg-blue-600 px-3 py-2 font-medium text-white">1</button><button type="button" className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200">2</button><button type="button" className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200">{t("pagination.next")}</button></div>
      </div>
    </div>
  );
}

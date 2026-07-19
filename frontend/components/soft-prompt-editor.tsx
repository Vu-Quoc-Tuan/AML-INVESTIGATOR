"use client";

import { useState } from "react";
import { AlertCircle, Loader2, RotateCcw, Save } from "lucide-react";

import type { InvestigationControlState } from "@/hooks/use-investigation-control";

const MAX_PROMPT_LENGTH = 4_000;

export function SoftPromptEditor({
  control,
}: {
  control: InvestigationControlState;
}) {
  const { configuration, isLoading, isMutating, error } = control;
  const [draft, setDraft] = useState<string | null>(null);
  const [resetArmed, setResetArmed] = useState(false);
  const [saved, setSaved] = useState(false);

  const currentDraft = draft ?? configuration?.soft_prompt ?? "";
  const tooLong = currentDraft.length > MAX_PROMPT_LENGTH;
  const unchanged = currentDraft === (configuration?.soft_prompt ?? "");

  const save = async () => {
    const didSave = await control.saveSoftPrompt(currentDraft);
    if (!didSave) return;
    setDraft(null);
    setSaved(true);
  };

  const reset = async () => {
    if (!resetArmed) {
      setResetArmed(true);
      return;
    }
    const didReset = await control.resetSoftPrompt();
    if (!didReset) return;
    setDraft(null);
    setResetArmed(false);
    setSaved(true);
  };

  return (
    <section aria-labelledby="soft-prompt-title" className="rounded-xl bg-white p-5 ring-1 ring-slate-200">
      <div>
        <h2 id="soft-prompt-title" className="text-lg font-semibold text-slate-950">
          Additional instructions for all agents
        </h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
          Nội dung này được nối vào cuối system prompt của cả sáu agent. Base prompt bắt buộc vẫn giữ nguyên và các chỉ dẫn bổ sung không thể bỏ qua workflow hoặc safety rules.
        </p>
      </div>

      {error ? (
        <div role="alert" className="mt-4 flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      <label htmlFor="soft-prompt" className="mt-5 block text-sm font-medium text-slate-800">
        Chỉ dẫn bổ sung
      </label>
      {isLoading && !configuration ? (
        <div className="mt-2 h-40 animate-pulse rounded-xl bg-slate-100" />
      ) : (
        <textarea
          id="soft-prompt"
          value={currentDraft}
          onChange={(event) => {
            setDraft(event.target.value);
            setResetArmed(false);
            setSaved(false);
          }}
          rows={7}
          placeholder="Ví dụ: Ưu tiên phân tích rapid pass-through và nêu rõ bằng chứng theo timeline."
          className="mt-2 w-full resize-y rounded-xl bg-white px-4 py-3 text-sm leading-6 text-slate-900 ring-1 ring-slate-300 outline-none placeholder:text-slate-600 focus:ring-2 focus:ring-blue-500"
        />
      )}

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
        <p className={tooLong ? "font-medium text-red-700" : "text-slate-500"}>
          {currentDraft.length.toLocaleString("vi-VN")} / {MAX_PROMPT_LENGTH.toLocaleString("vi-VN")}
        </p>
        {saved ? <p role="status" className="font-medium text-emerald-700">Đã lưu</p> : null}
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={isMutating || isLoading || tooLong || unchanged}
          aria-busy={isMutating}
          onClick={() => void save()}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {isMutating ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
          {isMutating ? "Đang lưu…" : "Lưu chỉ dẫn"}
        </button>
        <button
          type="button"
          disabled={isMutating || isLoading || (!currentDraft && !configuration?.soft_prompt)}
          onClick={() => void reset()}
          className={`inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-medium ring-1 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 ${
            resetArmed
              ? "bg-red-50 text-red-800 ring-red-300 hover:bg-red-100"
              : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"
          }`}
        >
          <RotateCcw className="size-4" />
          {resetArmed ? "Bấm lần nữa để xác nhận" : "Reset"}
        </button>
      </div>
    </section>
  );
}

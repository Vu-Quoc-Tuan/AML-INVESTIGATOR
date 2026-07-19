"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2, Save } from "lucide-react";

import { ApiError } from "@/lib/api";
import {
  getAgentSettings,
  saveAgentSettings,
  type AgentSetting,
} from "@/lib/agent-settings";
import { listModels, type ModelItem } from "@/lib/models";

const MAX_PROMPT = 4_000;

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

type Draft = {
  model_id: string;
  soft_prompt: string;
};

export function AgentSettingsPanel() {
  const [agents, setAgents] = useState<AgentSetting[]>([]);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [activeId, setActiveId] = useState<string>("planner");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [settings, modelList] = await Promise.all([
        getAgentSettings(),
        listModels(),
      ]);
      setAgents(settings.agents);
      setModels(modelList.items);
      const nextDrafts: Record<string, Draft> = {};
      for (const agent of settings.agents) {
        nextDrafts[agent.id] = {
          model_id: agent.model_id ?? modelList.selected_id ?? modelList.items[0]?.id ?? "",
          soft_prompt: agent.soft_prompt ?? "",
        };
      }
      setDrafts(nextDrafts);
      if (settings.agents.length && !settings.agents.some((a) => a.id === activeId)) {
        setActiveId(settings.agents[0].id);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [activeId]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once on mount
  }, []);

  const active = agents.find((item) => item.id === activeId) ?? agents[0];
  const draft = active ? drafts[active.id] : null;
  const tooLong = (draft?.soft_prompt.length ?? 0) > MAX_PROMPT;

  const updateDraft = (agentId: string, patch: Partial<Draft>) => {
    setDrafts((current) => ({
      ...current,
      [agentId]: {
        model_id: current[agentId]?.model_id ?? "",
        soft_prompt: current[agentId]?.soft_prompt ?? "",
        ...patch,
      },
    }));
    setStatus(null);
  };

  const onSave = async () => {
    if (!agents.length) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const payload = agents.map((agent) => ({
        id: agent.id,
        model_id: drafts[agent.id]?.model_id || null,
        soft_prompt: drafts[agent.id]?.soft_prompt ?? null,
      }));
      const saved = await saveAgentSettings(payload);
      setAgents(saved.agents);
      setStatus("Đã lưu cấu hình theo từng agent");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Cấu hình từng Agent</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
            Chọn model và soft prompt riêng cho Planner, Transaction, KYC, Screening,
            Behavior Mapper và Report. Base prompt hệ thống vẫn giữ nguyên.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={loading || saving || tooLong}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
          Lưu tất cả
        </button>
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {status && (
        <p className="mt-4 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800 ring-1 ring-emerald-200">
          {status}
        </p>
      )}

      {loading ? (
        <div className="mt-5 h-48 animate-pulse rounded-xl bg-slate-100" />
      ) : (
        <div className="mt-5 grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
          <div className="space-y-1">
            {agents.map((agent) => {
              const selected = agent.id === (active?.id ?? activeId);
              return (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => setActiveId(agent.id)}
                  className={[
                    "w-full rounded-xl px-3 py-2.5 text-left text-sm font-medium transition",
                    selected
                      ? "bg-blue-600 text-white shadow-sm"
                      : "bg-slate-50 text-slate-700 hover:bg-blue-50 hover:text-blue-700",
                  ].join(" ")}
                >
                  {agent.label}
                </button>
              );
            })}
          </div>

          {active && draft && (
            <div className="space-y-4 rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200">
              <div>
                <label className="text-sm font-medium text-slate-800" htmlFor="agent-model">
                  Model
                </label>
                {models.length === 0 ? (
                  <p className="mt-2 text-sm text-slate-500">
                    Chưa có model trong env (API_KEY / BASE_URL / MODEL_NAME…).
                  </p>
                ) : (
                  <select
                    id="agent-model"
                    value={draft.model_id}
                    onChange={(event) =>
                      updateDraft(active.id, { model_id: event.target.value })
                    }
                    className="mt-2 w-full rounded-xl bg-white px-3 py-2.5 text-sm text-slate-900 ring-1 ring-slate-300 outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.model_name}
                      </option>
                    ))}
                  </select>
                )}
                {draft.model_id && (
                  <p className="mt-1 truncate text-xs text-slate-500">
                    {models.find((m) => m.id === draft.model_id)?.base_url}
                  </p>
                )}
              </div>

              <div>
                <label className="text-sm font-medium text-slate-800" htmlFor="agent-prompt">
                  Soft prompt (chỉ agent này)
                </label>
                <textarea
                  id="agent-prompt"
                  rows={8}
                  value={draft.soft_prompt}
                  onChange={(event) =>
                    updateDraft(active.id, { soft_prompt: event.target.value })
                  }
                  placeholder="Ví dụ: Ưu tiên rapid pass-through…"
                  className="mt-2 w-full resize-y rounded-xl bg-white px-3 py-2.5 text-sm leading-6 text-slate-900 ring-1 ring-slate-300 outline-none placeholder:text-slate-500 focus:ring-2 focus:ring-blue-500"
                />
                <p className={`mt-1 text-xs ${tooLong ? "font-medium text-red-700" : "text-slate-500"}`}>
                  {draft.soft_prompt.length.toLocaleString("vi-VN")} / {MAX_PROMPT.toLocaleString("vi-VN")}
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

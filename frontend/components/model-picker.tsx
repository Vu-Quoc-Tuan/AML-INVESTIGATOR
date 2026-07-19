"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { ApiError } from "@/lib/api";
import { listModels, selectModel, type ModelItem } from "@/lib/models";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

export function ModelPicker() {
  const [items, setItems] = useState<ModelItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listModels();
      setItems(response.items);
      setSelectedId(response.selected_id);
    } catch (err) {
      setError(errorMessage(err));
      setItems([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onSelect = async (id: string) => {
    if (id === selectedId || saving) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const response = await selectModel(id);
      setSelectedId(response.selected_id);
      setStatus(`Using ${response.selected_id} for agents`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Available Models</h2>
          <p className="mt-1 text-sm text-slate-500">
            Profiles from backend env. Applies to multi-agent runs after you select.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading || saving}
          className="inline-flex h-9 items-center gap-2 rounded-xl bg-slate-50 px-3 text-sm font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-white disabled:opacity-50"
        >
          <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && (
        <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
          {error}
        </p>
      )}
      {status && (
        <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 ring-1 ring-emerald-200">
          {status}
        </p>
      )}

      <div className="mt-4 space-y-2">
        {loading && items.length === 0 && (
          <p className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="size-4 animate-spin" /> Loading models…
          </p>
        )}
        {!loading && items.length === 0 && (
          <p className="text-sm text-slate-500">
            No models configured. Set API_KEY / BASE_URL / MODEL_NAME (and optional
            API_KEY_1 / API_URL_1 / MODEL_NAME_1) in backend/.env.
          </p>
        )}
        {items.map((item) => {
          const selected = selectedId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              disabled={saving}
              onClick={() => void onSelect(item.id)}
              className={[
                "flex w-full flex-col gap-1 rounded-xl px-4 py-3 text-left text-sm transition disabled:opacity-60",
                selected
                  ? "bg-blue-600 text-white shadow-sm"
                  : "bg-slate-50 text-slate-700 hover:bg-blue-50 hover:text-blue-700",
              ].join(" ")}
            >
              <span className="flex items-center justify-between gap-2 font-medium">
                <span className="truncate">{item.model_name}</span>
                <span
                  className={[
                    "size-2.5 shrink-0 rounded-full",
                    selected ? "bg-white" : "bg-slate-300",
                  ].join(" ")}
                />
              </span>
              <span
                className={[
                  "truncate text-xs",
                  selected ? "text-blue-100" : "text-slate-500",
                ].join(" ")}
                title={item.base_url}
              >
                {item.base_url}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

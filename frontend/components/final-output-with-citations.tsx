"use client";

import { useState } from "react";
import { BookMarked } from "lucide-react";

export interface Citation {
  id: string;
  label: string;
  source_system?: string;
  source_record_id?: string;
  relevance_note?: string;
  snippet?: string;
  evidence_ids?: string[];
  finding_ids?: string[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function normalizeCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  const out: Citation[] = [];
  value.forEach((item, index) => {
    const row = asRecord(item);
    if (!row) return;
    const label = String(row.label || row.article || `Citation ${index + 1}`);
    out.push({
      id: String(row.id || `c${index + 1}`),
      label,
      source_system: row.source_system ? String(row.source_system) : undefined,
      source_record_id: row.source_record_id
        ? String(row.source_record_id)
        : undefined,
      relevance_note: row.relevance_note
        ? String(row.relevance_note)
        : row.relevance
          ? String(row.relevance)
          : undefined,
      snippet: row.snippet ? String(row.snippet) : undefined,
      evidence_ids: Array.isArray(row.evidence_ids)
        ? row.evidence_ids.map(String)
        : undefined,
      finding_ids: Array.isArray(row.finding_ids)
        ? row.finding_ids.map(String)
        : undefined,
    });
  });
  return out;
}

/**
 * Renders final investigation text with small citation markers.
 * Hover a marker → compact popup (source / article / snippet).
 *
 * Citations come from legal RAG mappings + evidence ledger when available.
 * If the run had no legal hits, only the text is shown (no fake sources).
 */
export function FinalOutputWithCitations({
  finalOutput,
}: {
  finalOutput: Record<string, unknown>;
}) {
  const [openId, setOpenId] = useState<string | null>(null);

  const risk = finalOutput.overall_risk_level
    ? String(finalOutput.overall_risk_level)
    : null;
  const summary = finalOutput.summary ? String(finalOutput.summary) : null;
  const rationale = finalOutput.risk_rationale
    ? String(finalOutput.risk_rationale)
    : null;
  const citations = normalizeCitations(
    finalOutput.citations ?? finalOutput.legal_mappings,
  );

  return (
    <div className="mt-5 border-t border-slate-200 pt-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Kết quả cuối
      </h3>

      {risk && (
        <p className="mt-2 text-sm text-slate-700">
          Risk: <strong className="text-slate-950">{risk}</strong>
        </p>
      )}

      {summary && (
        <p className="mt-2 text-sm leading-6 text-slate-700">{summary}</p>
      )}

      {(rationale || citations.length > 0) && (
        <div className="mt-3 rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
          {rationale && (
            <p className="text-sm leading-6 text-slate-800">
              {rationale}
              {citations.length > 0 && (
                <span className="ml-1.5 inline-flex flex-wrap items-center gap-1 align-middle">
                  {citations.map((citation) => (
                    <span
                      key={citation.id}
                      className="relative inline-flex"
                      onMouseEnter={() => setOpenId(citation.id)}
                      onMouseLeave={() => setOpenId(null)}
                      onFocus={() => setOpenId(citation.id)}
                      onBlur={() => setOpenId(null)}
                    >
                      <button
                        type="button"
                        aria-label={`Citation ${citation.label}`}
                        className="inline-flex size-5 items-center justify-center rounded-full bg-violet-100 text-violet-700 ring-1 ring-violet-200 transition hover:bg-violet-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500"
                      >
                        <BookMarked className="size-3" />
                      </button>
                      {openId === citation.id && (
                        <span
                          role="tooltip"
                          className="absolute bottom-[calc(100%+6px)] left-1/2 z-30 w-72 -translate-x-1/2 rounded-xl bg-slate-950 p-3 text-left text-xs leading-5 text-slate-100 shadow-xl ring-1 ring-slate-700"
                        >
                          <span className="block font-semibold text-white">
                            {citation.label}
                          </span>
                          {citation.source_system && (
                            <span className="mt-1 block text-violet-200">
                              Source: {citation.source_system}
                            </span>
                          )}
                          {citation.source_record_id && (
                            <span className="mt-0.5 block break-all text-[10px] text-slate-400">
                              {citation.source_record_id}
                            </span>
                          )}
                          {citation.relevance_note && (
                            <span className="mt-2 block text-slate-200">
                              {citation.relevance_note}
                            </span>
                          )}
                          {citation.snippet && (
                            <span className="mt-2 block border-t border-slate-700 pt-2 text-slate-300">
                              “{citation.snippet}”
                            </span>
                          )}
                          {citation.evidence_ids && citation.evidence_ids.length > 0 && (
                            <span className="mt-2 block font-mono text-[10px] text-slate-400">
                              evidence: {citation.evidence_ids.join(", ")}
                            </span>
                          )}
                        </span>
                      )}
                    </span>
                  ))}
                </span>
              )}
            </p>
          )}

          {!rationale && citations.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {citations.map((citation) => (
                <span
                  key={citation.id}
                  className="relative inline-flex"
                  onMouseEnter={() => setOpenId(citation.id)}
                  onMouseLeave={() => setOpenId(null)}
                >
                  <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-1 text-[11px] font-medium text-violet-800 ring-1 ring-violet-200">
                    <BookMarked className="size-3" />
                    {citation.label}
                  </span>
                  {openId === citation.id && (
                    <span
                      role="tooltip"
                      className="absolute bottom-[calc(100%+6px)] left-0 z-30 w-72 rounded-xl bg-slate-950 p-3 text-left text-xs leading-5 text-slate-100 shadow-xl"
                    >
                      <span className="block font-semibold">{citation.label}</span>
                      {citation.snippet && (
                        <span className="mt-2 block text-slate-300">
                          “{citation.snippet}”
                        </span>
                      )}
                    </span>
                  )}
                </span>
              ))}
            </div>
          )}

          {citations.length === 0 && (
            <p className="mt-2 text-xs text-slate-500">
              Không có legal citation / RAG source cho run này (legal NO_DATA hoặc chưa
              map statute).
            </p>
          )}
        </div>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-800">
          Raw result JSON
        </summary>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {JSON.stringify(finalOutput, null, 2)}
        </pre>
      </details>
    </div>
  );
}

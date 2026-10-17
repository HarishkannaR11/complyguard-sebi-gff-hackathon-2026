import { useState } from "react";
import { sourceLabel } from "../../sourceLabel";
import StatusBadge from "../shared/StatusBadge";

const INTERMEDIARY_COLORS = {
  stockbroker: "bg-blue-50 text-blue-700 border-blue-200",
  depository: "bg-cyan-50 text-cyan-700 border-cyan-200",
  asset_management_company: "bg-amber-50 text-amber-700 border-amber-200",
  registrar_and_transfer_agent: "bg-teal-50 text-teal-700 border-teal-200",
  investment_adviser: "bg-purple-50 text-purple-700 border-purple-200",
  market_infrastructure_institution: "bg-rose-50 text-rose-700 border-rose-200",
};

const INTERMEDIARY_LABELS = {
  stockbroker: "Stock Broker",
  depository: "Depository",
  asset_management_company: "Asset Management Company (AMC)",
  registrar_and_transfer_agent: "RTA",
  investment_adviser: "Investment Adviser (IA)",
  market_infrastructure_institution: "Market Infrastructure Institution (MII)",
};

export default function ObligationList({ obligations, evidence, onAttachEvidence }) {
  const [expandedId, setExpandedId] = useState(null);
  const [evidenceForId, setEvidenceForId] = useState(null);
  const [draft, setDraft] = useState("");

  function submitEvidence(id) {
    if (!draft.trim()) return;
    onAttachEvidence(id, draft.trim());
    setDraft("");
    setEvidenceForId(null);
  }

  return (
    <div className="flex-1">
      <div className="flex items-baseline justify-between">
        <h2 className="text-2xl font-bold tracking-tight text-neutral-900">
          Obligations
        </h2>
        <p className="font-mono text-xs text-neutral-400">
          {obligations[0]?.circularName || "SEBI Circular"}
        </p>
      </div>
      <p className="mt-2 text-sm text-neutral-500">
        Extracted compliance obligations checklist across securities market intermediaries.
        Click a row to see the exact source text and attach fulfillment evidence.
      </p>

      <div className="mt-6 space-y-4">
        {obligations.map((ob) => {
          const isOpen = expandedId === ob.id;
          const obEvidence = evidence.filter((e) => e.obligationId === ob.id);
          return (
            <div key={ob.id} className="rounded-2xl border border-neutral-200 p-5">
              <button
                className="flex w-full items-start justify-between gap-4 text-left"
                onClick={() => setExpandedId(isOpen ? null : ob.id)}
              >
                <p className="text-sm font-medium text-neutral-900">
                  {ob.obligationText}
                </p>
                <StatusBadge status={ob.status} />
              </button>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                {ob.intermediary && (
                  <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-semibold ${
                    INTERMEDIARY_COLORS[ob.intermediary] || "bg-neutral-50 text-neutral-600 border-neutral-200"
                  }`}>
                    🏢 {INTERMEDIARY_LABELS[ob.intermediary] || ob.intermediary}
                  </span>
                )}
                <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-2.5 py-1 font-mono text-[11px] font-medium text-violet-700">
                  {ob.evidenceType}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-neutral-100 px-2.5 py-1 font-mono text-[11px] font-medium text-neutral-500">
                  ⏱ {ob.deadline ?? "No deadline"}
                </span>
              </div>

              {isOpen && (
                <div className="mt-4 space-y-4 border-t border-neutral-100 pt-4">
                  <div className="rounded-xl bg-neutral-50 p-4">
                    <p className="font-mono text-[11px] font-medium tracking-wide text-neutral-400">
                      SOURCE TEXT (TRACEABILITY)
                    </p>
                    {sourceLabel(ob.source) && (
                      <p className="mt-1 font-mono text-[11px] font-semibold text-violet-600">
                        {ob.circularName ? `${ob.circularName} \u00b7 ` : ""}{sourceLabel(ob.source)}
                      </p>
                    )}
                    <p className="mt-1.5 text-sm italic leading-relaxed text-neutral-600">
                      {ob.sourceChunk}
                    </p>
                  </div>

                  {obEvidence.length > 0 && (
                    <div className="space-y-2">
                      <p className="font-mono text-[11px] font-medium tracking-wide text-neutral-400">
                        EVIDENCE ON FILE
                      </p>
                      {obEvidence.map((e) => (
                        <div key={e.id} className="rounded-xl border border-neutral-200 p-3">
                          <p className="text-sm text-neutral-700">{e.description}</p>
                          <p className="mt-1 font-mono text-xs text-neutral-400">
                            Submitted {new Date(e.submittedAt).toLocaleDateString()}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}

                  {evidenceForId === ob.id ? (
                    <div className="space-y-2">
                      <textarea
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        placeholder="Describe the evidence, e.g. link or filename of the supporting document..."
                        className="w-full rounded-xl border border-neutral-200 p-3 text-sm text-neutral-900 outline-none focus:border-violet-400"
                        rows={3}
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => submitEvidence(ob.id)}
                          className="rounded-full bg-emerald-300 px-4 py-2 text-xs font-semibold text-emerald-950 hover:bg-emerald-400"
                        >
                          Submit evidence
                        </button>
                        <button
                          onClick={() => {
                            setEvidenceForId(null);
                            setDraft("");
                          }}
                          className="rounded-full px-4 py-2 text-xs font-medium text-neutral-500 hover:bg-neutral-100"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <button
                        onClick={() => setEvidenceForId(ob.id)}
                        className="rounded-full border border-neutral-200 px-4 py-2 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
                      >
                        + Attach evidence
                      </button>
                      {ob.status !== "met" && (
                        <button
                          onClick={() => onAttachEvidence(ob.id, "Verified and marked as compliant by compliance officer")}
                          className="rounded-full bg-emerald-500 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-600"
                        >
                          ✓ Mark as Met
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

import { useState, useRef } from "react";
import { CIRCULAR } from "../../data/mockData";
import { uploadCircular, importObligationsCsv, submitReviewDecision } from "../../api";

const PROCESSING_STEPS = [
  "Parsing PDF text...",
  "Chunking + generating embeddings...",
  "Retrieving relevant clauses...",
  "Extracting structured obligations...",
];

export default function UploadCircular({ onComplete, onCsvImportComplete }) {
  const [fileName, setFileName] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [showSampleNotice, setShowSampleNotice] = useState(false);
  const [pendingReviews, setPendingReviews] = useState([]);
  const timeouts = useRef([]);

  async function handleCsvUpload(file) {
    if (!file) return;
    setFileName(file.name);
    setProcessing(true);
    setStepIndex(3);
    try {
      const res = await importObligationsCsv(file);
      alert(`Successfully imported ${res.imported} obligations from CSV!`);
      // Notify parent so it can refresh readiness/gap data
      if (onCsvImportComplete) {
        onCsvImportComplete();
      } else {
        onComplete();
      }
    } catch (e) {
      console.error(e);
      alert("Failed to import CSV. Make sure it is a valid formatted CSV.");
      setProcessing(false);
    }
  }

  const updatePendingField = (threadId, field, value) => {
    setPendingReviews(prev => prev.map(p => {
      if (p.threadId === threadId) {
        return { ...p, [field]: value };
      }
      return p;
    }));
  };

  async function handleAction(threadId, actionType, itemData = null) {
    const item = pendingReviews.find(p => p.threadId === threadId);
    console.log("Selected review:", item || itemData || { threadId, actionType });

    if (!threadId || threadId === "undefined" || (item && !item.isValidId)) {
      alert("Cannot submit review decision: Missing or invalid review thread identifier.");
      return;
    }

    let decision = actionType;
    if (actionType === "amend" && itemData) {
      const payload = {
        requirement: itemData.requirement,
        frequency: itemData.frequency,
        evidence_type: itemData.evidenceType,
        deadline_rule: itemData.deadlineRule,
      };
      decision = "amend:" + JSON.stringify(payload);
    }
    
    try {
      await submitReviewDecision(threadId, decision);
      const remaining = pendingReviews.filter(p => p.threadId !== threadId);
      setPendingReviews(remaining);
      if (remaining.length === 0) {
        onComplete();
      }
    } catch (e) {
      console.error(e);
      alert("Failed to submit review decision: " + (e.message || "Make sure the backend is running."));
    }
  }

  async function startProcessing(file, fallbackName = null) {
    setShowSampleNotice(false);
    setFileName(file ? file.name : fallbackName);
    setProcessing(true);
    setStepIndex(0);
    setPendingReviews([]);
    
    PROCESSING_STEPS.forEach((_, i) => {
      const t = setTimeout(() => setStepIndex(i), (i + 1) * 800);
      timeouts.current.push(t);
    });

    try {
      const fileToUpload = file || (await fetchSampleFile());
      const data = await uploadCircular(fileToUpload);
      
      const pending = data.results.filter(r => r.status === "pending_review");
      if (pending && pending.length > 0) {
        timeouts.current.forEach(t => clearTimeout(t));
        setProcessing(false);
        setPendingReviews(pending.map(p => {
          const resolvedThreadId = p.thread_id || p.id || (data.circular_id && p.clause_id ? `${data.circular_id}:${p.clause_id}` : null);
          const isValidId = Boolean(resolvedThreadId && typeof resolvedThreadId === "string" && resolvedThreadId.trim() !== "" && resolvedThreadId !== "undefined");
          return {
            threadId: resolvedThreadId,
            isValidId,
            clauseId: p.clause_id,
            clauseText: p.clause_text,
            diffStatus: p.diff_status,
            requirement: p.extracted_obligation?.requirement || "",
            frequency: p.extracted_obligation?.frequency || "one-time",
            evidenceType: p.extracted_obligation?.evidence_type || "",
            deadlineRule: p.extracted_obligation?.deadline_rule || "",
          };
        }));
      } else {
        onComplete();
      }
    } catch (e) {
      console.error(e);
      alert("Failed to process circular. Make sure the backend is running.");
      setProcessing(false);
    }
  }

  async function fetchSampleFile() {
    const res = await fetch(CIRCULAR.file);
    const blob = await res.blob();
    return new File([blob], `${CIRCULAR.name}.pdf`, { type: "application/pdf" });
  }

  function useSample() {
    startProcessing(null, `${CIRCULAR.name}.pdf`);
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files?.[0]) {
      startProcessing(e.dataTransfer.files[0]);
    }
  }

  function handlePick(e) {
    if (e.target.files?.[0]) {
      startProcessing(e.target.files[0]);
    }
  }

  if (pendingReviews.length > 0) {
    return (
      <div className="flex-1">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-50">
            <span className="text-xl font-bold text-amber-700">⚖️</span>
          </div>
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-neutral-900">
              Human-in-the-Loop Review
            </h2>
            <p className="text-sm text-neutral-500 mt-0.5">
              {pendingReviews.length} circular clause(s) require compliance translation approval.
            </p>
          </div>
        </div>

        <div className="mt-8 space-y-8">
          {pendingReviews.map((item) => (
            <div key={item.threadId} className="rounded-2xl border border-neutral-200 p-6 bg-white shadow-sm">
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-mono text-xs font-semibold tracking-wider text-amber-700 uppercase bg-amber-50 px-2.5 py-1 rounded-full border border-amber-100">
                  {item.diffStatus === "amended" ? "⚠️ Amended Clause (Matches existing task)" : "📝 New Obligation"}
                </span>
                <span className="font-mono text-[10px] text-neutral-400">
                  Thread ID: {item.threadId}
                </span>
              </div>

              <div className="mt-4 rounded-xl bg-neutral-50 p-4 border border-neutral-100">
                <p className="font-mono text-[11px] font-medium tracking-wide text-neutral-400">
                  SEBI CIRCULAR CLAUSE TEXT
                </p>
                <p className="mt-1.5 text-sm italic leading-relaxed text-neutral-600">
                  {item.clauseText}
                </p>
              </div>

              <div className="mt-6 space-y-4">
                <p className="font-mono text-[11px] font-medium tracking-wide text-neutral-400">
                  TRANSLATED REGULATORY RULES (EDITABLE)
                </p>

                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-semibold text-neutral-600 mb-1">
                      Compliance Obligation Requirement
                    </label>
                    <textarea
                      value={item.requirement}
                      onChange={(e) => updatePendingField(item.threadId, "requirement", e.target.value)}
                      className="w-full rounded-xl border border-neutral-200 p-3 text-sm text-neutral-900 outline-none focus:border-violet-400"
                      rows={3}
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs font-semibold text-neutral-600 mb-1">
                        Frequency
                      </label>
                      <select
                        value={item.frequency}
                        onChange={(e) => updatePendingField(item.threadId, "frequency", e.target.value)}
                        className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm text-neutral-900 outline-none focus:border-violet-400 bg-white"
                      >
                        <option value="daily">Daily</option>
                        <option value="monthly">Monthly</option>
                        <option value="quarterly">Quarterly</option>
                        <option value="half-yearly">Half-Yearly</option>
                        <option value="annual">Annual</option>
                        <option value="one-time">One-Time</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-neutral-600 mb-1">
                        Evidence Required
                      </label>
                      <input
                        type="text"
                        value={item.evidenceType}
                        onChange={(e) => updatePendingField(item.threadId, "evidenceType", e.target.value)}
                        className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm text-neutral-900 outline-none focus:border-violet-400"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-neutral-600 mb-1">
                        Deadline Rule (Days / Recurrence)
                      </label>
                      <input
                        type="text"
                        value={item.deadlineRule}
                        onChange={(e) => updatePendingField(item.threadId, "deadlineRule", e.target.value)}
                        className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm text-neutral-900 outline-none focus:border-violet-400"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {!item.isValidId && (
                <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700">
                  ⚠️ Invalid or missing review thread ID. Decision submission is disabled for this item.
                </div>
              )}

              <div className="mt-6 flex flex-wrap gap-3 border-t border-neutral-100 pt-4">
                <button
                  onClick={() => handleAction(item.threadId, "approve")}
                  disabled={!item.isValidId}
                  className={`rounded-full px-6 py-2.5 text-xs font-semibold text-white transition-colors ${
                    !item.isValidId ? "bg-neutral-300 cursor-not-allowed opacity-50" : "bg-emerald-500 hover:bg-emerald-600"
                  }`}
                >
                  ✓ Approve Translation
                </button>
                <button
                  onClick={() => handleAction(item.threadId, "amend", item)}
                  disabled={!item.isValidId}
                  className={`rounded-full px-6 py-2.5 text-xs font-semibold text-white transition-colors ${
                    !item.isValidId ? "bg-neutral-300 cursor-not-allowed opacity-50" : "bg-violet-600 hover:bg-violet-700"
                  }`}
                >
                  Save & Apply Amendments
                </button>
                <button
                  onClick={() => handleAction(item.threadId, "reject")}
                  disabled={!item.isValidId}
                  className={`rounded-full border px-6 py-2.5 text-xs font-semibold transition-colors ${
                    !item.isValidId
                      ? "border-neutral-200 bg-neutral-100 text-neutral-400 cursor-not-allowed opacity-50"
                      : "border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50"
                  }`}
                >
                  ✗ Discard Requirement
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1">
      <h2 className="text-2xl font-bold tracking-tight text-neutral-900">
        Upload a circular
      </h2>
      <p className="mt-2 text-sm text-neutral-500">
        This prototype is wired up end-to-end for one document only.
      </p>

      {!processing && (
        <>
          <div className="mt-8 rounded-2xl border border-violet-200 bg-violet-50/40 p-8 text-center">
            <p className="font-mono text-xs font-medium tracking-wide text-violet-700">
              SAMPLE CIRCULAR
            </p>
            <p className="mt-1.5 text-lg font-semibold text-neutral-900">
              {CIRCULAR.name}
            </p>
            <p className="mt-1 text-sm text-neutral-500">
              {CIRCULAR.pages} pages · {CIRCULAR.intermediary}
            </p>
            <button
              onClick={useSample}
              className="mt-6 rounded-full bg-emerald-300 px-8 py-3.5 text-base font-semibold text-emerald-950 transition-colors hover:bg-emerald-400"
            >
              Run the pipeline on this circular →
            </button>
          </div>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`mt-4 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
              dragOver ? "border-violet-400 bg-violet-50/40" : "border-neutral-200"
            }`}
          >
            <p className="text-sm text-neutral-400">
              Or drag and drop your own circular PDF, or{" "}
              <label className="cursor-pointer text-violet-700 underline underline-offset-2 hover:text-violet-900">
                choose a file
                <input type="file" accept="application/pdf" className="hidden" onChange={handlePick} />
              </label>
            </p>

            {showSampleNotice && (
              <p className="mt-4 max-w-sm rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
                You can now upload a real PDF and the backend will process it.
              </p>
            )}
          </div>

          <div
            className="mt-6 flex flex-col items-center justify-center rounded-2xl border border-dashed border-emerald-300 bg-emerald-50/10 px-6 py-6 text-center"
          >
            <p className="text-sm font-semibold text-neutral-800">
              📊 Have existing company data?
            </p>
            <p className="mt-1 text-xs text-neutral-500 max-w-md">
              Upload a CSV file containing <code>requirement, frequency, evidence_type, deadline_rule, owner, due_date</code> columns to instantly import obligations.
            </p>
            <label className="mt-4 cursor-pointer rounded-full bg-emerald-500 px-6 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-emerald-600">
              Select Company CSV
              <input type="file" accept=".csv" className="hidden" onChange={(e) => {
                if (e.target.files?.[0]) {
                  handleCsvUpload(e.target.files[0]);
                }
                e.target.value = "";
              }} />
            </label>
          </div>
        </>
      )}

      {processing && (
        <div className="mt-8 rounded-2xl border border-neutral-200 p-8">
          <p className="font-mono text-sm font-medium text-neutral-900">{fileName}</p>
          <div className="mt-6 space-y-3">
            {PROCESSING_STEPS.map((label, i) => {
              const active = i === stepIndex;
              return (
                <div key={label} className="flex items-center gap-3">
                  <div
                    className={`h-2 w-2 flex-shrink-0 rounded-full ${
                      i <= stepIndex ? "bg-violet-600" : "bg-neutral-200"
                    } ${active ? "animate-pulse" : ""}`}
                  />
                  <p
                    className={`font-mono text-sm ${
                      i <= stepIndex ? "text-neutral-900" : "text-neutral-300"
                    }`}
                  >
                    {label}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

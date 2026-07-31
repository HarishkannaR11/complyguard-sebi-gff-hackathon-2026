/**
 * RegComplete.jsx
 * Shown after all pending human reviews are resolved.
 * User chooses: "Finish" (regulatory baseline only) OR
 *               "Continue to Compliance Analysis" (import CSV + gap analysis).
 */
import { useState } from "react";
import { finishWorkflow, startComplianceWorkflow, importObligationsCsv } from "../../api";

export default function RegComplete({ stats = {}, onFinish, onContinue }) {
  const [mode, setMode] = useState(null); // null | "finish" | "compliance"
  const [loading, setLoading] = useState(false);
  const [csvImporting, setCsvImporting] = useState(false);

  async function handleFinish() {
    setLoading(true);
    try {
      await finishWorkflow();
      onFinish();
    } catch (e) {
      console.error(e);
      alert("Failed to save regulatory baseline. Check backend.");
    } finally {
      setLoading(false);
    }
  }

  async function handleContinue() {
    setLoading(true);
    try {
      await startComplianceWorkflow();
      setMode("compliance");
    } catch (e) {
      console.error(e);
      alert("Failed to start compliance workflow. Check backend.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCsvUpload(file) {
    if (!file) return;
    setCsvImporting(true);
    try {
      const res = await importObligationsCsv(file);
      onContinue(res);
    } catch (e) {
      console.error(e);
      alert("Failed to import CSV. Please check the file format.");
    } finally {
      setCsvImporting(false);
    }
  }

  return (
    <div className="flex-1 max-w-2xl mx-auto">
      {/* Success banner */}
      <div className="flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-5 py-4">
        <span className="text-2xl">✓</span>
        <div>
          <p className="font-semibold text-emerald-900">Regulatory Extraction Completed</p>
          <p className="mt-0.5 text-sm text-emerald-700">
            {stats.approved ?? 0} obligation{stats.approved !== 1 ? "s" : ""} extracted and approved
            {stats.circular_id ? ` from "${stats.circular_id}"` : ""}.
          </p>
        </div>
      </div>

      {mode === null && (
        <>
          <h2 className="mt-8 text-xl font-bold text-neutral-900">What would you like to do?</h2>
          <p className="mt-1 text-sm text-neutral-500">
            The regulatory obligations are ready. Choose an option below.
          </p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {/* Option A – Finish */}
            <button
              onClick={handleFinish}
              disabled={loading}
              className="rounded-2xl border border-neutral-200 bg-white p-6 text-left transition-all hover:border-violet-300 hover:shadow-md disabled:opacity-50"
            >
              <span className="text-2xl">📁</span>
              <h3 className="mt-3 font-bold text-neutral-900">Finish</h3>
              <p className="mt-1 text-sm text-neutral-500 leading-relaxed">
                Save the approved regulatory obligations as your compliance knowledge base. No company data needed.
              </p>
              <span className="mt-4 inline-block rounded-full bg-violet-600 px-4 py-1.5 text-xs font-semibold text-white">
                {loading ? "Saving…" : "Save Regulatory Baseline →"}
              </span>
            </button>

            {/* Option B – Continue to Compliance */}
            <button
              onClick={handleContinue}
              disabled={loading}
              className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-6 text-left transition-all hover:border-emerald-400 hover:shadow-md disabled:opacity-50"
            >
              <span className="text-2xl">📊</span>
              <h3 className="mt-3 font-bold text-neutral-900">Continue to Compliance Analysis</h3>
              <p className="mt-1 text-sm text-neutral-500 leading-relaxed">
                Import your company obligations CSV and run a gap analysis to identify missing, overdue, and extra requirements.
              </p>
              <span className="mt-4 inline-block rounded-full bg-emerald-500 px-4 py-1.5 text-xs font-semibold text-white">
                {loading ? "Setting up…" : "Upload Company CSV →"}
              </span>
            </button>
          </div>

          <p className="mt-6 text-center text-xs text-neutral-400">
            You can always run Compliance Analysis later from the Review Workspace.
          </p>
        </>
      )}

      {mode === "compliance" && (
        <div className="mt-8">
          <h2 className="text-xl font-bold text-neutral-900">Upload Company Compliance Register</h2>
          <p className="mt-1 text-sm text-neutral-500">
            Upload a CSV with columns: <code className="bg-neutral-100 px-1 rounded">requirement, frequency, evidence_type, deadline_rule, owner, due_date</code>
          </p>

          <div className="mt-6 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-emerald-300 bg-emerald-50/20 px-6 py-12 text-center">
            <span className="text-4xl mb-4">📂</span>
            {csvImporting ? (
              <div className="space-y-2">
                <p className="font-semibold text-neutral-700 animate-pulse">Importing obligations…</p>
                <p className="text-xs text-neutral-400">This may take a moment.</p>
              </div>
            ) : (
              <>
                <p className="text-sm text-neutral-500">Drag and drop your CSV file, or click to select.</p>
                <label className="mt-4 cursor-pointer rounded-full bg-emerald-500 px-6 py-2.5 text-xs font-semibold text-white hover:bg-emerald-600 transition-colors">
                  Select Company CSV
                  <input
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files?.[0]) handleCsvUpload(e.target.files[0]);
                      e.target.value = "";
                    }}
                  />
                </label>
              </>
            )}
          </div>

          <button
            onClick={() => setMode(null)}
            className="mt-4 text-xs text-neutral-400 underline hover:text-neutral-700"
          >
            ← Back to options
          </button>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from "react";
import { getReviewQueue, submitReviewAction } from "../../api";

export default function ReviewWorkspace() {
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchQueue = async () => {
    try {
      setLoading(true);
      const data = await getReviewQueue();
      setQueue(data.map(item => ({
        ...item,
        requirement: item.extracted_obligation?.requirement || "",
        frequency: item.extracted_obligation?.frequency || "monthly",
        evidenceType: item.extracted_obligation?.evidence_type || "",
        deadlineRule: item.extracted_obligation?.deadline_rule || ""
      })));
      setError(null);
    } catch (err) {
      console.error(err);
      setError("Failed to fetch pending reviews. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  const updateField = (id, field, value) => {
    setQueue(prev => prev.map(item => {
      if (item.id === id) {
        return { ...item, [field]: value };
      }
      return item;
    }));
  };

  const handleAction = async (id, action) => {
    const item = queue.find(q => q.id === id);
    if (!item) return;

    try {
      const obligationData = {
        requirement: item.requirement,
        frequency: item.frequency,
        evidence_type: item.evidenceType,
        deadline_rule: item.deadlineRule,
        // Carry forward confidence scores
        deadline_confidence: item.extracted_obligation?.deadline_confidence || 1.0,
        entity_confidence: item.extracted_obligation?.entity_confidence || 1.0,
        evidence_confidence: item.extracted_obligation?.evidence_confidence || 1.0,
        overall_confidence: item.extracted_obligation?.overall_confidence || 1.0
      };

      await submitReviewAction(id, action, obligationData);
      
      // Remove from visual queue list immediately
      setQueue(prev => prev.filter(q => q.id !== id));
    } catch (err) {
      console.error(err);
      alert("Failed to submit review decision.");
    }
  };

  if (loading) {
    return (
      <div className="flex-1 py-12 text-center">
        <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-violet-700 border-r-transparent align-[-0.125em]" />
        <p className="mt-4 text-sm text-neutral-500">Loading pending reviews...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 py-8">
        <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-red-800">
          <p className="font-semibold">⚠️ Connection Error</p>
          <p className="mt-1 text-sm">{error}</p>
          <button
            onClick={fetchQueue}
            className="mt-4 rounded-full bg-red-600 px-5 py-2 text-xs font-semibold text-white transition-colors hover:bg-red-700"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  if (queue.length === 0) {
    return (
      <div className="flex-1 text-center py-16 bg-neutral-50/50 rounded-3xl border border-neutral-100 p-8 shadow-sm">
        <div className="flex justify-center text-4xl mb-4">🎉</div>
        <h3 className="text-xl font-bold text-neutral-800">No Review Tasks Outstanding</h3>
        <p className="mt-1.5 text-sm text-neutral-400 max-w-sm mx-auto">
          All clauses have been translated, checked against validation checks, and successfully processed.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1">
      <div className="flex items-center justify-between border-b border-neutral-100 pb-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-neutral-900">
            Compliance Review Queue
          </h2>
          <p className="text-sm text-neutral-500 mt-1">
            Review layout splits, visual comparisons, and translate parsed rules into obligations.
          </p>
        </div>
        <span className="rounded-full bg-amber-50 border border-amber-100 text-amber-800 px-3.5 py-1 text-xs font-semibold">
          {queue.length} pending review{queue.length > 1 ? "s" : ""}
        </span>
      </div>

      <div className="mt-8 space-y-10">
        {queue.map((item) => {
          const overallConf = item.confidence || 0.0;
          const confPercent = Math.round(overallConf * 100);
          
          return (
            <div
              key={item.id}
              className="rounded-3xl border border-neutral-200 p-6 bg-white shadow-sm transition-all duration-300 hover:shadow-md"
            >
              {/* Header Info */}
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-neutral-100 pb-4 mb-5">
                <div className="flex items-center gap-2.5">
                  <span className="font-mono text-xs font-semibold tracking-wider text-amber-700 bg-amber-50 px-3 py-1 rounded-full border border-amber-100">
                    PENDING APPROVAL
                  </span>
                  <span className="font-mono text-xs text-neutral-500 font-semibold bg-neutral-100 px-3 py-1 rounded-full">
                    {item.circular_id}
                  </span>
                </div>
                <span className="font-mono text-[10px] text-neutral-400">
                  Thread: {item.id}
                </span>
              </div>

              {/* Clause Side-by-Side */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-5">
                <div className="rounded-2xl border border-neutral-100 bg-neutral-50/50 p-4">
                  <p className="font-mono text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
                    Historical Matching Clause
                  </p>
                  <p className="mt-2 text-sm italic leading-relaxed text-neutral-500">
                    {item.previous_clause || "No previous clause matched. This represents a completely new obligation."}
                  </p>
                </div>

                <div className="rounded-2xl border border-neutral-100 bg-neutral-50/50 p-4">
                  <p className="font-mono text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
                    Incoming New Clause
                  </p>
                  <p className="mt-2 text-sm italic leading-relaxed text-neutral-600">
                    {item.new_clause}
                  </p>
                </div>
              </div>

              {/* Highlighted Differences */}
              {item.previous_clause && (
                <div className="rounded-2xl border border-violet-100 bg-violet-50/20 p-4 mb-5">
                  <p className="font-mono text-[10px] font-bold text-violet-600 uppercase tracking-wider mb-2">
                    Visual Difference Highlight
                  </p>
                  <div
                    className="text-sm leading-relaxed text-neutral-700"
                    dangerouslySetInnerHTML={{ __html: item.highlighted_diff }}
                  />
                </div>
              )}

              {/* LLM Explanation & Confidence */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5 border-t border-neutral-100 pt-5 mb-6">
                <div className="md:col-span-2">
                  <p className="font-mono text-[10px] font-bold text-neutral-400 uppercase tracking-wider mb-1">
                    System Reasoning / Validation Alert
                  </p>
                  <p className="text-sm text-neutral-600 leading-relaxed font-medium">
                    {item.llm_explanation || "Analyzing clause translation metrics."}
                  </p>
                </div>

                <div className="rounded-2xl bg-neutral-50 p-4 border border-neutral-100 flex flex-col justify-center">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-mono text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
                      Confidence Score
                    </span>
                    <span className={`text-xs font-bold ${overallConf >= 0.95 ? 'text-emerald-600' : overallConf >= 0.8 ? 'text-amber-600' : 'text-rose-600'}`}>
                      {confPercent}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-neutral-200 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${overallConf >= 0.95 ? 'bg-emerald-500' : overallConf >= 0.8 ? 'bg-amber-500' : 'bg-rose-500'}`}
                      style={{ width: `${confPercent}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Editable Fields Form */}
              <div className="space-y-4 border-t border-neutral-100 pt-5">
                <p className="font-mono text-[10px] font-bold text-violet-700 uppercase tracking-wider">
                  Translated Obligations (Editable)
                </p>

                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-semibold text-neutral-500 mb-1">
                      Compliance Obligation Requirement
                    </label>
                    <textarea
                      value={item.requirement}
                      onChange={(e) => updateField(item.id, "requirement", e.target.value)}
                      className="w-full rounded-xl border border-neutral-200 p-3 text-sm text-neutral-900 outline-none focus:border-violet-500 shadow-inner"
                      rows={2}
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs font-semibold text-neutral-500 mb-1">
                        Frequency
                      </label>
                      <select
                        value={item.frequency}
                        onChange={(e) => updateField(item.id, "frequency", e.target.value)}
                        className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm text-neutral-900 outline-none focus:border-violet-500 bg-white"
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
                      <label className="block text-xs font-semibold text-neutral-500 mb-1">
                        Evidence Required
                      </label>
                      <input
                        type="text"
                        value={item.evidenceType}
                        onChange={(e) => updateField(item.id, "evidenceType", e.target.value)}
                        className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm text-neutral-900 outline-none focus:border-violet-500"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-neutral-500 mb-1">
                        Deadline Rule (ISO or Recurrence)
                      </label>
                      <input
                        type="text"
                        value={item.deadlineRule}
                        onChange={(e) => updateField(item.id, "deadlineRule", e.target.value)}
                        className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm text-neutral-900 outline-none focus:border-violet-500"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-neutral-100 pt-4">
                <button
                  onClick={() => handleAction(item.id, "approve")}
                  className="rounded-full bg-emerald-500 px-6 py-2.5 text-xs font-semibold text-white transition-all hover:bg-emerald-600 shadow-sm"
                >
                  ✓ Approve Translation
                </button>
                <button
                  onClick={() => handleAction(item.id, "edit")}
                  className="rounded-full bg-violet-600 px-6 py-2.5 text-xs font-semibold text-white transition-all hover:bg-violet-700 shadow-sm"
                >
                  Save & Apply Amendments
                </button>
                <button
                  onClick={() => handleAction(item.id, "reject")}
                  className="rounded-full border border-neutral-200 bg-white px-6 py-2.5 text-xs font-semibold text-neutral-500 transition-all hover:bg-neutral-50 hover:text-neutral-700"
                >
                  ✗ Discard Requirement
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

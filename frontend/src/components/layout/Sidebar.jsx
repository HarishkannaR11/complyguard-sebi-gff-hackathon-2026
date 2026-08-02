function daysUntil(dateStr) {
  const diff = Math.ceil(
    (new Date(dateStr) - new Date()) / (1000 * 60 * 60 * 24)
  );
  return diff;
}

export default function Sidebar({ obligations, evidence, auditLog, readiness = {}, onOpenDashboard }) {
  const open = obligations.filter((o) => o.status !== "met" && o.deadline);
  const next = open
    .map((o) => ({ ...o, days: daysUntil(o.deadline) }))
    .sort((a, b) => a.days - b.days)[0];

  const deadlineLabel = next
    ? next.days >= 0
      ? `${next.days} days left`
      : `${Math.abs(next.days)} days overdue`
    : "No open deadlines";
  const deadlineTone =
    next && next.days < 0
      ? "bg-red-50 text-red-700"
      : "bg-emerald-50 text-emerald-700";

  const gapAvailable = Boolean(readiness.gap_analysis_available);
  const hasCompany = Boolean(readiness.has_company_obligations);

  return (
    <aside className="w-full flex-shrink-0 space-y-5 lg:w-[340px]">
      <div className="rounded-2xl border border-neutral-200 p-5">
        <div
          className={`flex items-center gap-2 rounded-lg px-3 py-2 font-mono text-xs font-medium ${deadlineTone}`}
        >
          <span>⏱</span>
          <span className="tracking-tight">
            {next ? "NEXT DEADLINE" : "STATUS"}: {deadlineLabel}
          </span>
        </div>

        <dl className="mt-5 space-y-3 text-sm">
          <div className="flex items-center justify-between">
            <dt className="text-neutral-500">Circular</dt>
            <dd className="max-w-[180px] truncate text-right font-medium text-neutral-900">
              {obligations[0]?.circularName || "No active circular"}
            </dd>
          </div>
          <div className="flex items-center justify-between border-t border-neutral-100 pt-3">
            <dt className="text-neutral-500">Regulatory Obligations</dt>
            <dd className="font-mono font-medium text-neutral-900">
              {obligations.filter(o => o.sourceType !== "company").length || obligations.length}
            </dd>
          </div>
          <div className="flex items-center justify-between border-t border-neutral-100 pt-3">
            <dt className="text-neutral-500">Evidence Filed</dt>
            <dd className="font-mono font-medium text-neutral-900">
              {evidence.length}
            </dd>
          </div>
        </dl>

        <p className="mt-5 border-t border-neutral-100 pt-4 font-mono text-xs text-neutral-400">
          {auditLog.length} audit log entries
        </p>

        {/* Gap Dashboard CTA — gated on company data */}
        {gapAvailable ? (
          <button
            onClick={onOpenDashboard}
            className="mt-5 flex w-full items-center justify-center gap-1.5 rounded-full bg-emerald-300 px-4 py-2.5 text-sm font-semibold text-emerald-950 transition-colors hover:bg-emerald-400"
          >
            Open Gap Dashboard
            <span>→</span>
          </button>
        ) : (
          <div className="mt-5 rounded-xl border border-neutral-100 bg-neutral-50 p-4">
            <p className="font-mono text-[10px] font-bold text-amber-600 uppercase tracking-wider mb-1.5">
              Gap Analysis Locked
            </p>
            <p className="text-xs text-neutral-500 leading-relaxed">
              {hasCompany
                ? "Upload a SEBI circular to enable gap analysis."
                : "Upload your company obligations CSV to compare against regulatory requirements and unlock the Gap Dashboard."}
            </p>
            <button
              disabled
              className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-full bg-neutral-200 px-4 py-2.5 text-sm font-semibold text-neutral-400 cursor-not-allowed"
            >
              Open Gap Dashboard
              <span>→</span>
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

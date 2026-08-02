import { useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// GapDashboard — shows gap analysis results from the Gap Engine.
// Props:
//   gapData    – result of GET /gaps (null if no company data yet)
//   readiness  – { has_regulatory_obligations, has_company_obligations, gap_analysis_available }
//   obligations – regulatory obligation list (for legacy reference)
//   onSelectObligation – callback when an item is clicked
// ─────────────────────────────────────────────────────────────────────────────

export default function GapDashboard({ gapData, readiness = {}, onSelectObligation }) {
  const [activeTab, setActiveTab] = useState("missing");

  // No company data yet — show informational placeholder
  if (!readiness.gap_analysis_available || !gapData) {
    const hasRegulatory = readiness.has_regulatory_obligations;
    const hasCompany = readiness.has_company_obligations;

    return (
      <div className="flex-1 space-y-6">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-neutral-900">
            Compliance Gap Dashboard
          </h2>
          <p className="mt-1 text-sm text-neutral-500">
            Compare regulatory obligations against your company obligations.
          </p>
        </div>

        <div className="rounded-3xl border border-amber-100 bg-amber-50/40 p-10 text-center">
          <div className="flex justify-center text-4xl mb-4">📋</div>
          <h3 className="text-lg font-bold text-neutral-800">
            {!hasRegulatory
              ? "Upload a SEBI Circular First"
              : !hasCompany
              ? "Upload Your Company Obligations to Begin Gap Analysis"
              : "Running Gap Analysis..."}
          </h3>
          <p className="mt-2 text-sm text-neutral-500 max-w-md mx-auto leading-relaxed">
            {!hasRegulatory
              ? "Go to Upload Circular and process a SEBI circular. Once regulatory obligations are extracted and approved, return here to upload your company obligations."
              : "Upload your company obligations CSV to compare against the extracted regulatory obligations. The Gap Engine will identify missing, extra, and fulfilled requirements — and compute your compliance score."}
          </p>

          <div className="mt-8 flex justify-center gap-6 text-sm">
            <Step
              num="1"
              label="Upload SEBI Circular"
              done={hasRegulatory}
            />
            <div className="mt-4 text-neutral-300 font-bold">→</div>
            <Step
              num="2"
              label="Import Company CSV"
              done={hasCompany}
            />
            <div className="mt-4 text-neutral-300 font-bold">→</div>
            <Step
              num="3"
              label="View Gap Analysis"
              done={false}
            />
          </div>
        </div>

        {/* Grayed-out metric previews */}
        <div className="grid gap-4 md:grid-cols-4 opacity-30 pointer-events-none select-none">
          {["Compliance Score", "Missing Obligations", "Overdue Gaps", "Extra Company Obligations"].map(label => (
            <div key={label} className="rounded-2xl border border-neutral-200 bg-neutral-50 p-5">
              <span className="text-xs font-semibold text-neutral-500 uppercase tracking-wider">{label}</span>
              <div className="mt-4 text-4xl font-black text-neutral-300">—</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Data is available ──────────────────────────────────────────────────────
  const {
    regulatory_count = 0,
    company_count = 0,
    missing = [],
    extra = [],
    met = [],
    overdue = [],
    compliance_score = 0,
  } = gapData;

  const TABS = [
    { id: "missing",  label: "Missing",  count: missing.length,  color: "rose" },
    { id: "met",      label: "Covered",  count: met.length,      color: "emerald" },
    { id: "overdue",  label: "Overdue",  count: overdue.length,  color: "amber" },
    { id: "extra",    label: "Extra",    count: extra.length,    color: "blue" },
  ];

  const tabData = { missing, met, overdue, extra };

  return (
    <div className="flex-1 space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-neutral-900">
          Compliance Gap Dashboard
        </h2>
        <p className="mt-1 text-sm text-neutral-500">
          Regulatory vs Company obligation comparison · {regulatory_count} regulatory · {company_count} company
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        {/* Compliance Score */}
        <div className="flex flex-col justify-between rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50/50 to-white p-5 shadow-xs">
          <span className="text-xs font-semibold text-violet-700 uppercase tracking-wider">Compliance Score</span>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-5xl font-black tracking-tight text-violet-950">{compliance_score}%</span>
          </div>
          <div className="mt-4">
            <div className="h-1.5 w-full rounded-full bg-violet-100">
              <div className="h-1.5 rounded-full bg-violet-600" style={{ width: `${compliance_score}%` }} />
            </div>
            <p className="mt-2 text-xs text-neutral-400 font-medium">
              {met.length} of {regulatory_count} regulatory obligations covered
            </p>
          </div>
        </div>

        {/* Missing */}
        <div className="flex flex-col justify-between rounded-2xl border border-rose-100 bg-gradient-to-br from-rose-50/30 to-white p-5 shadow-xs">
          <span className="text-xs font-semibold text-rose-700 uppercase tracking-wider">Missing</span>
          <div className="mt-4 text-5xl font-black text-rose-950">{missing.length}</div>
          <p className="mt-4 text-xs font-medium text-rose-500">
            Regulatory requirements not covered by company obligations.
          </p>
        </div>

        {/* Overdue */}
        <div className="flex flex-col justify-between rounded-2xl border border-amber-100 bg-gradient-to-br from-amber-50/30 to-white p-5 shadow-xs">
          <span className="text-xs font-semibold text-amber-700 uppercase tracking-wider">Overdue Gaps</span>
          <div className="mt-4 text-5xl font-black text-amber-950">{overdue.length}</div>
          <p className="mt-4 text-xs font-medium text-amber-600">
            Matched but past their due date — action required.
          </p>
        </div>

        {/* Extra */}
        <div className="flex flex-col justify-between rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50/30 to-white p-5 shadow-xs">
          <span className="text-xs font-semibold text-blue-700 uppercase tracking-wider">Extra</span>
          <div className="mt-4 text-5xl font-black text-blue-950">{extra.length}</div>
          <p className="mt-4 text-xs font-medium text-neutral-500">
            Company obligations with no corresponding regulatory requirement.
          </p>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="border-b border-neutral-200">
        <nav className="flex gap-0">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-5 py-3 text-xs font-semibold border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-violet-600 text-violet-700"
                  : "border-transparent text-neutral-400 hover:text-neutral-700"
              }`}
            >
              {tab.label}
              <span className={`ml-2 rounded-full px-1.5 py-0.5 font-mono text-[10px] ${
                activeTab === tab.id ? "bg-violet-100 text-violet-700" : "bg-neutral-100 text-neutral-500"
              }`}>
                {tab.count}
              </span>
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div className="space-y-3">
        {tabData[activeTab].length === 0 ? (
          <div className="rounded-2xl border border-neutral-100 bg-neutral-50 p-6 text-center text-sm text-neutral-400">
            No items in this category.
          </div>
        ) : (
          tabData[activeTab].map((item, idx) => (
            <GapItem key={item.regulatory_id || item.company_id || idx} item={item} type={activeTab} onClick={onSelectObligation} />
          ))
        )}
      </div>
    </div>
  );
}

function GapItem({ item, type, onClick }) {
  const colorMap = {
    missing:  { border: "border-rose-100",   bg: "bg-rose-50/20",   badge: "bg-rose-100 text-rose-700",    label: "MISSING" },
    met:      { border: "border-emerald-100", bg: "bg-emerald-50/10", badge: "bg-emerald-100 text-emerald-700", label: "COVERED" },
    overdue:  { border: "border-amber-100",   bg: "bg-amber-50/20",   badge: "bg-amber-100 text-amber-700",   label: "OVERDUE" },
    extra:    { border: "border-blue-100",    bg: "bg-blue-50/10",    badge: "bg-blue-100 text-blue-700",     label: "EXTRA" },
  };
  const c = colorMap[type] || colorMap.met;

  return (
    <div
      className={`rounded-2xl border ${c.border} ${c.bg} p-4 cursor-pointer hover:shadow-sm transition-shadow`}
      onClick={() => onClick && item.regulatory_id && onClick(item.regulatory_id)}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-neutral-800 line-clamp-2">
            {item.requirement || item.company_requirement || "—"}
          </p>
          {item.company_requirement && item.requirement && item.company_requirement !== item.requirement && (
            <p className="mt-1 text-xs text-neutral-400 line-clamp-1 italic">
              Company: {item.company_requirement}
            </p>
          )}
          {item.due_date && (
            <p className="mt-1 font-mono text-[10px] text-neutral-500">
              Due: {item.due_date}
            </p>
          )}
          {item.match_score !== undefined && (
            <p className="mt-1 font-mono text-[10px] text-neutral-400">
              Match: {item.match_score}%
            </p>
          )}
        </div>
        <span className={`flex-shrink-0 rounded-full px-2.5 py-1 font-mono text-[10px] font-bold ${c.badge}`}>
          {c.label}
        </span>
      </div>
    </div>
  );
}

function Step({ num, label, done }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div className={`h-9 w-9 rounded-full flex items-center justify-center text-sm font-bold ${
        done ? "bg-emerald-500 text-white" : "bg-neutral-200 text-neutral-500"
      }`}>
        {done ? "✓" : num}
      </div>
      <span className="text-xs font-medium text-neutral-500 text-center max-w-[80px]">{label}</span>
    </div>
  );
}

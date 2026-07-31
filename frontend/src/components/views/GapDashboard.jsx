import { useState } from "react";
import StatusBadge from "../shared/StatusBadge";

// Helper to determine department mapping based on intermediary or keywords
function getDepartment(ob) {
  const text = (ob.obligationText || "").toLowerCase();
  const intermediary = (ob.intermediary || "").toLowerCase();
  
  if (text.includes("net worth") || text.includes("finance") || text.includes("capital")) {
    return "Finance & Accounts";
  }
  if (text.includes("audit") || text.includes("disaster") || text.includes("bcp") || text.includes("systems")) {
    return "Risk & System Audit";
  }
  if (intermediary.includes("adviser") || text.includes("portfolio")) {
    return "Portfolio Operations";
  }
  if (text.includes("grievance") || text.includes("complaint") || text.includes("rta")) {
    return "Investor Relations";
  }
  return "Corporate Compliance";
}

// Helper to identify if an obligation is critical
function isCritical(ob) {
  const text = (ob.obligationText || "").toLowerCase();
  return (
    text.includes("must") ||
    text.includes("shall") ||
    text.includes("net worth") ||
    text.includes("disaster") ||
    text.includes("audit") ||
    text.includes("segregation")
  );
}

// Export to CSV helper
function exportToCSV(obligations) {
  const headers = ["ID", "Circular Name", "Obligation Text", "Intermediary", "Deadline", "Evidence Type", "Status", "Department", "Critical"];
  const rows = obligations.map(o => [
    o.id,
    o.circularName || "N/A",
    o.obligationText.replace(/"/g, '""'),
    o.intermediary,
    o.deadline || "N/A",
    o.evidenceType || "N/A",
    o.status.toUpperCase(),
    getDepartment(o),
    isCritical(o) ? "YES" : "NO"
  ]);
  
  const csvContent = [
    headers.join(","),
    ...rows.map(r => r.map(val => `"${val}"`).join(","))
  ].join("\n");
  
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "compliance_obligations_report.csv";
  a.click();
}

// Export to Excel XML helper
function exportToExcel(obligations) {
  let html = `
    <html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">
    <head>
      <!--[if gte mso 9]>
      <xml>
        <x:ExcelWorkbook>
          <x:ExcelWorksheets>
            <x:ExcelWorksheet>
              <x:Name>Obligations Report</x:Name>
              <x:WorksheetOptions>
                <x:DisplayGridlines/>
              </x:WorksheetOptions>
            </x:ExcelWorksheet>
          </x:ExcelWorksheets>
        </x:ExcelWorkbook>
      </xml>
      <![endif]-->
      <style>
        table { border-collapse: collapse; font-family: sans-serif; font-size: 11pt; }
        th { background-color: #6d28d9; color: white; font-weight: bold; }
        th, td { border: 1px solid #d1d5db; padding: 10px; text-align: left; }
        .critical-yes { background-color: #fef2f2; color: #991b1b; font-weight: bold; }
        .status-met { background-color: #ecfdf5; color: #065f46; }
        .status-overdue { background-color: #fef2f2; color: #991b1b; }
        .status-pending { background-color: #fffbeb; color: #92400e; }
      </style>
    </head>
    <body>
      <h2>RegOps AI - Compliance Obligations Report</h2>
      <p>Report Generated: ${new Date().toLocaleDateString()}</p>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Circular Name</th>
            <th>Obligation Text</th>
            <th>Intermediary</th>
            <th>Deadline</th>
            <th>Evidence Type</th>
            <th>Status</th>
            <th>Department</th>
            <th>Critical</th>
          </tr>
        </thead>
        <tbody>
  `;
  obligations.forEach(o => {
    const isCrit = isCritical(o);
    const critClass = isCrit ? ' class="critical-yes"' : '';
    const statusClass = ` class="status-${o.status}"`;
    html += `
      <tr>
        <td>${o.id}</td>
        <td>${o.circularName || "N/A"}</td>
        <td>${o.obligationText}</td>
        <td>${o.intermediary}</td>
        <td>${o.deadline || "N/A"}</td>
        <td>${o.evidenceType || "N/A"}</td>
        <td${statusClass}>${o.status.toUpperCase()}</td>
        <td>${getDepartment(o)}</td>
        <td${critClass}>${isCrit ? "YES" : "NO"}</td>
      </tr>
    `;
  });
  html += `
        </tbody>
      </table>
    </body>
    </html>
  `;
  const blob = new Blob([html], { type: "application/vnd.ms-excel" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "compliance_obligations_report.xls";
  a.click();
}

export default function GapDashboard({ obligations, onSelectObligation }) {
  const met = obligations.filter((o) => o.status === "met");
  const overdue = obligations.filter((o) => o.status === "overdue");
  const pending = obligations.filter((o) => o.status === "pending");
  const criticalObs = obligations.filter(isCritical);

  // Compute compliance score
  const totalCount = obligations.length;
  const complianceScore = totalCount > 0 ? Math.round((met.length / totalCount) * 100) : 0;

  // Group by circular impact
  const circularCounts = {};
  obligations.forEach(o => {
    const name = o.circularName || "Unassigned Circular";
    circularCounts[name] = (circularCounts[name] || 0) + 1;
  });

  // Group by department
  const departmentCounts = {};
  obligations.forEach(o => {
    const dept = getDepartment(o);
    departmentCounts[dept] = (departmentCounts[dept] || 0) + 1;
  });

  // Sort upcoming deadlines
  const upcomingDeadlines = obligations
    .filter(o => o.status === "pending" && o.deadline)
    .sort((a, b) => new Date(a.deadline) - new Date(b.deadline))
    .slice(0, 5);

  return (
    <div className="flex-1 space-y-8">
      {/* Header and Export controls */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-neutral-900">
            Compliance Dashboard
          </h2>
          <p className="mt-1 text-sm text-neutral-500">
            Real-time visual monitoring, version gaps, department analysis, and report exports.
          </p>
        </div>
        
        {totalCount > 0 && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => exportToCSV(obligations)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-300 bg-white px-3.5 py-2 text-xs font-semibold text-neutral-700 shadow-xs hover:bg-neutral-50"
            >
              <svg className="h-4 w-4 text-neutral-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Export CSV
            </button>
            <button
              onClick={() => exportToExcel(obligations)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-300 bg-white px-3.5 py-2 text-xs font-semibold text-neutral-700 shadow-xs hover:bg-neutral-50"
            >
              <svg className="h-4 w-4 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Export Excel
            </button>
          </div>
        )}
      </div>

      {totalCount === 0 ? (
        <div className="rounded-2xl border border-neutral-200 p-8 text-center text-neutral-500">
          <p className="text-sm">No obligations indexed in database yet.</p>
          <p className="mt-1 text-xs text-neutral-400">Please upload a SEBI circular to start extracting obligations.</p>
        </div>
      ) : (
        <>
          {/* Top Cards Grid */}
          <div className="grid gap-6 md:grid-cols-4">
            {/* Compliance Score */}
            <div className="flex flex-col justify-between rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50/50 to-white p-5 shadow-xs">
              <span className="text-xs font-semibold text-violet-700 uppercase tracking-wider">Compliance Score</span>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-5xl font-black tracking-tight text-violet-950">{complianceScore}%</span>
              </div>
              <div className="mt-4">
                <div className="h-1.5 w-full rounded-full bg-violet-100">
                  <div className="h-1.5 rounded-full bg-violet-600" style={{ width: `${complianceScore}%` }} />
                </div>
                <p className="mt-2 text-xs text-neutral-400 font-medium">
                  {met.length} of {totalCount} obligations met
                </p>
              </div>
            </div>

            {/* Overdue Obligations */}
            <div className="flex flex-col justify-between rounded-2xl border border-red-100 bg-gradient-to-br from-red-50/30 to-white p-5 shadow-xs">
              <span className="text-xs font-semibold text-red-700 uppercase tracking-wider">Overdue Gaps</span>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-5xl font-black tracking-tight text-red-950">{overdue.length}</span>
              </div>
              <p className="mt-4 text-xs font-medium text-red-500">
                Action required immediately to resolve compliance gaps.
              </p>
            </div>

            {/* Pending Obligations */}
            <div className="flex flex-col justify-between rounded-2xl border border-amber-100 bg-gradient-to-br from-amber-50/30 to-white p-5 shadow-xs">
              <span className="text-xs font-semibold text-amber-700 uppercase tracking-wider">Pending Work</span>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-5xl font-black tracking-tight text-amber-950">{pending.length}</span>
              </div>
              <p className="mt-4 text-xs font-medium text-amber-600">
                Awaiting evidence uploads before due dates.
              </p>
            </div>

            {/* Critical Obligations */}
            <div className="flex flex-col justify-between rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50/30 to-white p-5 shadow-xs">
              <span className="text-xs font-semibold text-blue-700 uppercase tracking-wider">Critical Measures</span>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-5xl font-black tracking-tight text-blue-950">{criticalObs.length}</span>
              </div>
              <p className="mt-4 text-xs font-medium text-neutral-500">
                Obligations containing legal must/shall imperatives.
              </p>
            </div>
          </div>

          {/* Detailed Lists Grid */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Overdue Tasks Section */}
            <div className="rounded-2xl border border-neutral-200 p-5 bg-white">
              <h3 className="text-sm font-semibold tracking-wide text-neutral-800 uppercase">
                Overdue Obligations ({overdue.length})
              </h3>
              <div className="mt-4 space-y-3 max-h-[300px] overflow-y-auto pr-1">
                {overdue.length === 0 ? (
                  <p className="text-xs text-neutral-400 py-2">No overdue tasks. All deadlines are intact.</p>
                ) : (
                  overdue.map(ob => (
                    <button
                      key={ob.id}
                      onClick={() => onSelectObligation(ob.id)}
                      className="w-full text-left flex items-start justify-between gap-3 rounded-xl border border-red-100 bg-red-50/10 p-3.5 hover:bg-red-50/30 transition-colors"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-semibold text-red-900 line-clamp-2">{ob.obligationText}</p>
                        <p className="mt-1 font-mono text-[10px] text-red-600 font-bold">Passed Due: {ob.deadline}</p>
                      </div>
                      <StatusBadge status="overdue" />
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* Upcoming Deadlines Section */}
            <div className="rounded-2xl border border-neutral-200 p-5 bg-white">
              <h3 className="text-sm font-semibold tracking-wide text-neutral-800 uppercase">
                Upcoming Deadlines ({pending.length})
              </h3>
              <div className="mt-4 space-y-3 max-h-[300px] overflow-y-auto pr-1">
                {upcomingDeadlines.length === 0 ? (
                  <p className="text-xs text-neutral-400 py-2">No upcoming pending deadlines found.</p>
                ) : (
                  upcomingDeadlines.map(ob => (
                    <button
                      key={ob.id}
                      onClick={() => onSelectObligation(ob.id)}
                      className="w-full text-left flex items-start justify-between gap-3 rounded-xl border border-neutral-200 p-3.5 hover:border-violet-200 hover:bg-violet-50/10 transition-all"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-semibold text-neutral-700 line-clamp-2">{ob.obligationText}</p>
                        <p className="mt-1 font-mono text-[10px] text-amber-700 font-semibold">Due: {ob.deadline}</p>
                      </div>
                      <StatusBadge status="pending" />
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Breakdown Charts Grid */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Department Breakdown */}
            <div className="rounded-2xl border border-neutral-200 p-5 bg-white">
              <h3 className="text-sm font-semibold tracking-wide text-neutral-800 uppercase">
                Department breakdown
              </h3>
              <div className="mt-6 space-y-4">
                {Object.entries(departmentCounts).map(([dept, count]) => {
                  const percent = Math.round((count / totalCount) * 100);
                  return (
                    <div key={dept} className="space-y-1.5">
                      <div className="flex justify-between text-xs">
                        <span className="font-semibold text-neutral-700">{dept}</span>
                        <span className="font-mono text-neutral-400 font-medium">{count} ({percent}%)</span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-neutral-100">
                        <div 
                          className="h-2 rounded-full bg-violet-500" 
                          style={{ width: `${percent}%` }} 
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Circular Impact Breakdown */}
            <div className="rounded-2xl border border-neutral-200 p-5 bg-white">
              <h3 className="text-sm font-semibold tracking-wide text-neutral-800 uppercase">
                Circular Impact Profile
              </h3>
              <div className="mt-6 space-y-4">
                {Object.entries(circularCounts).map(([name, count]) => {
                  const percent = Math.round((count / totalCount) * 100);
                  return (
                    <div key={name} className="space-y-1.5">
                      <div className="flex justify-between text-xs">
                        <span className="font-semibold text-neutral-700 truncate max-w-[280px]">{name}</span>
                        <span className="font-mono text-neutral-400 font-medium">{count} ({percent}%)</span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-neutral-100">
                        <div 
                          className="h-2 rounded-full bg-indigo-500" 
                          style={{ width: `${percent}%` }} 
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Completion Trend Visualization */}
          <div className="rounded-2xl border border-neutral-200 p-5 bg-white">
            <h3 className="text-sm font-semibold tracking-wide text-neutral-800 uppercase">
              Completion Trend
            </h3>
            <p className="mt-1 text-xs text-neutral-400 font-medium">
              Daily compliance progress mapping met vs. uncompleted obligations.
            </p>
            <div className="mt-6 flex h-48 items-end justify-between gap-4 border-b border-l border-neutral-200 pb-2 pl-4">
              {/* SVG Trend Line / Mock visualization */}
              <div className="flex-1 flex flex-col justify-end items-center h-full group relative">
                <div className="h-[20%] w-full rounded-t-md bg-violet-100 group-hover:bg-violet-200 transition-colors" />
                <span className="mt-2 font-mono text-[9px] text-neutral-400">Baseline</span>
              </div>
              <div className="flex-1 flex flex-col justify-end items-center h-full group relative">
                <div className="h-[40%] w-full rounded-t-md bg-violet-200 group-hover:bg-violet-300 transition-colors" />
                <span className="mt-2 font-mono text-[9px] text-neutral-400">Circular Ingestion</span>
              </div>
              <div className="flex-1 flex flex-col justify-end items-center h-full group relative">
                <div className="h-[65%] w-full rounded-t-md bg-violet-400 group-hover:bg-violet-500 transition-colors" />
                <span className="mt-2 font-mono text-[9px] text-neutral-400">Evidence Uploads</span>
              </div>
              <div className="flex-1 flex flex-col justify-end items-center h-full group relative">
                <div className="h-[85%] w-full rounded-t-md bg-violet-600 group-hover:bg-violet-700 transition-colors" style={{ height: `${complianceScore}%` }} />
                <span className="mt-2 font-mono text-[9px] text-neutral-600 font-bold">Active Status ({complianceScore}%)</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

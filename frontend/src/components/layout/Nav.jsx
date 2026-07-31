const STEPS = [
  { id: "landing", label: "Overview" },
  { id: "upload", label: "Upload" },
  { id: "review", label: "Review Workspace" },
  { id: "obligations", label: "Obligations" },
  { id: "dashboard", label: "Gap Dashboard" },
  { id: "audit", label: "Audit Trail" },
];

export default function Nav({ view, setView, unlocked }) {
  return (
    <header className="sticky top-0 z-10 bg-white">
      <div className="border-b border-neutral-200">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
          <button
            onClick={() => unlocked.includes("landing") && setView("landing")}
            className="flex items-center gap-2"
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-600 to-violet-800 text-sm font-semibold text-white">
              ◆
            </div>
            <span className="text-[15px] font-semibold tracking-tight text-neutral-900">
              RegOps AI
            </span>
          </button>
          <div className="flex items-center gap-4 font-mono text-xs text-neutral-400">
            <span>SEBI x RegOps AI</span>
            <span className="rounded-full bg-violet-50 px-2.5 py-1 font-mono text-[11px] font-medium text-violet-700">
              PROTOTYPE
            </span>
          </div>
        </div>
      </div>
      <div className="border-b border-neutral-200 bg-white">
        <nav className="mx-auto flex max-w-6xl items-center gap-6 overflow-x-auto px-6">
          {STEPS.map((step) => {
            const isUnlocked = unlocked.includes(step.id);
            const isActive = view === step.id;
            return (
              <button
                key={step.id}
                disabled={!isUnlocked}
                onClick={() => setView(step.id)}
                className={`whitespace-nowrap border-b-2 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-violet-700 text-violet-700"
                    : isUnlocked
                    ? "border-transparent text-neutral-500 hover:text-neutral-900"
                    : "cursor-not-allowed border-transparent text-neutral-300"
                }`}
              >
                {step.label}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

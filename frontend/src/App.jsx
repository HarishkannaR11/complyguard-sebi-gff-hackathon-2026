import { useEffect, useState } from "react";
import { addEvidence, getAuditLog, getEvidence, getGapAnalysis, getObligations, getReadiness } from "./api";
import Nav from "./components/layout/Nav";
import Sidebar from "./components/layout/Sidebar";
import AuditTrail from "./components/views/AuditTrail";
import GapDashboard from "./components/views/GapDashboard";
import Hero from "./components/views/Hero";
import Landing from "./components/views/Landing";
import ObligationList from "./components/views/ObligationList";
import ReviewWorkspace from "./components/views/ReviewWorkspace";
import UploadCircular from "./components/views/UploadCircular";

// Views that are always accessible regardless of data
const BASE_VIEWS = ["landing", "upload", "review", "obligations", "audit"];
// Full view list including gap dashboard
const ALL_VIEWS = [...BASE_VIEWS, "dashboard"];

export default function App() {
  const [view, setView] = useState("landing");
  const [unlocked, setUnlocked] = useState(["landing", "upload", "review"]);
  const [obligations, setObligations] = useState([]);
  const [evidence, setEvidence] = useState([]);
  const [auditLog, setAuditLog] = useState([]);
  const [gapData, setGapData] = useState(null);

  // Readiness flags from the backend
  const [readiness, setReadiness] = useState({
    has_regulatory_obligations: false,
    has_company_obligations: false,
    gap_analysis_available: false,
  });

  const fetchReadiness = async () => {
    const r = await getReadiness();
    setReadiness(r);
    return r;
  };

  const fetchGapData = async () => {
    try {
      const data = await getGapAnalysis();
      setGapData(data.__no_company_data ? null : data);
    } catch {
      setGapData(null);
    }
  };

  const fetchData = async () => {
    try {
      const [obs, evs, logs, r] = await Promise.all([
        getObligations(),
        getEvidence(),
        getAuditLog(),
        getReadiness(),
      ]);

      setReadiness(r);

      // Unlock views based on backend readiness
      if (r.has_regulatory_obligations) {
        setUnlocked(r.gap_analysis_available ? ALL_VIEWS : BASE_VIEWS);
      } else if (obs.length > 0) {
        setUnlocked(BASE_VIEWS);
      }

      setObligations(obs.map(o => ({
        id: o.id,
        circularName: o.circular_name,
        obligationText: o.obligation_text,
        intermediary: o.intermediary,
        deadline: o.deadline,
        evidenceType: o.evidence_type,
        sourceChunk: o.source_chunk,
        source: o.source,
        status: o.status,
        sourceType: o.source_type,
      })));

      setEvidence(evs.map(e => ({
        id: e.id,
        obligationId: e.obligation_id,
        description: e.description,
        submittedAt: e.submitted_at
      })));

      setAuditLog(logs);

      // Fetch gap data only if company obligations exist
      if (r.gap_analysis_available) {
        await fetchGapData();
      }
    } catch (error) {
      console.error("Failed to fetch data (backend might not be running).", error);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  async function handleUploadComplete() {
    await fetchData();
    setView("obligations");
  }

  // Called after successful CSV import — now gap analysis becomes available
  async function handleCsvImportComplete() {
    const r = await fetchReadiness();
    if (r.gap_analysis_available) {
      setUnlocked(ALL_VIEWS);
      await fetchGapData();
    } else {
      setUnlocked(prev => Array.from(new Set([...prev, ...BASE_VIEWS])));
    }
    await fetchData();
  }

  function handleStart() {
    setUnlocked((prev) => (prev.includes("upload") ? prev : [...prev, "upload"]));
    setView("upload");
  }

  async function handleAttachEvidence(obligationId, description) {
    try {
      await addEvidence(obligationId, description);
      await fetchData();
    } catch (error) {
      console.error("Failed to add evidence:", error);
    }
  }

  function handleOpenDashboard() {
    if (readiness.gap_analysis_available) {
      setView("dashboard");
    }
  }

  return (
    <div className="min-h-screen bg-white">
      <Nav view={view} setView={setView} unlocked={unlocked} />
      {view === "landing" && <Hero onStart={handleStart} />}

      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-10 lg:flex-row">
        {view === "landing" && <Landing />}
        {view === "upload" && (
          <UploadCircular
            onComplete={handleUploadComplete}
            onCsvImportComplete={handleCsvImportComplete}
          />
        )}
        {view === "review" && <ReviewWorkspace />}
        {view === "obligations" && (
          <ObligationList
            obligations={obligations}
            evidence={evidence}
            onAttachEvidence={handleAttachEvidence}
          />
        )}
        {view === "dashboard" && (
          <GapDashboard
            gapData={gapData}
            readiness={readiness}
            obligations={obligations}
            onSelectObligation={() => setView("obligations")}
          />
        )}
        {view === "audit" && <AuditTrail log={auditLog} />}

        <Sidebar
          obligations={obligations}
          evidence={evidence}
          auditLog={auditLog}
          readiness={readiness}
          onOpenDashboard={handleOpenDashboard}
        />
      </div>

      <footer className="border-t border-neutral-100 py-8 text-center text-xs text-neutral-300">
        RegOps AI — Connects to Python FastAPI Backend.
      </footer>
    </div>
  );
}

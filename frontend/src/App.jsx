import { useState, useEffect } from "react";
import Nav from "./components/layout/Nav";
import Sidebar from "./components/layout/Sidebar";
import Hero from "./components/views/Hero";
import Landing from "./components/views/Landing";
import UploadCircular from "./components/views/UploadCircular";
import ReviewWorkspace from "./components/views/ReviewWorkspace";
import ObligationList from "./components/views/ObligationList";
import GapDashboard from "./components/views/GapDashboard";
import AuditTrail from "./components/views/AuditTrail";
import { getObligations, getEvidence, getAuditLog, addEvidence } from "./api";

const ALL_VIEWS = ["landing", "upload", "review", "obligations", "dashboard", "audit"];

export default function App() {
  const [view, setView] = useState("landing");
  const [unlocked, setUnlocked] = useState(["landing", "upload", "review"]);
  const [obligations, setObligations] = useState([]);
  const [evidence, setEvidence] = useState([]);
  const [auditLog, setAuditLog] = useState([]);

  const fetchData = async () => {
    try {
      const obs = await getObligations();
      const evs = await getEvidence();
      const logs = await getAuditLog();

      if (obs.length > 0) {
        setUnlocked(ALL_VIEWS); // data already exists from a prior run — unlock on load, not just after upload
      }

      setObligations(obs.map(o => ({
        id: o.id,
        circularName: o.circular_name,
        obligationText: o.obligation_text,
        intermediary: o.intermediary,
        deadline: o.deadline,
        evidenceType: o.evidence_type,
        sourceChunk: o.source_chunk,
        status: o.status
      })));
      
      setEvidence(evs.map(e => ({
        id: e.id,
        obligationId: e.obligation_id,
        description: e.description,
        submittedAt: e.submitted_at
      })));
      
      setAuditLog(logs);
    } catch (error) {
      console.error("Failed to fetch data (backend might not be running).", error);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  async function handleUploadComplete() {
    await fetchData();
    setUnlocked(ALL_VIEWS); // full nav available once the pipeline has "run"
    setView("obligations");
  }

  function handleStart() {
    setUnlocked((prev) => (prev.includes("upload") ? prev : [...prev, "upload"]));
    setView("upload");
  }

  async function handleAttachEvidence(obligationId, description) {
    try {
      await addEvidence(obligationId, description);
      await fetchData(); // refresh state from API
    } catch (error) {
      console.error("Failed to add evidence:", error);
    }
  }

  return (
    <div className="min-h-screen bg-white">
      <Nav view={view} setView={setView} unlocked={unlocked} />
      {view === "landing" && <Hero onStart={handleStart} />}

      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-10 lg:flex-row">
        {view === "landing" && <Landing />}
        {view === "upload" && <UploadCircular onComplete={handleUploadComplete} />}
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
            obligations={obligations}
            onSelectObligation={() => setView("obligations")}
          />
        )}
        {view === "audit" && <AuditTrail log={auditLog} />}

        <Sidebar
          obligations={obligations}
          evidence={evidence}
          auditLog={auditLog}
          onOpenDashboard={() => setView("dashboard")}
        />
      </div>

      <footer className="border-t border-neutral-100 py-8 text-center text-xs text-neutral-300">
        RegOps AI — Connects to Python FastAPI Backend.
      </footer>
    </div>
  );
}

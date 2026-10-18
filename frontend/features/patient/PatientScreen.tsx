"use client";

// The patient-facing screen. Everything the patient does is by voice; the screen only shows the
// gradient, a photo, or a few words (design.md). The nurse sets it up, and Esc brings the setup back.
import { useEffect, useState } from "react";
import { CalmStage } from "./CalmStage";
import { SetupCard } from "./SetupCard";
import { useCompanion } from "./useCompanion";
import "./calm.css";

export function PatientScreen() {
  const { status, screen, error, start, end } = useCompanion();
  const [nurseOpen, setNurseOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setNurseOpen((o) => !o); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const showSetup = status !== "live" || nurseOpen;

  return (
    <CalmStage screen={screen}>
      {showSetup && (
        <SetupCard
          live={status === "live"}
          connecting={status === "connecting"}
          error={error}
          onStart={(name, games) => { setNurseOpen(false); start(name, games); }}
          onEnd={() => { setNurseOpen(false); end(); }}
          onHide={() => setNurseOpen(false)}
        />
      )}
    </CalmStage>
  );
}

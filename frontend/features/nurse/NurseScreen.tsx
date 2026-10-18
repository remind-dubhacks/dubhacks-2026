"use client";

// Nurse dashboard (Nurse Dashboard mockup): urgent alerts, the residents, and for the one picked their sessions,
// what the companion remembers about them, their care context and consent to remember.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Participant } from "@/lib/api";
import { fetchSessions, type CompanionSession } from "@/lib/voice";
import { ResidentDetail } from "./ResidentDetail";
import { ResidentStrip } from "./ResidentStrip";
import { UrgentPanel, type Alert } from "./UrgentPanel";
import "./nurse.css";

const FONT = "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;600&display=swap";
export const GAME_NAMES: Record<string, string> = { faces: "Famous faces", proverbs: "Sayings", sounds: "Sounds", reorder: "Reorder" };

export const displayName = (p: Participant) => p.careProfile?.preferredName || p.alias;

export function NurseScreen() {
  const [residents, setResidents] = useState<Participant[]>([]);
  const [sessions, setSessions] = useState<CompanionSession[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [today, setToday] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    Promise.all([api.participants(), fetchSessions()]).then(([p, s]) => {
      setResidents(p);
      setSessions(s);
      setErr(null);
    }, () => setErr("Can't reach the backend (is it running on :8000?)"));
  }, []);

  useEffect(() => {
    setToday(new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const byId = new Map(residents.map((r) => [r._id, r]));
  const alerts: Alert[] = sessions
    .filter((s) => s.alerts.length > 0 && !s.acknowledgedAt)
    .map((s) => {
      const r = s.participantId ? byId.get(s.participantId) : undefined;
      const games = [...new Set(s.gamesPlayed)].map((g) => GAME_NAMES[g] ?? g);
      return {
        sessionId: s._id,
        participantId: r?._id ?? null,
        name: r ? r.alias : s.patientName,
        title: "Asked for help",
        detail: `${s.alerts[s.alerts.length - 1]}${games.length ? ` during ${games.join(", ")}` : ""}`,
        at: s.endedAt,
      };
    });
  const flagged = new Set(alerts.map((a) => a.participantId).filter(Boolean) as string[]);

  const open = (pid: string) => {
    setSelected(pid);
    requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };
  const acknowledge = async (sid: string) => {
    setSessions((ss) => ss.map((s) => (s._id === sid ? { ...s, acknowledgedAt: new Date().toISOString() } : s)));
    await api.acknowledge(sid).catch(load);
  };
  const updateResident = (p: Participant) => setResidents((rs) => rs.map((r) => (r._id === p._id ? p : r)));

  const resident = selected ? byId.get(selected) : undefined;
  return (
    <div className="nurse">
      <link rel="stylesheet" href={FONT} precedence="default" />
      <header className="nurse-head">
        <h1>ReMind Companion</h1>
        <span>{today}</span>
      </header>
      {err && <p className="nurse-error" role="alert">{err}</p>}

      <UrgentPanel alerts={alerts} onOpen={open} onAcknowledge={acknowledge} />
      <ResidentStrip residents={residents} selected={selected} flagged={flagged} onSelect={open} />

      <div ref={detailRef} className="nurse-panel">
        {resident ? (
          <ResidentDetail key={resident._id} resident={resident} onChange={updateResident} />
        ) : (
          <p className="nurse-empty">Select a patient to see their recent sessions.</p>
        )}
      </div>
    </div>
  );
}

"use client";

// Nurse screen: what happened in patient-screen sessions (games, engagement notes, alerts).
// Session records come from the backend; the resident list is a synthetic placeholder for the demo.
import { useEffect, useState } from "react";
import { fetchSessions, type CompanionSession } from "@/lib/voice";

const GAME_NAMES: Record<string, string> = { faces: "Famous faces", proverbs: "Sayings", sounds: "Sounds", reorder: "Reorder" };
const ENGAGEMENT: Record<string, string> = { engaged: "Engaged", some: "Some interest", withdrawn: "Withdrawn" };

// Placeholder residents (synthetic, never real patient data).
const RESIDENTS = [
  { name: "Harold", room: "12B", last: "Famous faces · engaged", when: "Yesterday" },
  { name: "Ines", room: "14", last: "Sayings · engaged", when: "Today 9:10" },
  { name: "George", room: "15", last: "Sounds · some interest", when: "Today 8:40" },
  { name: "Mabel", room: "16A", last: "Not played yet", when: "" },
  { name: "Edith", room: "18B", last: "Asked for help", when: "Today 8:55" },
];

const time = (iso: string) => new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
const minutes = (s: CompanionSession) => Math.max(1, Math.round((+new Date(s.endedAt) - +new Date(s.startedAt)) / 60000));

export function NurseScreen() {
  const [sessions, setSessions] = useState<CompanionSession[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () => fetchSessions().then((s) => { setSessions(s); setErr(null); }, () => setErr("Can't reach the backend (is it running on :8000?)"));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const alerts = sessions.flatMap((s) => s.alerts.map((a) => `${s.patientName}: ${a}`));

  return (
    <main>
      <h1>Nurse dashboard</h1>
      <p className="small">
        Shows activity and engagement, not a clinical score. Start a session on the <a href="/patient" target="_blank" rel="noreferrer">patient screen ↗</a>.
      </p>
      {err && <p className="warn">{err}</p>}

      {alerts.length > 0 && (
        <div className="alerts" role="alert">{alerts.slice(0, 5).map((a, i) => <p key={i}>⚠️ {a}</p>)}</div>
      )}

      <h2>Recent sessions</h2>
      {sessions.length === 0 ? (
        <div className="card"><p className="small">No sessions yet. They appear here when a patient-screen session ends.</p></div>
      ) : (
        <div className="grid2">
          {sessions.map((s) => (
            <div key={s._id} className="card">
              <div className="row">
                <strong>{s.patientName}</strong>
                <span className="badge">{time(s.startedAt)}</span>
                <span className="badge">{minutes(s)} min</span>
              </div>
              <p className="small">
                {s.gamesPlayed.length ? [...new Set(s.gamesPlayed)].map((g) => GAME_NAMES[g] ?? g).join(", ") : "Conversation only"}
              </p>
              {s.observations.length > 0 && (
                <ul className="small">
                  {s.observations.map((o, i) => (
                    <li key={i}><strong>{ENGAGEMENT[o.engagement]}</strong>{o.game ? ` · ${GAME_NAMES[o.game] ?? o.game}` : ""}{o.note ? `: ${o.note}` : ""}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      <h2>Residents <span className="small">(placeholder data)</span></h2>
      <div className="residents">
        {RESIDENTS.map((r) => (
          <div key={r.name} className="card res">
            <strong>{r.name}</strong> <span className="small">Room {r.room}</span>
            <p className="small" style={{ margin: "4px 0 0" }}>{r.last}{r.when ? ` · ${r.when}` : ""}</p>
          </div>
        ))}
      </div>
    </main>
  );
}

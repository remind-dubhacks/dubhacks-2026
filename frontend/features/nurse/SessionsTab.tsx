import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CompanionSession } from "@/lib/voice";
import { GAME_NAMES } from "./NurseScreen";
import { parseTime, when } from "./time";

const ENGAGEMENT: Record<string, string> = { engaged: "Engaged", some: "Some interest", withdrawn: "Withdrawn" };
const minutes = (s: CompanionSession) => Math.max(1, Math.round((+parseTime(s.endedAt) - +parseTime(s.startedAt)) / 60000));

export function SessionsTab({ residentId }: { residentId: string }) {
  const [sessions, setSessions] = useState<CompanionSession[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.participantSessions(residentId).then(setSessions, (e) => setErr((e as Error).message));
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [residentId]);

  if (err) return <p className="nurse-error">{err}</p>;
  if (!sessions) return <p className="muted">Loading…</p>;
  if (sessions.length === 0) return <p className="muted">No sessions yet. They appear here when a call on the patient screen ends.</p>;
  return (
    <ul className="list">
      {sessions.map((s) => (
        <li key={s._id} className="item">
          <p className="item-title">{when(s.startedAt)} · {minutes(s)} min</p>
          <p className="muted">{s.gamesPlayed.length ? [...new Set(s.gamesPlayed)].map((g) => GAME_NAMES[g] ?? g).join(", ") : "Conversation only"}</p>
          {s.observations.length > 0 && (
            <ul className="obs">
              {s.observations.map((o, i) => (
                <li key={i}><strong>{ENGAGEMENT[o.engagement] ?? o.engagement}</strong>{o.game ? ` · ${GAME_NAMES[o.game] ?? o.game}` : ""}{o.note ? `: ${o.note}` : ""}</li>
              ))}
            </ul>
          )}
          {s.alerts.map((a, i) => <p key={i} className="item-alert"><span className="dot" aria-hidden /> {a}</p>)}
        </li>
      ))}
    </ul>
  );
}

"use client";

// Nurse-facing setup, shown before a session and again on Esc. The Start click is also the browser
// gesture that allows the microphone and sound playback.
// Picking a resident sends their participantId, so the companion uses their care profile and memories.
import { useEffect, useState } from "react";
import { api, type Participant } from "@/lib/api";

const GAMES = [
  { id: "faces", label: "Famous faces", on: true },
  { id: "proverbs", label: "Sayings", on: true },
  { id: "sounds", label: "Sounds", on: true },
  { id: "reorder", label: "Reorder (needs the robot)", on: false },
];
const SAVED = "remind.patient.setup";

type Props = {
  live: boolean;
  connecting: boolean;
  error: string | null;
  onStart: (name: string, games: string[], participantId?: string) => void;
  onEnd: () => void;
  onHide: () => void;
};

const displayName = (p: Participant) => p.careProfile?.preferredName || p.alias;

export function SetupCard({ live, connecting, error, onStart, onEnd, onHide }: Props) {
  const [name, setName] = useState("");
  const [games, setGames] = useState<string[]>(GAMES.filter((g) => g.on).map((g) => g.id));
  const [residents, setResidents] = useState<Participant[]>([]);
  const [participantId, setParticipantId] = useState("");

  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(SAVED) ?? "null");
      if (s?.name) setName(s.name);
      if (Array.isArray(s?.games)) setGames(s.games);
      if (s?.participantId) setParticipantId(s.participantId);
    } catch { /* ignore */ }
    api.participants().then(setResidents).catch(() => setResidents([]));
  }, []);

  const resident = residents.find((p) => p._id === participantId);

  function pick(id: string) {
    setParticipantId(id);
    const p = residents.find((r) => r._id === id);
    if (p) setName(displayName(p));
  }

  function start(e: React.FormEvent) {
    e.preventDefault();
    const pid = resident ? participantId : "";
    try { localStorage.setItem(SAVED, JSON.stringify({ name, games, participantId: pid })); } catch { /* ignore */ }
    onStart(name.trim(), games, pid || undefined);
  }

  const toggle = (id: string) => setGames((gs) => (gs.includes(id) ? gs.filter((g) => g !== id) : [...gs, id]));

  return (
    <div className="calm-setup">
      <form className="card" onSubmit={start}>
        <h1>ReMind companion</h1>
        {live ? (
          <>
            <p>Session running{name ? ` with ${name}` : ""}.</p>
            <div className="actions">
              <button type="button" onClick={onHide}>Back to patient view</button>
              <button type="button" className="stop" onClick={onEnd}>End session</button>
            </div>
          </>
        ) : (
          <>
            {residents.length > 0 && (
              <label className="small">
                Resident
                <select value={resident ? participantId : ""} onChange={(e) => pick(e.target.value)}>
                  <option value="">Someone else (name only)</option>
                  {residents.map((p) => <option key={p._id} value={p._id}>{displayName(p)}</option>)}
                </select>
              </label>
            )}
            {resident?.careProfile?.interests?.length ? (
              <p className="small">Using {displayName(resident)}&apos;s care profile: likes {resident.careProfile.interests[0]}.</p>
            ) : null}
            <label className="small">
              Patient&apos;s first name
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Margaret" required autoFocus />
            </label>
            <fieldset>
              <legend>Games</legend>
              {GAMES.map((g) => (
                <label key={g.id} className="check">
                  <input type="checkbox" checked={games.includes(g.id)} onChange={() => toggle(g.id)} />
                  {g.label}
                </label>
              ))}
            </fieldset>
            {error && <p className="error">{error}</p>}
            <div className="actions">
              <button type="submit" className="primary" disabled={connecting || !name.trim() || games.length === 0}>
                {connecting ? "Starting…" : "Start"}
              </button>
            </div>
            <p className="small">After Start, the screen shows only the calm view. Press Esc to come back here.</p>
          </>
        )}
      </form>
    </div>
  );
}

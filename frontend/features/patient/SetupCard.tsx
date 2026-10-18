"use client";

// Nurse-facing setup, shown before a session and again on Esc. The Start click is also the browser
// gesture that allows the microphone and sound playback.
import { useEffect, useState } from "react";

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
  onStart: (name: string, games: string[]) => void;
  onEnd: () => void;
  onHide: () => void;
};

export function SetupCard({ live, connecting, error, onStart, onEnd, onHide }: Props) {
  const [name, setName] = useState("");
  const [games, setGames] = useState<string[]>(GAMES.filter((g) => g.on).map((g) => g.id));

  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(SAVED) ?? "null");
      if (s?.name) setName(s.name);
      if (Array.isArray(s?.games)) setGames(s.games);
    } catch { /* ignore */ }
  }, []);

  function start(e: React.FormEvent) {
    e.preventDefault();
    try { localStorage.setItem(SAVED, JSON.stringify({ name, games })); } catch { /* ignore */ }
    onStart(name.trim(), games);
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

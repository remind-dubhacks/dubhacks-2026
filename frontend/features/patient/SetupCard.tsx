"use client";

// Nurse-facing setup, shown before a session and again on Esc. The Start click is also the browser
// gesture that allows the microphone and sound playback. Styled as the "device faceplate" from the
// Calm design handoff (Nurse Setup.dc.html).
// Picking a resident sends only their participantId: the backend takes their name, care profile and
// memories from it. "Someone else…" (or no residents to pick from) sends a typed first name instead.
import { useEffect, useState } from "react";
import { api, type Participant } from "@/lib/api";

const GAMES = [
  { id: "faces", label: "Famous faces", on: true, icon: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18Z M8.5 14.5c1 1.3 2.2 2 3.5 2s2.5-.7 3.5-2 M9 9.5h.01 M15 9.5h.01" },
  { id: "proverbs", label: "Sayings", on: true, icon: "M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12Z" },
  { id: "sounds", label: "Sounds", on: true, icon: "M11 5 6 9H3v6h3l5 4V5Z M15.5 8.5a5 5 0 0 1 0 7 M18.5 5.5a9 9 0 0 1 0 13" },
  { id: "reorder", label: "Reorder (needs the robot)", on: false, icon: "M7 4v16 M3 8l4-4 4 4 M17 20V4 M13 16l4 4 4-4" },
];
// Reorder stays disabled until a robot can be connected.
const REORDER_AVAILABLE = false;
const available = (id: string) => id !== "reorder" || REORDER_AVAILABLE;
const SAVED = "remind.patient.setup";
const GUEST = "guest";

type Props = {
  live: boolean;
  connecting: boolean;
  error: string | null;
  onStart: (name: string, games: string[], participantId?: string) => void;
  onEnd: () => void;
  onHide: () => void;
};

const displayName = (p: Participant) => p.careProfile?.preferredName || p.alias;

function Header() {
  return (
    <div className="face-head">
      <h1>ReMind Companion</h1>
      <div className="face-lights" aria-hidden="true">
        <div className="grille">{Array.from({ length: 9 }, (_, i) => <span key={i} />)}</div>
        <span className="led" />
      </div>
    </div>
  );
}

export function SetupCard({ live, connecting, error, onStart, onEnd, onHide }: Props) {
  const [name, setName] = useState("");
  const [games, setGames] = useState<string[]>(GAMES.filter((g) => g.on && available(g.id)).map((g) => g.id));
  const [residents, setResidents] = useState<Participant[] | null>(null); // null while loading
  const [choice, setChoice] = useState(""); // a resident's _id, or GUEST

  useEffect(() => {
    let saved: { name?: string; games?: string[]; participantId?: string } | null = null;
    try {
      saved = JSON.parse(localStorage.getItem(SAVED) ?? "null");
      if (Array.isArray(saved?.games)) setGames(saved.games.filter(available));
      if (saved?.name && !saved.participantId) setName(saved.name);
    } catch { /* ignore */ }
    const wasGuest = !!saved?.name && !saved.participantId;
    api.participants()
      .then((ps) => {
        setResidents(ps);
        const pid = saved?.participantId;
        setChoice(pid && ps.some((p) => p._id === pid) ? pid : wasGuest ? GUEST : ps[0]?._id ?? GUEST);
      })
      .catch(() => { setResidents([]); setChoice(GUEST); });
  }, []);

  const resident = residents?.find((p) => p._id === choice);
  const guest = residents !== null && !resident;
  const who = resident ? displayName(resident) : name.trim();

  function start(e: React.FormEvent) {
    e.preventDefault();
    const chosen = games.filter(available);
    const saved = resident ? { games: chosen, participantId: resident._id } : { games: chosen, name };
    try { localStorage.setItem(SAVED, JSON.stringify(saved)); } catch { /* ignore */ }
    onStart(resident ? "" : name.trim(), chosen, resident?._id);
  }

  const toggle = (id: string) => setGames((gs) => (gs.includes(id) ? gs.filter((g) => g !== id) : [...gs, id]));
  const helper = <p className="helper">After Start, the screen shows only the calm view. Press Esc to come back here.</p>;

  if (live) {
    return (
      <div className="calm-setup">
        <div className="face">
          <Header />
          <p className="status">Session running{who ? ` with ${who}` : ""}.</p>
          <div className="start-well">
            <button type="button" className="start" onClick={onHide}>Back to patient view</button>
          </div>
          <div className="start-well">
            <button type="button" className="start secondary" onClick={onEnd}>End session</button>
          </div>
          {helper}
        </div>
      </div>
    );
  }

  return (
    <div className="calm-setup">
      <form className="face" onSubmit={start}>
        <Header />
        {residents && residents.length > 0 && (
          <label className="field">
            <span>Who&apos;s playing?</span>
            <div className="field-well">
              <select value={choice} onChange={(e) => setChoice(e.target.value)}>
                {residents.map((p) => <option key={p._id} value={p._id}>{displayName(p)}</option>)}
                <option value={GUEST}>Someone else…</option>
              </select>
            </div>
            {resident?.careProfile?.interests?.length ? (
              <span className="field-note">
                Using {displayName(resident)}&apos;s care profile: likes {resident.careProfile.interests[0]}.
              </span>
            ) : null}
          </label>
        )}
        {guest && (
          <label className="field">
            <span>First name</span>
            <div className="field-well">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="First name" required autoFocus />
            </div>
          </label>
        )}
        <div className="field">
          <span id="games-label">Games</span>
          <div className="tray" role="group" aria-labelledby="games-label">
            {GAMES.map((g) => {
              const disabled = !available(g.id);
              const on = !disabled && games.includes(g.id);
              return (
                <button key={g.id} type="button" className="key" aria-pressed={on} aria-label={g.label}
                  disabled={disabled} onClick={() => toggle(g.id)}>
                  <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={g.icon} />
                  </svg>
                </button>
              );
            })}
          </div>
          <div className="key-labels" aria-hidden="true">
            {GAMES.map((g) => <span key={g.id} className={available(g.id) ? "" : "disabled"}>{g.label}</span>)}
          </div>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="start-well">
          <button type="submit" className="start" disabled={connecting || !who || games.length === 0}>
            {connecting ? "Starting…" : "Start"}
          </button>
        </div>
        {helper}
      </form>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { ItemCard } from "@/components/ItemCard";
import { loadLive, type LiveSession } from "@/lib/liveSession";

const PHASE_TEXT: Record<string, string> = {
  idle: "Waiting to start", intro: "Explaining the game", shuffling: "Robot is shuffling", awaiting: "Resident is reordering",
  checking: "Checking the order", feedback: "Giving feedback", reveal: "Showing the answer", complete: "Finished", stopped: "Stopped",
};

// Placeholder residents (synthetic). The live resident (Rose) is overlaid from the running session.
const RESIDENTS = [
  { name: "Rose", room: "12A" }, { name: "Harold", room: "12B", last: "Correct on try 2", when: "Yesterday" },
  { name: "Ines", room: "14", last: "Correct on try 1", when: "Today 9:10" }, { name: "George", room: "15", last: "Used all 3 tries", when: "Today 8:40" },
  { name: "Mabel", room: "16A", last: "Not played yet", when: "" }, { name: "Walter", room: "16B", last: "Correct on try 3", when: "Yesterday" },
  { name: "Dorothy", room: "17", last: "Not played yet", when: "" }, { name: "Frank", room: "18A", last: "Correct on try 1", when: "Today 9:30" },
  { name: "Edith", room: "18B", last: "Asked for help", when: "Today 8:55" }, { name: "Arthur", room: "19", last: "Not played yet", when: "" },
];

export default function Dashboard() {
  const [live, setLive] = useState<LiveSession | null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    setLive(loadLive());
    const t = setInterval(() => { setLive(loadLive()); setNow(Date.now()); }, 1000);
    return () => clearInterval(t);
  }, []);

  const active = live && !["idle", "complete", "reveal", "stopped"].includes(live.phase);
  const secs = live ? Math.max(0, Math.round(((live.phase === "complete" || live.phase === "reveal" || live.phase === "stopped" ? live.updatedAt : now) - live.startedAt) / 1000)) : 0;
  const alerts: string[] = [];
  if (live?.helpRequested) alerts.push(`${live.resident} asked for help`);
  if (live?.result === "gave_up") alerts.push(`${live.resident} used all ${live.maxTrials} tries`);

  return (
    <main>
      <h1>Caregiver dashboard</h1>
      <p className="small">Supervised use only. Keep the workspace clear and the emergency stop within reach. Shows activity, not a clinical score.</p>

      {alerts.length > 0 && (
        <div className="alerts" role="alert">{alerts.map((a) => <p key={a}>⚠️ {a}</p>)}</div>
      )}

      <h2>Live session</h2>
      {live && live.phase !== "idle" ? (
        <div className="card live">
          <div className="row">
            <strong>{live.resident}</strong>
            <span className={`badge ${active ? "on" : ""}`}>{PHASE_TEXT[live.phase] ?? live.phase}</span>
            <span className="badge">Try {Math.min(live.attempt + (live.phase === "awaiting" ? 1 : 0), live.maxTrials)} of {live.maxTrials}</span>
            <span className="badge">{secs}s</span>
          </div>
          <p className="small">Says: “{live.lastFeedback}”</p>
          <div className="row">
            <div><p className="small">Target</p><div className="itemrow mini">{live.target.map((id) => <ItemCard key={id} id={id} />)}</div></div>
            {live.shuffledOrder.length > 0 && <div><p className="small">After shuffle</p><div className="itemrow mini">{live.shuffledOrder.map((id) => <ItemCard key={id} id={id} />)}</div></div>}
          </div>
          {live.result !== "none" && <p><strong>Result:</strong> {live.result === "correct" ? `Correct in ${live.attempt} ${live.attempt === 1 ? "try" : "tries"}` : live.result === "gave_up" ? "Not solved in 3 tries" : "Stopped"}</p>}
        </div>
      ) : (
        <div className="card"><p className="small">No live session. Open the <a href="/play" target="_blank" rel="noreferrer">resident screen ↗</a> in another tab to start one.</p></div>
      )}

      <h2>Residents</h2>
      <div className="residents">
        {RESIDENTS.map((r) => {
          const isLive = r.name === live?.resident && live.phase !== "idle";
          const last = isLive ? (live!.result === "correct" ? `Correct on try ${live!.attempt}` : live!.result === "gave_up" ? "Used all 3 tries" : PHASE_TEXT[live!.phase]) : r.last ?? "Not played yet";
          return (
            <div key={r.name} className={`card res ${isLive ? "live" : ""}`}>
              <strong>{r.name}</strong> <span className="small">Room {r.room}</span>
              <p className="small" style={{ margin: "4px 0 0" }}>Reorder: {last}{!isLive && r.when ? ` · ${r.when}` : ""}</p>
            </div>
          );
        })}
      </div>

      <h2>Game catalog</h2>
      <div className="residents">
        <div className="card"><strong>Reorder</strong><p className="small">Robot shuffles, resident puts items back in order.</p><span className="badge on">Available</span></div>
        <div className="card dim"><strong>Memory match</strong><p className="small">Coming soon</p></div>
        <div className="card dim"><strong>Sort by colour</strong><p className="small">Coming soon</p></div>
      </div>
    </main>
  );
}

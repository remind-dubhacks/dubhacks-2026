"use client";

// Playground: run Remember the Order by tapping (no microphone) and watch, in real time, what the
// camera sees, what the robot is doing, and when and why the companion speaks. Same engine and robot
// path as the patient screen (backend/app/play.py).
import { useCallback, useEffect, useRef, useState } from "react";
import { API } from "@/lib/api";
import "./playground.css";
import { Board, Keycap } from "@/features/shared/Keycap";

type Ev = { kind: string; obj?: string; spot?: number; right?: boolean; level?: number };
type Exercise = {
  phase: string; row: string[]; answer: string[]; say: string; options: string[]; watching: boolean; mover: string;
  robot?: { status?: string; last?: string; error?: string; check?: { verdict?: string } };
  summary?: { rounds: number; restoredAlone: number; restoredWithChoice: number; restoredTogether: number };
};
type LogLine = { t: string; who: "robot" | "camera" | "agent" | "you"; text: string; tone?: "ok" | "warn" };
type FeedItem = { t: number; who: string; text?: string; kind?: string; event?: Ev; check?: string; tone?: "ok" | "warn" };
type Robot = { reachable: boolean; mode?: string; ready?: boolean; busy?: boolean; motors?: Record<string, { ok: boolean; tempC: number }> };

const SPOT = ["left", "middle", "right"];
const STEPS = [
  { label: "Look & say", phases: ["study", "idle"] },
  { label: "Robot mixes", phases: ["shuffle"] },
  { label: "Put back", phases: ["restore"] },
  { label: "Memory", phases: ["reminisce", "recall"] },
  { label: "Done", phases: ["done"] },
];
const BADGE: Record<string, string> = { robot: "⚙", camera: "◉", agent: "R", you: "P" };
const WHO: Record<string, string> = { robot: "Robot", camera: "Camera", agent: "ReMind", you: "Player" };
const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function fromFeed(f: FeedItem): LogLine | null {
  const t = new Date(f.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (f.who === "camera" && f.event) { const l = describe(f.event); return l && { ...l, t }; }
  if (f.who === "robot") {
    const k = f.kind;
    const text = k === "paused_for_hand" ? "paused: a hand is on the table" : k === "resumed" ? "table clear, carrying on" : k === "checking" ? "checking the row with the camera"
      : k === "checked" ? "row checked" : k === "moving" ? "moving" : k === "hand_timeout" ? "stopped: a hand stayed on the table" : f.text ?? "";
    return { t, who: "robot", text: f.check ? `${text} (camera check: ${f.check})` : text, tone: f.tone ?? (k === "hand_timeout" ? "warn" : undefined) };
  }
  if (f.who === "agent") return { t, who: "agent", text: f.text ?? "" };
  if (f.who === "player") return { t, who: "you", text: f.text ?? "" };
  return null;
}

function describe(e: Ev): LogLine | null {
  const t = now();
  switch (e.kind) {
    case "lifted": return { t, who: "camera", text: `Picked up: ${e.obj}` };
    case "placed": return { t, who: "camera", text: `${e.obj} placed in spot ${(e.spot ?? 0) + 1}: ${e.right ? "right spot" : "not its spot (waiting before helping)"}`, tone: e.right ? "ok" : "warn" };
    case "wrong_stays": return { t, who: "camera", text: `${e.obj} is still in the wrong spot after a calm pause: offering a choice`, tone: "warn" };
    case "holding": return { t, who: "camera", text: `Holding ${e.obj} for a while: giving a hint` };
    case "hesitate": return { t, who: "camera", text: `No activity: support level ${e.level} of 3` };
    case "complete": return { t, who: "camera", text: "Row matches the original!", tone: "ok" };
    default: return null;
  }
}

async function post(path: string, body: unknown) {
  const r = await fetch(`${API}/api/play/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export default function Playground() {
  const [sid] = useState(() => `play-${Math.random().toString(36).slice(2, 8)}`);
  const [mover, setMover] = useState<"simulated" | "robot">("simulated");
  const [ex, setEx] = useState<Exercise | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [typed, setTyped] = useState("");
  const [robot, setRobot] = useState<Robot | null>(null);
  const [camera, setCamera] = useState<boolean | null>(null);
  const [err, setErr] = useState("");
  const [frame, setFrame] = useState(0);
  const [live, setLive] = useState<{ active: boolean; name?: string; game?: string; state?: { exercise?: Exercise }; feed?: FeedItem[] } | null>(null);
  const [follow, setFollow] = useState(true);
  const [camOk, setCamOk] = useState(true);
  const lastRobot = useRef("");
  const add = (l: LogLine | null) => l && setLog((ls) => [l, ...ls].slice(0, 80));

  const take = useCallback((state: { exercise?: Exercise }) => {
    const e = state.exercise ?? null;
    setEx(e);
    const r = e?.robot;
    const key = `${r?.status}/${r?.last}`;
    if (r?.status && key !== lastRobot.current) {
      lastRobot.current = key;
      const what = r.status === "moving" ? (r.last === "paused_for_hand" ? "paused: a hand is on the table" : r.last === "checking" ? "checking the row with the camera" : "moving") :
        r.status === "done" ? `finished (camera check: ${r.check?.verdict ?? "n/a"})` : `needs help (${r.error}); caregiver texted`;
      add({ t: now(), who: "robot", text: what, tone: r.status === "failed" ? "warn" : r.status === "done" ? "ok" : undefined });
    }
  }, []);

  const speak = (text: string) => {
    add({ t: now(), who: "agent", text });
    try { const u = new SpeechSynthesisUtterance(text); u.rate = 0.92; speechSynthesis.cancel(); speechSynthesis.speak(u); } catch { /* no voice */ }
  };

  const start = async () => {
    setErr(""); setLog([]); lastRobot.current = "";
    try {
      const r = await post("start", { sessionId: sid, mover });
      take(r.state);
      if (r.result?.say) speak(r.result.say);
    } catch (e) { setErr(String(e)); }
  };

  const say = async (text: string) => {
    if (!text.trim()) return;
    add({ t: now(), who: "you", text });
    try {
      const r = await post("say", { sessionId: sid, text });
      take(r.state);
      if (r.result?.say) speak(r.result.say);
    } catch (e) { setErr(String(e)); }
  };

  // Live loop: the table watcher decides when to speak; we just poll and show everything it noticed.
  useEffect(() => {
    if (!ex || ex.phase === "done") return;
    if (!(ex.watching || ex.robot?.status === "moving")) return;
    let stop = false;
    const id = setInterval(async () => {
      if (stop) return;
      try {
        const r = await post("watch", { sessionId: sid });
        if (stop) return;
        setCamera(r.camera !== false);
        (r.events as Ev[]).forEach((e) => add(describe(e)));
        take(r.state);
        if (r.say) speak(r.say);
      } catch { /* backend busy */ }
    }, 1200);
    return () => { stop = true; clearInterval(id); };
  }, [ex?.watching, ex?.robot?.status, ex?.phase, sid, take]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const get = () => fetch(`${API}/api/play/robot`).then((r) => r.json()).then(setRobot).catch(() => setRobot({ reachable: false }));
    get();
    const id = setInterval(get, 10000);
    return () => clearInterval(id);
  }, []);

  // Follow the real patient session when one is running (read-only).
  useEffect(() => {
    let alive = true;
    const get = () => fetch(`${API}/api/play/live`).then((r) => r.json()).then((d) => { if (alive) setLive(d); }).catch(() => {});
    get();
    const id = setInterval(get, 1500);
    return () => { alive = false; clearInterval(id); };
  }, []);
  const following = !!live?.active && follow && !ex;
  const viewEx: Exercise | null = following ? (live?.state?.exercise ?? null) : ex;
  const viewLog: LogLine[] = following ? (live?.feed ?? []).map(fromFeed).filter((l): l is LogLine => !!l).reverse() : log;

  // Live camera: a fresh annotated frame about once a second while the robot is reachable.
  useEffect(() => {
    if (!robot?.reachable) return;
    const id = setInterval(() => setFrame((f) => f + 1), 1000);
    return () => clearInterval(id);
  }, [robot?.reachable]);

  const hot = robot?.motors ? Math.max(...Object.values(robot.motors).map((m) => m.tempC ?? 0)) : 0;
  const robotLine = robot?.reachable ? `${robot.mode} mode · ${robot.ready ? (robot.busy ? "busy" : "ready") : "not ready"}` : "offline";
  const stepAt = viewEx ? Math.max(0, STEPS.findIndex((st) => st.phases.includes(viewEx.phase))) : -1;
  const moving = viewEx?.robot?.status === "moving";
  const headline = !viewEx ? "" : moving ? (viewEx.robot?.last === "paused_for_hand" ? "Robot is waiting: a hand is on the table" : "The robot is mixing the keyrings…")
    : viewEx.phase === "restore" ? "Player's turn: put them back the way they were" : viewEx.phase === "study" ? "Look at the row and say it together"
    : viewEx.phase === "done" ? "Game finished" : "Chatting about a memory";

  return (
    <main className="pg">
      <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;600;700&display=swap" precedence="default" />
      <header className="pg-hero">
        <div className="pg-brand">
          <span className="pg-logo" aria-hidden="true"><Keycap name="purple" size={44} /></span>
          <div>
            <h1>Robot playground</h1>
            <p>Remember the Order, live: what the camera sees, what the robot does, and when the companion helps.</p>
          </div>
        </div>
        <a className="pg-chip" href="/patient">← Back to setup</a>
      </header>

      <section className="pg-cards">
        <div className="pg-face pg-card">
          <span className="pg-card-label">Robot arm</span>
          <span className="pg-card-value"><span className={`pg-dot ${robot?.ready ? "on" : robot ? "off" : "wait"}`} />{robotLine}</span>
          {robot?.motors && (
            <div className="pg-gauges" title="Follower motor temperatures (pauses at 60 °C)">
              {Object.entries(robot.motors).map(([k, m]) => (
                <span key={k} className="pg-gauge">
                  <span className="pg-gauge-bar"><span style={{ height: `${Math.min(100, Math.max(8, ((m.tempC - 30) / 35) * 100))}%` }}
                    className={m.tempC >= 60 ? "hot" : m.tempC >= 55 ? "warm" : ""} /></span>
                  <small>{k.split("_").map((w) => w[0]).join("").toUpperCase()}</small>
                </span>
              ))}
              <span className={`pg-temp ${hot >= 60 ? "hot" : hot >= 55 ? "warm" : ""}`}>{hot}°C</span>
            </div>
          )}
        </div>
        <div className="pg-face pg-card">
          <span className="pg-card-label">Camera</span>
          <span className="pg-card-value"><span className={`pg-dot ${camera ? "on" : camera === false ? "off" : "wait"}`} />
            {camera === null ? "starts with the game" : camera ? "watching the table" : "can't see the table"}</span>
          <span className="pg-muted small">Judges a placement after 2 s of stillness with no hand on the table.</span>
        </div>
        <div className="pg-face pg-card pg-card-controls">
          <span className="pg-card-label">Test game</span>
          <div className="pg-segment" role="radiogroup" aria-label="Who moves the keyrings">
            {(["simulated", "robot"] as const).map((m) => (
              <button key={m} role="radio" aria-checked={mover === m} className={mover === m ? "on" : ""}
                disabled={(!!ex && ex.phase !== "done") || (m === "robot" && !robot?.ready)} onClick={() => setMover(m)}>
                {m === "simulated" ? "Simulated" : "Robot arm"}
              </button>
            ))}
          </div>
          <div className="pg-row-buttons">
            <button className="pg-start" onClick={start}>{ex ? "Restart" : "Start game"}</button>
            {ex && <button className="pg-chip" onClick={() => post("stop", { sessionId: sid }).then(() => { setEx(null); add({ t: now(), who: "you", text: "Stopped" }); })}>Stop</button>}
          </div>
        </div>
      </section>

      {mover === "robot" && <p className="pg-warn">⚠ The arm will move. Keep the emergency stop within reach and hands off the table while it moves.</p>}
      {err && <p className="pg-error">{err}</p>}
      {live?.active && (
        <div className="pg-face pg-live">
          <span className="pg-pulse" aria-hidden="true" />
          <span className="pg-stat">Live patient session: {live.name}{live.game ? ` · ${live.game.replace("_", " ")}` : ""}</span>
          {ex ? <span className="pg-muted">Stop your test game to follow it.</span>
            : <button className="pg-chip" onClick={() => setFollow((f) => !f)}>{follow ? "Following live (read-only)" : "Follow it here"}</button>}
        </div>
      )}

      <div className="pg-main">
        <section className="pg-face pg-table">
          {!viewEx ? (
            <div className="pg-empty">
              <Board row={["black keycap", "white keycap", "purple keycap"]} labels={false} size={64} />
              <p>{live?.active ? `${live.name} is doing another activity right now.` : "Start a test game, or start Remember the Order on the patient screen to follow it here live."}</p>
            </div>
          ) : (
            <>
              <ol className="pg-steps">
                {STEPS.map((st, i) => (
                  <li key={st.label} className={i < stepAt ? "done" : i === stepAt ? "now" : ""}><span>{i < stepAt ? "✓" : i + 1}</span>{st.label}</li>
                ))}
              </ol>
              <h2 className={`pg-headline${moving ? " moving" : ""}`}>{headline}</h2>
              <Board row={viewEx.row} answer={viewEx.answer} judge={viewEx.phase === "restore" && !moving} size={84} />
              <div className="pg-answer">
                <span className="pg-card-label">Original order · caregiver only</span>
                <span className="pg-mini-row">{viewEx.answer.map((o, i) => <span key={i}><Keycap name={o} size={26} />{o.split(" ")[0]}</span>)}</span>
              </div>
              {viewEx.say && (
                <div className="pg-bubble"><span className="pg-avatar" aria-hidden="true">R</span><p>{viewEx.say}</p></div>
              )}
              {!following && (<>
                <div className="pg-actions">
                  {viewEx.options.map((o) => <button key={o} className="pg-option" onClick={() => say(o)}><Keycap name={o} size={30} />{o}</button>)}
                  {viewEx.phase === "study" && <button className="pg-chip" onClick={() => say(viewEx.answer.join(", "))}>Say them back</button>}
                  {viewEx.phase === "restore" && <button className="pg-chip" onClick={() => say("done")}>I&apos;m done</button>}
                  {(viewEx.phase === "reminisce" || viewEx.phase === "recall") && <button className="pg-chip" onClick={() => say("skip")}>Skip</button>}
                </div>
                <form className="pg-say-form" onSubmit={(e) => { e.preventDefault(); say(typed); setTyped(""); }}>
                  <div className="pg-well"><input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type what the player says…" /></div>
                  <button type="submit" className="pg-chip">Say</button>
                </form>
              </>)}
              {viewEx.summary && viewEx.summary.rounds > 0 && (
                <div className="pg-tally">
                  <span><b>{viewEx.summary.restoredAlone}</b> alone</span>
                  <span><b>{viewEx.summary.restoredWithChoice}</b> with a choice</span>
                  <span><b>{viewEx.summary.restoredTogether}</b> together</span>
                </div>
              )}
            </>
          )}
        </section>

        <div className="pg-side">
          <section className="pg-face">
            <div className="pg-sec-head"><h2>Robot camera</h2>{robot?.reachable && camOk && <span className="pg-live-pill">● LIVE</span>}</div>
            {robot?.reachable ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img className="pg-cam" src={`${API}/api/play/camera.jpg?f=${frame}`} alt="Live view of the table from the robot's side camera"
                  onLoad={() => setCamOk(true)} onError={() => setCamOk(false)} style={{ display: camOk ? "block" : "none" }} />
                {!camOk && <div className="pg-cam-off">Camera busy right now (for example while a recording runs).</div>}
                <p className="pg-muted small">Circles: each keyring and the slot the game reads. Red frame: a hand is on the table, so the robot waits.</p>
              </>
            ) : <div className="pg-cam-off">Robot worker offline: no camera view.</div>}
          </section>

          <section className="pg-face pg-feed">
            <div className="pg-sec-head"><h2>Live feed</h2><span className="pg-muted small">newest first</span></div>
            <ol>
              {viewLog.length === 0 && <li className="pg-muted">Nothing yet.</li>}
              {viewLog.map((l, i) => (
                <li key={i} className={l.tone ?? ""}>
                  <span className={`pg-badge ${l.who}`} aria-hidden="true">{BADGE[l.who]}</span>
                  <div><span className="pg-who">{WHO[l.who]}</span> <small>{l.t}</small><p>{l.text}</p></div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </main>
  );
}

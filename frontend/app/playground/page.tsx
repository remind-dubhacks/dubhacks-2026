"use client";

// Playground: run Remember the Order by tapping (no microphone) and watch, in real time, what the
// camera sees, what the robot is doing, and when and why the companion speaks. Same engine and robot
// path as the patient screen (backend/app/play.py).
import { useCallback, useEffect, useRef, useState } from "react";
import { API } from "@/lib/api";

type Ev = { kind: string; obj?: string; spot?: number; right?: boolean; level?: number };
type Exercise = {
  phase: string; row: string[]; answer: string[]; say: string; options: string[]; watching: boolean; mover: string;
  robot?: { status?: string; last?: string; error?: string; check?: { verdict?: string } };
  summary?: { rounds: number; restoredAlone: number; restoredWithChoice: number; restoredTogether: number };
};
type LogLine = { t: string; who: "robot" | "camera" | "agent" | "you"; text: string; tone?: "ok" | "warn" };
type Robot = { reachable: boolean; mode?: string; ready?: boolean; busy?: boolean; motors?: Record<string, { ok: boolean; tempC: number }> };

const SPOT = ["left", "middle", "right"];
const SWATCH: Record<string, string> = { black: "#23262a", white: "#f6f3ea", purple: "#8d72c9" };
const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function describe(e: Ev): LogLine | null {
  const t = now();
  switch (e.kind) {
    case "lifted": return { t, who: "camera", text: `Picked up: ${e.obj}` };
    case "placed": return { t, who: "camera", text: `${e.obj} placed on the ${SPOT[e.spot ?? 0]}: ${e.right ? "right spot" : "not its spot (waiting before helping)"}`, tone: e.right ? "ok" : "warn" };
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

  // Live camera: a fresh annotated frame about once a second while the robot is reachable.
  useEffect(() => {
    if (!robot?.reachable) return;
    const id = setInterval(() => setFrame((f) => f + 1), 1000);
    return () => clearInterval(id);
  }, [robot?.reachable]);

  const hot = robot?.motors ? Math.max(...Object.values(robot.motors).map((m) => m.tempC ?? 0)) : 0;
  const box: React.CSSProperties = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: 16 };

  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 16px 48px", color: "var(--text)" }}>
      <h1 style={{ margin: "0 0 4px" }}>Robot playground</h1>
      <p style={{ margin: "0 0 16px", color: "var(--muted)" }}>Remember the Order, live: camera, robot and the companion&apos;s timing. Tap or type instead of talking.</p>

      <section style={{ ...box, display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginBottom: 16 }}>
        <span><b>Robot:</b> {robot?.reachable ? `${robot.mode}, ${robot.ready ? (robot.busy ? "busy" : "ready") : "not ready"}` : "offline"}</span>
        {robot?.motors && <span style={{ color: hot >= 60 ? "var(--stop)" : hot >= 55 ? "var(--warn)" : "inherit" }}><b>Hottest motor:</b> {hot} °C</span>}
        <span><b>Camera:</b> {camera === null ? "—" : camera ? "watching the table" : "can't see the table"}</span>
        <label style={{ marginLeft: "auto" }}>
          Moves by{" "}
          <select value={mover} onChange={(e) => setMover(e.target.value as "simulated" | "robot")} disabled={!!ex && ex.phase !== "done"}>
            <option value="simulated">simulated (no motion)</option>
            <option value="robot" disabled={!robot?.ready}>the robot arm</option>
          </select>
        </label>
        <button onClick={start}>{ex ? "Restart" : "Start game"}</button>
        {ex && <button onClick={() => post("stop", { sessionId: sid }).then(() => { setEx(null); add({ t: now(), who: "you", text: "Stopped" }); })}>Stop</button>}
      </section>
      {mover === "robot" && <p style={{ color: "var(--warn)", marginTop: -8 }}>The arm will move. Keep the emergency stop within reach and hands off the table while it moves.</p>}
      {err && <p style={{ color: "var(--stop)" }}>{err}</p>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
        <section style={box}>
          <h2 style={{ marginTop: 0 }}>Table</h2>
          {!ex ? <p style={{ color: "var(--muted)" }}>Start a game to see the row.</p> : (
            <>
              <p style={{ margin: "0 0 8px" }}><b>Phase:</b> {ex.phase}{ex.robot?.status === "moving" ? " · robot moving" : ""}</p>
              <div style={{ display: "grid", gridTemplateColumns: `repeat(${ex.row.length}, 1fr)`, gap: 8 }}>
                {ex.row.map((o, i) => {
                  const right = o === ex.answer[i];
                  return (
                    <div key={i} style={{ textAlign: "center", padding: 10, borderRadius: 12, border: `2px solid ${ex.phase === "restore" ? (right ? "var(--accent)" : "var(--warn)") : "var(--border)"}` }}>
                      <div style={{ width: 44, height: 44, margin: "0 auto 6px", borderRadius: 10, border: "1px solid var(--border)", background: SWATCH[o?.split(" ")[0]] ?? "#ccc" }} />
                      <div>{o}</div>
                      <small style={{ color: "var(--muted)" }}>{SPOT[i]}{ex.phase === "restore" ? (right ? " · right" : ` · should be ${ex.answer[i]}`) : ""}</small>
                    </div>
                  );
                })}
              </div>
              <p style={{ margin: "12px 0 4px" }}><b>Original order (caregiver only):</b> {ex.answer.join(" · ")}</p>
              {ex.say && <p style={{ margin: "8px 0" }}><b>Companion:</b> {ex.say}</p>}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {ex.options.map((o) => <button key={o} onClick={() => say(o)}>{o}</button>)}
                {ex.phase === "study" && <button onClick={() => say(ex.answer.join(", "))}>Say them back</button>}
                {ex.phase === "restore" && <button onClick={() => say("done")}>I&apos;m done</button>}
                {(ex.phase === "reminisce" || ex.phase === "recall") && <button onClick={() => say("skip")}>Skip</button>}
              </div>
              <form onSubmit={(e) => { e.preventDefault(); say(typed); setTyped(""); }} style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type what the player says…" style={{ flex: 1, padding: 8 }} />
                <button type="submit">Say</button>
              </form>
              {ex.summary && ex.summary.rounds > 0 && (
                <p style={{ color: "var(--muted)" }}>Rows: {ex.summary.rounds} · alone {ex.summary.restoredAlone} · with a choice {ex.summary.restoredWithChoice} · together {ex.summary.restoredTogether}</p>
              )}
            </>
          )}
        </section>

        <section style={box}>
          <h2 style={{ marginTop: 0 }}>Robot camera</h2>
          {robot?.reachable ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${API}/api/play/camera.jpg?f=${frame}`} alt="Live view of the table from the robot's side camera"
                onLoad={() => setCamOk(true)} onError={() => setCamOk(false)}
                style={{ width: "100%", borderRadius: 12, display: camOk ? "block" : "none", background: "#000" }} />
              {!camOk && <p style={{ color: "var(--muted)" }}>The camera is busy or unavailable right now (for example while a recording runs).</p>}
              <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: 14 }}>Circles show each keyring and the slot the game reads; a red frame means a hand is on the table (the robot waits).</p>
            </>
          ) : <p style={{ color: "var(--muted)" }}>The robot worker is offline, so there is no camera view.</p>}
        </section>

        <section style={box}>
          <h2 style={{ marginTop: 0 }}>Live feed</h2>
          <p style={{ marginTop: 0, color: "var(--muted)", fontSize: 14 }}>
            Placements are judged once the row is still for 2 s with no hand on the table. A wrong spot gets 4 s before any help; then a choice of two. Never &ldquo;wrong&rdquo;.
          </p>
          <ol style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 460, overflow: "auto" }}>
            {log.map((l, i) => (
              <li key={i} style={{ padding: "6px 0", borderTop: "1px solid var(--border)", color: l.tone === "warn" ? "var(--warn)" : l.tone === "ok" ? "var(--accent)" : "inherit" }}>
                <small style={{ color: "var(--muted)" }}>{l.t}</small> <b>{l.who}</b> {l.text}
              </li>
            ))}
          </ol>
        </section>
      </div>
    </main>
  );
}

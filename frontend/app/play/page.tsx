"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ItemCard } from "@/components/ItemCard";
import { clearLive, saveLive, type LiveSession, type Phase } from "@/lib/liveSession";
import { MAX_TRIALS, TARGET, checkOrder, item, shuffled } from "@/lib/reorder";

const RESIDENT = "Rose"; // synthetic demo profile
const names = (ids: string[]) => ids.map((i) => item(i).label.toLowerCase()).join(", then the ");

function speak(text: string, on: boolean) {
  if (!on || typeof window === "undefined" || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 0.9;
  window.speechSynthesis.speak(u);
}

export default function Play() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [attempt, setAttempt] = useState(0);
  const [table, setTable] = useState<string[]>(TARGET); // what is on the (simulated) table
  const [prompt, setPrompt] = useState("Hello Rose. Would you like to play a game?");
  const [feedback, setFeedback] = useState("");
  const [wrong, setWrong] = useState<string[]>([]);
  const [pick, setPick] = useState<number | null>(null);
  const [readAloud, setReadAloud] = useState(true);
  const [typed, setTyped] = useState("");
  const [help, setHelp] = useState(false);
  const [result, setResult] = useState<LiveSession["result"]>("none");
  const startedAt = useRef(Date.now());
  const shuffledRef = useRef<string[]>([]);

  const say = useCallback((t: string) => { setPrompt(t); speak(t, readAloud); }, [readAloud]);

  useEffect(() => {
    saveLive({
      resident: RESIDENT, phase, attempt, maxTrials: MAX_TRIALS, target: TARGET, shuffledOrder: shuffledRef.current,
      lastFeedback: feedback || prompt, result, helpRequested: help, startedAt: startedAt.current, updatedAt: Date.now(),
    });
  }, [phase, attempt, feedback, prompt, result, help]);

  async function startRound() {
    setAttempt(0); setFeedback(""); setWrong([]); setResult("none"); setPick(null);
    startedAt.current = Date.now();
    setPhase("intro");
    say(`Let's play. I'll mix up the ${names(TARGET)}. Then you put them back in this order.`);
    await new Promise((r) => setTimeout(r, 3500));
    setPhase("shuffling");
    say("The robot is mixing them up. Please watch.");
    const order = shuffled(TARGET);
    shuffledRef.current = order;
    await new Promise((r) => setTimeout(r, 2500)); // real robot job goes here
    setTable(order);
    setPhase("awaiting");
    say("All done. Put them back in order, then tell me when you're done.");
  }

  async function done() {
    if (phase !== "awaiting") return;
    setPhase("checking");
    say("Let me take a look.");
    const n = attempt + 1;
    setAttempt(n);
    const r = await checkOrder(TARGET, table);
    if (r.correct) {
      setResult("correct"); setWrong([]); setFeedback("That's right. Well done!");
      setPhase("complete"); say("That's right. Well done!");
    } else if (n >= MAX_TRIALS) {
      setResult("gave_up"); setWrong(r.misplaced); setFeedback("That was a good try. Here is the right order.");
      setPhase("reveal"); say("That was a good try. Here is the right order.");
    } else {
      setWrong(r.misplaced);
      const t = `Not quite. ${r.reason} Would you like to try again?`;
      setFeedback(t); setPhase("feedback"); say(t);
    }
  }

  function tryAgain() { setPhase("awaiting"); say("Okay. Take your time and tell me when you're done."); }

  function onHelp() {
    setHelp(true);
    say(phase === "awaiting" ? `Look at the card on top. The ${names(TARGET)}. I've let a caregiver know.` : "Of course. I've let a caregiver know.");
  }

  function stop() { setResult("stopped"); setPhase("stopped"); say("We've stopped for now. Thank you for spending time with me."); }

  function swap(i: number) {
    if (phase !== "awaiting") return;
    if (pick === null) return setPick(i);
    if (pick !== i) setTable((t) => { const c = [...t]; [c[pick], c[i]] = [c[i], c[pick]]; return c; });
    setPick(null);
  }

  function onType(e: React.FormEvent) {
    e.preventDefault();
    const t = typed.trim().toLowerCase(); setTyped("");
    if (/stop/.test(t)) stop();
    else if (/help/.test(t)) onHelp();
    else if (/done|finish|ready/.test(t)) done();
    else if (/play|game|start|yes|sure/.test(t) && (phase === "idle" || phase === "complete" || phase === "reveal")) startRound();
    else if (/again|yes|ok/.test(t) && phase === "feedback") tryAgain();
    else say("I didn't catch that. You can say done, help, or stop.");
  }

  const playing = ["intro", "shuffling", "awaiting", "checking", "feedback"].includes(phase);
  const ended = ["complete", "reveal", "stopped"].includes(phase);

  return (
    <main className="play">
      <p className="prompt" aria-live="polite">{prompt}</p>

      {phase !== "idle" && phase !== "stopped" && (
        <section className="target card" aria-label="Target order">
          <p className="small">Put them in this order</p>
          <div className="itemrow">
            {TARGET.map((id, i) => <ItemCard key={id} id={id} index={i} />)}
          </div>
        </section>
      )}

      {(phase === "idle" || ended) && (
        <div className="controls">
          <button className="primary big" onClick={startRound}>{phase === "idle" ? "Let's play" : "Play again"}</button>
        </div>
      )}

      {phase === "shuffling" && <p className="robot">🤖 The robot is mixing them up…</p>}

      {phase === "reveal" && (
        <p className="feedback">Correct order: <strong>{names(TARGET)}</strong></p>
      )}

      {(phase === "feedback" || (phase === "complete" && feedback)) && (
        <p className={`feedback ${phase === "complete" ? "ok" : ""}`} role="status">{feedback}</p>
      )}

      {playing && (
        <p className="tries" aria-label={`Try ${Math.min(attempt + 1, MAX_TRIALS)} of ${MAX_TRIALS}`}>
          {Array.from({ length: MAX_TRIALS }, (_, i) => <span key={i} className={`dot ${i < attempt ? "used" : ""}`} />)}
        </p>
      )}

      {phase === "feedback" && (
        <div className="controls"><button className="primary big" onClick={tryAgain}>Try again</button></div>
      )}

      {playing && phase !== "intro" && (
        <details className="demo" open={phase === "awaiting"}>
          <summary>Demo table (stands in for the real table and camera)</summary>
          <p className="small">Tap two items to swap them, as if the resident moved them.</p>
          <div className="itemrow">
            {table.map((id, i) => (
              <ItemCard key={i} id={id} index={i} selected={pick === i} flag={phase === "feedback" && wrong.includes(id)} onClick={() => swap(i)} />
            ))}
          </div>
        </details>
      )}

      <div className="controls">
        <button className="primary big" onClick={done} disabled={phase !== "awaiting"}>I'm done</button>
        <button onClick={() => say(prompt)} disabled={phase === "idle"}>Repeat</button>
        <button onClick={onHelp} disabled={!playing}>Help</button>
        <button className="stop" onClick={stop} disabled={phase === "stopped" || phase === "idle"}>Stop</button>
      </div>

      <form className="row" onSubmit={onType} style={{ marginTop: 24 }}>
        <input aria-label="Type a reply" placeholder="Or type: done, help, stop…" value={typed} onChange={(e) => setTyped(e.target.value)}
          style={{ flex: 1, font: "inherit", padding: 14, borderRadius: 16, border: "2px solid var(--border)" }} />
        <button type="submit">Send</button>
      </form>

      <p className="status">
        <label><input type="checkbox" checked={readAloud} onChange={(e) => setReadAloud(e.target.checked)} /> Read aloud</label>
        {" · "}<button className="linkbtn" onClick={() => { clearLive(); location.reload(); }}>Reset demo</button>
      </p>
      {/* TODO: replace the demo table with the camera check, and the timeout with the robot shuffle job. */}
    </main>
  );
}

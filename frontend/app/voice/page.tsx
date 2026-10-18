"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ItemCard } from "@/components/ItemCard";
import { MAX_TRIALS } from "@/lib/reorder";
import { voiceReset, voiceTurn, type ToolCall, type VoiceState } from "@/lib/voice";

/* eslint-disable @typescript-eslint/no-explicit-any */
const SR: any = typeof window !== "undefined" ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : null;

export default function Voice() {
  const [sid] = useState(() => `s-${Math.random().toString(36).slice(2, 8)}`);
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("Press the microphone and say: “Let's play the ordering game.”");
  const [state, setState] = useState<VoiceState | null>(null);
  const [calls, setCalls] = useState<ToolCall[]>([]);
  const [table, setTable] = useState<string[]>([]);
  const [pick, setPick] = useState<number | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hasSR, setHasSR] = useState(true);

  const recRef = useRef<any>(null);
  const listeningRef = useRef(false);
  const speakingRef = useRef(false);
  const tableRef = useRef<string[]>([]);
  const lastShuffle = useRef(0);
  tableRef.current = table;

  const startRec = useCallback(() => {
    try { if (listeningRef.current && !speakingRef.current) recRef.current?.start(); } catch { /* already started */ }
  }, []);

  const speak = useCallback((text: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.9;
    speakingRef.current = true;
    try { recRef.current?.stop(); } catch { /* not running */ } // don't listen to ourselves
    u.onend = u.onerror = () => { speakingRef.current = false; startRec(); };
    window.speechSynthesis.speak(u);
  }, [startRec]);

  const send = useCallback(async (text: string) => {
    if (!text.trim()) return;
    setHeard(text); setBusy(true); setErr(null);
    try {
      const r = await voiceTurn(sid, text, tableRef.current);
      setReply(r.reply); setCalls(r.toolCalls); setState(r.state);
      if (r.state.shuffleId !== lastShuffle.current) {
        lastShuffle.current = r.state.shuffleId;
        setTable(r.state.shuffledOrder);
        setPick(null);
      }
      speak(r.reply);
    } catch {
      setErr("Can't reach the backend (is it running on :8000?)");
    } finally {
      setBusy(false);
    }
  }, [sid, speak]);

  useEffect(() => {
    if (!SR) { setHasSR(false); return; }
    const rec = new SR();
    rec.lang = "en-US"; rec.interimResults = true; rec.continuous = false;
    rec.onresult = (e: any) => {
      let text = "", final = false;
      for (let i = e.resultIndex; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
        if (e.results[i].isFinal) final = true;
      }
      setHeard(text);
      if (final) send(text);
    };
    rec.onend = () => startRec(); // keep listening between phrases
    rec.onerror = (e: any) => {
      if (e.error === "not-allowed") { listeningRef.current = false; setListening(false); setErr("Microphone permission denied"); }
    };
    recRef.current = rec;
    return () => { listeningRef.current = false; try { rec.stop(); } catch { /* */ } };
  }, [send, startRec]);

  function toggleMic() {
    if (listening) {
      listeningRef.current = false; setListening(false);
      try { recRef.current?.stop(); } catch { /* */ }
      return;
    }
    listeningRef.current = true; setListening(true); startRec();
  }

  function swap(i: number) {
    if (state?.phase !== "awaiting") return;
    if (pick === null) return setPick(i);
    if (pick !== i) setTable((t) => { const c = [...t]; [c[pick], c[i]] = [c[i], c[pick]]; return c; });
    setPick(null);
  }

  const awaiting = state?.phase === "awaiting";
  return (
    <main className="play">
      <p className="small">Voice prototype · {hasSR ? "microphone ready" : "this browser has no speech recognition (use Chrome); typing works"}</p>

      <p className="prompt" aria-live="polite">{reply}</p>

      <div className="controls">
        <button className={`big mic ${listening ? "on" : "primary"}`} onClick={toggleMic} disabled={!hasSR}>
          {listening ? "🎙️ Listening… (tap to stop)" : "🎙️ Tap to talk"}
        </button>
        <button className="stop big" onClick={() => send("stop")}>Stop</button>
      </div>
      <p className="heard">{heard ? <>You: “{heard}”</> : " "}{busy && " …thinking"}</p>

      {state && state.target.length > 0 && state.phase !== "stopped" && (
        <>
          <section className="target card">
            <p className="small">Put them in this order</p>
            <div className="itemrow">{state.target.map((id, i) => <ItemCard key={id} id={id} index={i} />)}</div>
          </section>
          <p className="tries">
            {Array.from({ length: MAX_TRIALS }, (_, i) => <span key={i} className={`dot ${i < state.attempt ? "used" : ""}`} />)}
          </p>
          <details className="demo" open={awaiting}>
            <summary>Demo table (stands in for the real table and camera)</summary>
            <p className="small">Tap two items to swap them, then say “I'm done”.</p>
            <div className="itemrow">
              {table.map((id, i) => <ItemCard key={i} id={id} index={i} selected={pick === i} onClick={() => swap(i)} />)}
            </div>
          </details>
        </>
      )}

      <form className="row" style={{ marginTop: 24 }} onSubmit={(e) => { e.preventDefault(); send(typed); setTyped(""); }}>
        <input aria-label="Type instead" placeholder="Or type what you'd say…" value={typed} onChange={(e) => setTyped(e.target.value)}
          style={{ flex: 1, font: "inherit", padding: 14, borderRadius: 16, border: "2px solid var(--border)" }} />
        <button type="submit">Send</button>
      </form>

      <details className="demo" open>
        <summary>What the AI did (tool calls)</summary>
        {calls.length === 0 ? <p className="small">No tools called yet.</p> : calls.map((c, i) => (
          <pre key={i} className="tool">{c.name}({JSON.stringify(c.args)}) → {JSON.stringify(c.result)}</pre>
        ))}
        {state?.helpRequested && <p className="warn">⚠️ Caregiver alerted: {state.alerts.join("; ")}</p>}
      </details>

      <p className="status"><button className="linkbtn" onClick={async () => { await voiceReset(sid); location.reload(); }}>Reset</button></p>
      {err && <p className="status warn">{err}</p>}
    </main>
  );
}

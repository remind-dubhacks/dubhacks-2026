"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchTts, voiceReset, voiceStatus, voiceTurn, type ToolCall, type VoiceState } from "@/lib/voice";

/* eslint-disable @typescript-eslint/no-explicit-any */
const SR: any = typeof window !== "undefined" ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : null;

type Msg = { role: "you" | "ai"; text: string; tools?: string[]; at: number };
const GREETING = "Hello, I'm ReMind. Would you like to play a game? You can just say, play the ordering game.";
const HISTORY_KEY = "remind.voice.history";

export default function Voice() {
  const [sid] = useState(() => `s-${Math.random().toString(36).slice(2, 8)}`);
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [started, setStarted] = useState(false);
  const [log, setLog] = useState<Msg[]>([]);
  const [state, setState] = useState<VoiceState | null>(null);
  const [calls, setCalls] = useState<ToolCall[]>([]);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hasSR, setHasSR] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  const [provider, setProvider] = useState("rules");
  const [tts, setTts] = useState(false); // ElevenLabs available
  const ttsRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const recRef = useRef<any>(null);
  const listeningRef = useRef(false);
  const speakingRef = useRef(false);

  useEffect(() => {
    voiceStatus().then((st) => { setProvider(st.provider); setTts(st.tts); ttsRef.current = st.tts; });
  }, []);
  useEffect(() => {
    try { setLog(JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]")); } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(log.slice(-100))); } catch { /* ignore */ }
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);


  const startRec = useCallback(() => {
    try { if (listeningRef.current && !speakingRef.current) recRef.current?.start(); } catch { /* already started */ }
  }, []);

  const speak = useCallback(async (text: string) => {
    if (typeof window === "undefined") return;
    window.speechSynthesis?.cancel();
    audioRef.current?.pause();
    speakingRef.current = true;
    try { recRef.current?.stop(); } catch { /* not running */ } // don't listen to ourselves
    const finish = () => { speakingRef.current = false; startRec(); };
    const browserVoice = () => {
      if (!("speechSynthesis" in window)) return finish();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 0.9;
      u.onend = u.onerror = finish;
      window.speechSynthesis.speak(u);
    };
    if (!ttsRef.current) return browserVoice();
    try {
      const url = URL.createObjectURL(await fetchTts(text));
      const a = new Audio(url);
      audioRef.current = a;
      a.onended = a.onerror = () => { URL.revokeObjectURL(url); finish(); };
      await a.play();
    } catch {
      browserVoice(); // ElevenLabs failed or was blocked: use the browser voice
    }
  }, [startRec]);

  const send = useCallback(async (text: string) => {
    if (!text.trim()) return;
    setHeard(""); setBusy(true); setErr(null);
    setLog((l) => [...l, { role: "you", text: text.trim(), at: Date.now() }]);
    try {
      const r = await voiceTurn(sid, text, []);
      setCalls(r.toolCalls); setState(r.state);
      setLog((l) => [...l, { role: "ai", text: r.reply, tools: r.toolCalls.map((c) => c.name), at: Date.now() }]);
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

  function startConversation() {
    setStarted(true);
    listeningRef.current = true; setListening(true);
    setLog((l) => [...l, { role: "ai", text: GREETING, at: Date.now() }]);
    speak(GREETING); // recognition starts when the greeting finishes
  }

  function endConversation() {
    listeningRef.current = false; setListening(false); setStarted(false);
    try { recRef.current?.stop(); } catch { /* */ }
    window.speechSynthesis?.cancel(); audioRef.current?.pause();
    send("stop");
  }

  return (
    <main className="play voice">
      <h1>ReMind</h1>
      <p className="small">{hasSR ? `Brain: ${provider === "gemini" ? "Gemini" : "keyword rules (set GEMINI_API_KEY)"} · Voice: ${tts ? "ElevenLabs" : "browser (set ELEVENLABS_API_KEY)"}` : "This browser has no speech recognition (use Chrome); typing works."}</p>

      {!started ? (
        <button className="primary big start" onClick={startConversation} disabled={!hasSR}>🎙️ Start conversation</button>
      ) : (
        <div className="row">
          <span className={`badge ${listening && !busy ? "on live-dot" : ""}`}>{busy ? "Thinking…" : "Listening…"}</span>
          <button className="stop" onClick={endConversation}>Stop</button>
        </div>
      )}
      {heard && <p className="heard">“{heard}”</p>}

      <h2>Conversation</h2>
      <div className="chat" aria-live="polite">
        {log.length === 0 && <p className="small">Nothing yet. Press Start conversation.</p>}
        {log.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <span className="who">{m.role === "you" ? "You" : "ReMind"}</span>
            {m.text && <p>{m.text}</p>}
            {m.tools && m.tools.length > 0 && <p className="chips">{m.tools.map((t, j) => <span key={j} className="chip">🔧 {t}</span>)}</p>}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form className="row" style={{ marginTop: 16 }} onSubmit={(e) => { e.preventDefault(); send(typed); setTyped(""); }}>
        <input aria-label="Type instead" placeholder="Or type what you'd say…" value={typed} onChange={(e) => setTyped(e.target.value)}
          style={{ flex: 1, font: "inherit", padding: 14, borderRadius: 16, border: "2px solid var(--border)" }} />
        <button type="submit">Send</button>
      </form>

      {state?.helpRequested && <p className="warn">⚠️ Caregiver alerted: {state.alerts.join("; ")}</p>}
      <details className="demo">
        <summary>Last tool calls (debug)</summary>
        {calls.length === 0 ? <p className="small">None yet.</p> : calls.map((c, i) => (
          <pre key={i} className="tool">{c.name}({JSON.stringify(c.args)}) → {JSON.stringify(c.result)}</pre>
        ))}
      </details>
      <p className="status">
        <button className="linkbtn" onClick={async () => { await voiceReset(sid); try { localStorage.removeItem(HISTORY_KEY); } catch { /* */ } location.reload(); }}>Clear history &amp; reset</button>
      </p>
      {err && <p className="status warn">{err}</p>}
    </main>
  );
}

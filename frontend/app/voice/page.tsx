"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LiveVoice } from "@/lib/liveVoice";
import { fetchTools, fetchTts, voiceReset, voiceStatus, voiceTurn, type ToolCall, type ToolInfo, type VoiceState } from "@/lib/voice";

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
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [showTools, setShowTools] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hasSR, setHasSR] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  const [provider, setProvider] = useState("rules");
  const [tts, setTts] = useState(false); // ElevenLabs available
  const ttsRef = useRef(false);
  const [liveOk, setLiveOk] = useState(false); // Gemini Live available on the backend
  const [mode, setMode] = useState<"voice" | "chat">("voice");
  const [readAloud, setReadAloud] = useState(false); // chat mode: speak replies too
  const modeRef = useRef<"voice" | "chat">("voice");
  const readAllowed = useRef(false);
  const liveRef = useRef<LiveVoice | null>(null);
  const aiBuf = useRef("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const recRef = useRef<any>(null);
  const listeningRef = useRef(false);
  const speakingRef = useRef(false);

  useEffect(() => {
    try { const m = localStorage.getItem("remind.mode"); if (m === "chat" || m === "voice") { setMode(m); modeRef.current = m; } } catch { /* ignore */ }
  }, []);
  useEffect(() => { fetchTools().then(setTools); }, []);
  useEffect(() => {
    voiceStatus().then((st) => { setLiveOk(st.live); setProvider(st.provider); setTts(st.tts); ttsRef.current = st.tts; });
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
    if (liveRef.current) {
      setLog((l) => [...l, { role: "you", text: text.trim(), at: Date.now() }]);
      liveRef.current.sendText(text);
      return;
    }
    setHeard(""); setBusy(true); setErr(null);
    setLog((l) => [...l, { role: "you", text: text.trim(), at: Date.now() }]);
    try {
      const r = await voiceTurn(sid, text, []);
      setCalls(r.toolCalls); setState(r.state);
      setLog((l) => [...l, { role: "ai", text: r.reply, tools: r.toolCalls.map((c) => c.name), at: Date.now() }]);
      if (modeRef.current === "voice" || readAllowed.current) speak(r.reply);
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

  async function startLive() {
    setErr(null);
    const g = new LiveVoice({
      onUser: (text, final) => {
        setHeard(final ? "" : text);
        if (final && text.trim()) setLog((l) => [...l, { role: "you", text: text.trim(), at: Date.now() }]);
      },
      onAiDelta: (t) => { aiBuf.current += t; setBusy(true); },
      onAiDone: (t) => {
        const text = (t || aiBuf.current).trim();
        aiBuf.current = ""; setBusy(false);
        if (text) setLog((l) => [...l, { role: "ai", text, at: Date.now() }]);
      },
      onTool: (call, st) => {
        setCalls((c) => [call, ...c].slice(0, 8)); setState(st);
        setLog((l) => [...l, { role: "ai", text: "", tools: [call.name], at: Date.now() }]);
      },
      onError: (m) => setErr(m),
      onClose: () => { setStarted(false); setListening(false); setBusy(false); },
    });
    try {
      await g.start();
      liveRef.current = g;
      setStarted(true); setListening(true);
    } catch (e) {
      setErr(`Could not start voice: ${e}`);
    }
  }

  function switchMode(m: "voice" | "chat") {
    if (m === mode) return;
    if (started) endConversation();
    window.speechSynthesis?.cancel(); audioRef.current?.pause();
    setMode(m); modeRef.current = m;
    try { localStorage.setItem("remind.mode", m); } catch { /* ignore */ }
  }

  function startConversation() {
    if (liveOk) return void startLive();
    setStarted(true);
    listeningRef.current = true; setListening(true);
    setLog((l) => [...l, { role: "ai", text: GREETING, at: Date.now() }]);
    speak(GREETING); // recognition starts when the greeting finishes
  }

  function endConversation() {
    if (liveRef.current) {
      liveRef.current.emergencyStop();
      const g = liveRef.current;
      liveRef.current = null;
      setTimeout(() => g.stop(), 2500); // let the goodbye finish
      setStarted(false); setListening(false);
      return;
    }
    listeningRef.current = false; setListening(false); setStarted(false);
    try { recRef.current?.stop(); } catch { /* */ }
    window.speechSynthesis?.cancel(); audioRef.current?.pause();
    send("stop");
  }

  return (
    <main className="play voice">
      <h1>ReMind</h1>
      <div className="row" style={{ justifyContent: "space-between" }}>
      <div className="seg" role="tablist" aria-label="Mode">
        <button role="tab" aria-selected={mode === "voice"} className={mode === "voice" ? "active" : ""} onClick={() => switchMode("voice")}>🎙️ Voice</button>
        <button role="tab" aria-selected={mode === "chat"} className={mode === "chat" ? "active" : ""} onClick={() => switchMode("chat")}>💬 Chat</button>
      </div>
      <button className="toolsbtn" onClick={() => setShowTools((v) => !v)} aria-expanded={showTools}>🔧 Tools ({tools.length})</button>
      </div>
      {showTools && (
        <section className="card toolmenu" aria-label="Available tools">
          <p className="small">What the assistant can do. It picks these by itself from what you say.</p>
          {tools.map((t) => {
            const recent = calls.some((c) => c.name === t.name);
            return (
              <div key={t.name} className={`tool-item ${recent ? "recent" : ""}`}>
                <div className="row">
                  <code>{t.name}{t.params.length ? `(${t.params.join(", ")})` : "()"}</code>
                  <span className={`badge st-${t.status}`}>{t.status}</span>
                  {recent && <span className="badge on">just used</span>}
                </div>
                <p className="small" style={{ margin: "4px 0" }}>{t.does}</p>
                <button className="linkbtn" onClick={() => { setShowTools(false); if (mode === "chat" || started) send(t.example); else setTyped(t.example); }}>
                  Try: “{t.example}”
                </button>
              </div>
            );
          })}
        </section>
      )}
      {mode === "voice" && <p className="small">{liveOk ? "Live mode: Gemini Live, always listening, you can interrupt" : hasSR ? `Brain: ${provider === "gemini" ? "Gemini" : "keyword rules (set GEMINI_API_KEY)"} · Voice: ${tts ? "ElevenLabs" : "browser (set ELEVENLABS_API_KEY)"}` : "This browser has no speech recognition (use Chrome); try Chat mode."}</p>}
      {mode === "chat" && (
        <p className="small">Type to talk to ReMind. <label><input type="checkbox" checked={readAloud} onChange={(e) => { setReadAloud(e.target.checked); readAllowed.current = e.target.checked; }} /> Read replies aloud</label></p>
      )}

      {mode === "voice" && (!started ? (
        <button className="primary big start" onClick={startConversation} disabled={!hasSR && !(liveOk)}>🎙️ Start conversation</button>
      ) : (
        <div className="row">
          <span className={`badge ${listening && !busy ? "on live-dot" : ""}`}>{busy ? "Thinking…" : "Listening…"}</span>
          <button className="stop" onClick={endConversation}>Stop</button>
        </div>
      ))}
      {mode === "voice" && heard && <p className="heard">“{heard}”</p>}

      <h2>Conversation</h2>
      <div className="chat" aria-live="polite">
        {log.length === 0 && <p className="small">{mode === "chat" ? "Nothing yet. Type “hello” or “let's play the ordering game”." : "Nothing yet. Press Start conversation."}</p>}
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
        <input aria-label="Type instead" placeholder={mode === "chat" ? "Type a message…" : "Or type what you'd say…"} autoFocus={mode === "chat"} value={typed} onChange={(e) => setTyped(e.target.value)}
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

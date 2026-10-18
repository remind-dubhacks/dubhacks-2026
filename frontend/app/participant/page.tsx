"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type RobotJob, type Session } from "@/lib/api";

const ROBOT_TEXT: Record<string, string> = {
  queued: "Getting ready…",
  moving: "The robot is moving",
  verifying: "Checking with your caregiver…",
  complete: "Done",
  needs_staff: "A caregiver is coming to help",
  stopped: "Stopped",
};

const CAN_CHOOSE = new Set(["prompting", "complete"]);

function speak(text: string, enabled: boolean) {
  if (!enabled || typeof window === "undefined" || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 0.9;
  window.speechSynthesis.speak(u);
}

function Participant() {
  const sessionId = useSearchParams().get("session");
  const [session, setSession] = useState<Session | null>(null);
  const [prompt, setPrompt] = useState("");
  const [typed, setTyped] = useState("");
  const [readAloud, setReadAloud] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const polling = useRef(false);

  const show = useCallback(
    (text: string | null | undefined) => {
      if (!text) return;
      setPrompt(text);
      speak(text, readAloud);
    },
    [readAloud],
  );

  // Initial load, then a slow refresh so caregiver actions (resume, stop) show up here.
  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    api.session(sessionId).then((s) => {
      if (!alive) return;
      setSession(s);
      show(s.lastReply);
    }, (e) => setError(String(e)));
    const t = setInterval(async () => {
      if (polling.current) return;
      try {
        const s = await api.session(sessionId);
        setSession((prev) => {
          if (prev && s.lastReply && s.lastReply !== prev.lastReply) show(s.lastReply);
          return s;
        });
      } catch {
        /* keep last known state */
      }
    }, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [sessionId, show]);

  async function pollJob(jobId: string) {
    polling.current = true;
    try {
      for (;;) {
        const job: RobotJob = await api.job(jobId);
        setSession((s) => (s ? { ...s, state: job.sessionState ?? s.state } : s));
        if (["succeeded", "failed", "stopped"].includes(job.status)) {
          show(job.reply);
          break;
        }
        await new Promise((r) => setTimeout(r, 700));
      }
    } finally {
      polling.current = false;
      if (sessionId) setSession(await api.session(sessionId));
    }
  }

  async function send(text: string) {
    if (!sessionId || !text.trim()) return;
    setError(null);
    try {
      const { turn, session: s } = await api.turn(sessionId, text);
      setSession(s);
      show(turn.reply);
      if (turn.intent === "select_object" && turn.objectId && s.state === "validated") {
        const job = await api.createJob(sessionId, turn.objectId);
        setSession({ ...s, state: "queued" });
        await pollJob(job._id);
      }
    } catch (e) {
      setError("Something went wrong. A caregiver can help.");
      console.error(e);
    }
  }

  async function stop() {
    if (!sessionId) return;
    const r = await api.stop(sessionId);
    if (r.session) {
      setSession(r.session);
      show(r.session.lastReply);
    }
  }

  if (!sessionId) {
    return (
      <main>
        <p className="prompt">Please ask a caregiver to start a session.</p>
      </main>
    );
  }

  const state = session?.state ?? "idle";
  const canChoose = CAN_CHOOSE.has(state);

  return (
    <main>
      <p className="prompt" aria-live="polite">{prompt || "…"}</p>

      <div className="choices">
        {session?.choices.map((c) => (
          <button key={c.objectId} className="choice" disabled={!canChoose} onClick={() => send(c.objectId)}>
            {c.label}
          </button>
        ))}
      </div>

      <form
        className="row"
        style={{ marginTop: 24 }}
        onSubmit={(e) => {
          e.preventDefault();
          send(typed);
          setTyped("");
        }}
      >
        <input
          aria-label="Type a reply"
          placeholder="Or type here…"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          style={{ flex: 1, font: "inherit", padding: 14, borderRadius: 16, border: "2px solid var(--border)" }}
        />
        <button type="submit">Send</button>
      </form>

      <div className="controls">
        <button onClick={() => send("repeat")} disabled={state === "stopped"}>Repeat</button>
        <button onClick={() => send("help")} disabled={state === "stopped"}>Help</button>
        <button className="stop" onClick={stop} disabled={state === "stopped"}>Stop</button>
      </div>

      <p className="status">
        Robot: <strong>{ROBOT_TEXT[state] ?? "Ready"}</strong>
        {" · "}
        <label>
          <input type="checkbox" checked={readAloud} onChange={(e) => setReadAloud(e.target.checked)} /> Read aloud
        </label>
      </p>
      {error && <p className="status warn">{error}</p>}
      {/* TODO(P1): add push-to-talk mic input that feeds transcripts into send(). */}
    </main>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Participant />
    </Suspense>
  );
}

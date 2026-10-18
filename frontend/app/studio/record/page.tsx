"use client";

/* Focused recording screen for the person on the leader arm: one instruction, one countdown,
 * big Ready / Stop. Everything else lives in the full Robot Studio. */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { studio, type CampaignStatus, type StudioStatus } from "@/lib/studio";
import StudioVoice, { claimVoice } from "../StudioVoice";

type Phase = { key: string; label: string; tone: "wait" | "go" | "reset" | "rest" | "stop" | "done" };

function phaseOf(c: CampaignStatus | null, s: StudioStatus | null): Phase {
  const p = s?.process;
  if (p?.running && p.kind === "record") {
    if (p.phase === "reset") return { key: `reset-${p.episode}`, label: "Reset the keychain", tone: "reset" };
    if (p.phase === "finishing") return { key: "saving", label: "Saving…", tone: "rest" };
    if (p.phase === "recording") return { key: `ep-${p.episode}`, label: `Episode ${(p.episode ?? 0) + 1} of ${c?.current?.episodes ?? "?"}: go`, tone: "go" };
    return { key: "starting", label: "Starting…", tone: "rest" };
  }
  switch (c?.state) {
    case "setup":
    case "waiting_ready":
      return { key: "wait", label: "Set up, then press Ready", tone: "wait" };
    case "break":
      return { key: "break", label: "Short break", tone: "rest" };
    case "paused":
    case "error":
      return { key: "paused", label: "Paused", tone: "stop" };
    case "uploading":
      return { key: "up", label: "Uploading…", tone: "rest" };
    case "done":
      return { key: "done", label: "All done", tone: "done" };
    default:
      return { key: "idle", label: "Not started", tone: "wait" };
  }
}

/** "Swap LEFT and RIGHT: a to slot 4, b to slot 1, a to slot 3. Start: slot 1 x, ... End: slot 1 y, ..." */
function parsePlan(variation?: string) {
  if (!variation) return null;
  const [beforeEnd, endPart = ""] = variation.split(" End: ");
  const [movePart, startPart = ""] = beforeEnd.split(" Start: ");
  const idx = movePart.indexOf(": ");
  const title = idx > 0 ? movePart.slice(0, idx) : movePart;
  const clean = (t: string) => t.replace(/\.\s*$/, "").split(/, then |, /).map((x) => x.trim()).filter(Boolean);
  return { title, steps: clean(idx > 0 ? movePart.slice(idx + 2) : ""), lineup: clean(startPart), end: clean(endPart) };
}

export default function RecordPage() {
  const [status, setStatus] = useState<StudioStatus | null>(null);
  const [campaign, setCampaign] = useState<CampaignStatus | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const lastSeq = useRef(0);
  const phaseStart = useRef<{ key: string; t: number }>({ key: "", t: Date.now() });

  useEffect(() => {
    const tick = async () => {
      try {
        const [s, c] = await Promise.all([studio.status(), studio.campaign()]);
        setStatus(s);
        setCampaign(c);
        const l = await studio.logs(lastSeq.current);
        if (l.lines.length) {
          lastSeq.current = l.last;
          setLogs((p) => [...p, ...l.lines.map((x) => x.line)].slice(-300));
        }
        setErr(null);
      } catch {
        setErr("Can't reach the robot worker. Is it running in Terminal?");
      }
    };
    tick();
    const t = setInterval(tick, 700);
    const clock = setInterval(() => setNow(Date.now()), 250);
    return () => {
      clearInterval(t);
      clearInterval(clock);
    };
  }, []);

  const phase = phaseOf(campaign, status);
  if (phase.key !== phaseStart.current.key) phaseStart.current = { key: phase.key, t: Date.now() };
  const cfg = campaign?.config;
  const span = phase.tone === "go" ? cfg?.episodeSeconds : phase.tone === "reset" ? cfg?.resetSeconds : phase.key === "break" ? cfg?.breakSeconds : undefined;
  const left = span ? Math.max(0, Math.ceil(span - (now - phaseStart.current.t) / 1000)) : null;

  const target = campaign?.targets[0];
  const done = campaign?.totalDone ?? 0;
  const total = campaign?.totalTarget ?? 0;
  const waiting = campaign?.state === "setup" || campaign?.state === "waiting_ready";
  const stopped = !campaign?.running || campaign?.paused;
  const act = (a: Parameters<typeof studio.campaignAction>[0]) => {
    claimVoice(true);
    studio.campaignAction(a).catch((e) => setErr(e.message));
  };

  return (
    <main className="rec">
      <div className="rec-top">
        <span className="small">{target ? `“${target.task}”` : "No campaign set up"}</span>
        <Link href="/studio" className="small">Full Studio →</Link>
      </div>

      <div className="rec-progress">
        <strong>{done}</strong> / {total} episodes
        <div className="progress"><div style={{ width: `${total ? (done / total) * 100 : 0}%` }} /></div>
      </div>

      <div className={`rec-phase ${phase.tone}`}>
        <div className="rec-label">{phase.label}</div>
        {left !== null && <div className="rec-count">{left}</div>}
        {phase.tone === "go" && <div className="rec-hint">Done with the moves? Rest the arm and wait. It saves automatically.</div>}
        {phase.tone === "reset" && <div className="rec-hint">Put the keyrings back to START. Nothing to press.</div>}
      </div>

      {(() => {
        const plan = parsePlan(campaign?.current?.variation);
        if (!plan) return <p className="rec-msg">{campaign?.message || "Open the full Studio to set up a recording campaign."}</p>;
        const resetting = phase.tone === "reset";
        return (
          <div className="rec-steps">
            <div className="rec-steps-title">{plan.title}</div>
            {plan.steps.length > 0 && (
              <ol className={resetting ? "dim" : ""}>
                {plan.steps.map((st, i) => <li key={i}>{st}</li>)}
              </ol>
            )}
            {plan.lineup.length > 0 && (
              <div className={`rec-lineup ${resetting || phase.tone === "wait" ? "focus" : ""}`}>
                <span className="rec-lineup-label">{phase.tone === "reset" ? "Reset to START:" : "START:"}</span>
                {plan.lineup.map((x, i) => <span key={i} className="badge">{x}</span>)}
              </div>
            )}
            {plan.end.length > 0 && (
              <div className={`rec-lineup end ${phase.tone === "go" ? "focus" : ""}`}>
                <span className="rec-lineup-label">END:</span>
                {plan.end.map((x, i) => <span key={i} className="badge">{x}</span>)}
              </div>
            )}
            {(phase.tone === "stop" || phase.key === "break" || phase.key === "done") && <p className="rec-msg">{campaign?.message}</p>}
          </div>
        );
      })()}
      {err && <p className="warn">{err}</p>}

      <div className="rec-buttons">
        {waiting && <button className="primary huge" onClick={() => act("ready")}>Ready</button>}
        {stopped && !waiting && campaign?.state !== "done" && (
          <button className="primary huge" onClick={() => act("start")}>{done > 0 || campaign?.paused ? "Resume" : "Start"}</button>
        )}
        {stopped && !status?.process.running && (
          <button className="huge" onClick={async () => {
            claimVoice(true);
            try { const r = await studio.clearFault(); setErr(r.cleared ? null : "Fault still there: unplug the follower's DC power for 10 s."); }
            catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
          }}>Clear gripper fault</button>
        )}
        <button
          className="stop huge"
          onClick={() => {
            const recordingNow = phase.tone === "go" || phase.tone === "reset";
            if (recordingNow && !confirm("Emergency stop?\n\nThis DISCARDS the episode in progress. Episodes end and save automatically; you never need Stop to finish one.")) return;
            claimVoice(true);
            studio.stop().catch(() => {});
            if (campaign?.running) studio.campaignAction("pause").catch(() => {});
          }}
        >
          {phase.tone === "go" || phase.tone === "reset" ? "Emergency stop (discards episode)" : "Stop"}
        </button>
      </div>

      <StudioVoice
        compact
        status={status}
        logs={logs}
        datasets={[]}
        uploads={{}}
        rec={{ repo: cfg?.repo ?? "", task: target?.task ?? "", episodes: campaign?.current?.episodes ?? 5, episodeSeconds: cfg?.episodeSeconds ?? 20, resetSeconds: cfg?.resetSeconds ?? 10 }}
        campaign={campaign}
        actions={{
          teleop: async () => { await studio.teleop(true); },
          record: async () => act("start"),
          stop: async () => { await studio.stop(); },
          checkMotors: async () => studio.health(),
        }}
      />
      <p className="small">Say “ready”, “stop”, “resume” or “progress”. Grip the keychain gently; never squeeze the trigger hard.</p>
    </main>
  );
}

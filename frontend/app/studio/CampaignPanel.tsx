"use client";

/* Recording campaign: plan targets, then the worker walks the operator through batches
 * (spoken by StudioVoice), checks the camera, records, and uploads/trains at the end. */

import { useEffect, useState } from "react";
import { studio, type CampaignConfig, type CampaignStatus } from "@/lib/studio";

const variations = (o: string, spot: string) => [
  `${o} on spot ${spot}, label facing the camera`,
  `${o} on spot ${spot}, turned slightly left`,
  `${o} on spot ${spot}, turned slightly right`,
  `${o} on spot ${spot}, nudged 2 cm toward the robot`,
  `${o} on spot ${spot}, nudged 2 cm away from the robot`,
];

const PRESETS: Record<string, (repoUser: string) => Partial<CampaignConfig>> = {
  "ReMind demo (tea + coffee)": (u) => ({
    repo: `${u}/remind-sort`,
    targets: [
      { id: "tea", object: "tea box", task: "pick up the tea box and place it in the tray", target: 50, variations: variations("tea box", "A") },
      { id: "coffee", object: "coffee box", task: "pick up the coffee box and place it in the tray", target: 50, variations: variations("coffee box", "B") },
    ],
  }),
  "Practice props (keychain, pen, keycap)": (u) => ({
    repo: `${u}/remind-practice`,
    targets: [
      { id: "keychain", object: "blue keychain", task: "pick up the blue keychain and place it in the tray", target: 30, variations: variations("blue keychain", "A") },
      { id: "pen", object: "pink pen", task: "pick up the pink pen and place it in the tray", target: 30, variations: variations("pink pen", "B") },
      { id: "keycap", object: "white keycap", task: "pick up the white keycap and place it in the tray", target: 30, variations: variations("white keycap", "C") },
    ],
  }),
};

const STATE_TEXT: Record<string, string> = {
  idle: "Not started",
  preflight: "Starting",
  setup: "Operator: set up the scene",
  checking: "Checking the camera",
  waiting_ready: "Waiting for operator: say “ready”",
  recording: "Recording",
  break: "Break",
  paused: "Paused",
  uploading: "Uploading to Perceptron",
  training: "Training",
  done: "Done",
  error: "Error",
};

export default function CampaignPanel({ status, hfUser, onError }: { status: CampaignStatus | null; hfUser: string; onError: (e: string | null) => void }) {
  const [plan, setPlan] = useState<CampaignConfig | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (status && !editing) setPlan(status.config);
  }, [status, editing]);

  if (!status || !plan) return null;
  const active = status.running;
  const waiting = status.state === "setup" || status.state === "waiting_ready";
  const pct = status.totalTarget ? Math.min(100, (status.totalDone / status.totalTarget) * 100) : 0;

  const act = (a: Parameters<typeof studio.campaignAction>[0]) => studio.campaignAction(a).then(() => onError(null), (e) => onError(e.message));
  const save = async () => {
    try {
      await studio.campaignConfig(plan);
      setEditing(false);
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };
  const upd = (patch: Partial<CampaignConfig>) => {
    setEditing(true);
    setPlan({ ...plan, ...patch });
  };
  const updTarget = (i: number, patch: Partial<CampaignConfig["targets"][number]>) =>
    upd({ targets: plan.targets.map((t, j) => (j === i ? { ...t, ...patch } : t)) });

  return (
    <section>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Recording campaign</h2>
        <a className="primary" href="/studio/record" style={{ padding: "10px 18px", borderRadius: 999, textDecoration: "none" }}>Open simple Record screen →</a>
      </div>
      <p className="small">
        Set the targets once, then a teammate on the leader arm just follows the spoken prompts. Each batch: set up → camera check → “ready” → record → break. When every target is reached it uploads and starts training. Any fault pauses it; it never retries by itself.
      </p>

      <div className="card campaign-status">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className="badge">{STATE_TEXT[status.state] ?? status.state}</span>
          <span className="small">{status.totalDone} / {status.totalTarget} episodes · dataset has {status.datasetEpisodes}</span>
        </div>
        <div className="progress" style={{ margin: "12px 0" }}><div style={{ width: `${pct}%` }} /></div>
        <p className="campaign-msg" aria-live="polite">{status.message || "Press Start campaign when the arms and cameras are ready."}</p>
        {status.current && (
          <p className="small">
            Batch {status.current.batch} of <strong>{status.current.object}</strong> · {status.current.episodes} episodes · {status.current.variation}
          </p>
        )}
        <div className="row">
          {waiting && <button className="primary big" onClick={() => act("ready")}>Ready: start recording</button>}
          {!active || status.paused ? (
            <button className="primary" onClick={() => act("start")} disabled={editing}>{status.paused || status.totalDone > 0 ? "Start / resume campaign" : "Start campaign"}</button>
          ) : (
            <button onClick={() => act("pause")}>Pause after this batch</button>
          )}
          {active && <button className="stop" onClick={() => act("stop")}>Stop now</button>}
          {!active && status.totalDone > 0 && <button className="chip" onClick={() => confirm("Reset campaign progress counters? Recorded data is kept.") && act("reset-progress")}>Reset counters</button>}
        </div>
        {status.jobId && <p className="small">Training job: <code>{status.jobId}</code> (see Train &amp; deploy)</p>}
      </div>

      <div className="grid2" style={{ marginTop: 12 }}>
        {status.targets.map((t) => (
          <div key={t.id} className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{t.object}</strong>
              <span className="small">{t.done} / {t.target}</span>
            </div>
            <div className="progress" style={{ marginTop: 8 }}><div style={{ width: `${Math.min(100, (t.done / Math.max(1, t.target)) * 100)}%` }} /></div>
            <p className="small" style={{ marginBottom: 0 }}>“{t.task}”</p>
          </div>
        ))}
      </div>

      <details style={{ marginTop: 16 }} open={!active && status.totalDone === 0}>
        <summary><strong>Plan</strong> <span className="small">{active ? "(stop the campaign to edit)" : ""}</span></summary>
        <fieldset disabled={active} style={{ border: 0, padding: 0, margin: "12px 0 0" }}>
          <div className="row">
            {Object.entries(PRESETS).map(([label, make]) => (
              <button key={label} className="chip" onClick={() => upd(make(hfUser || "remind"))}>{label}</button>
            ))}
          </div>
          <div className="grid3" style={{ marginTop: 12 }}>
            <label className="small">Dataset<input value={plan.repo} onChange={(e) => upd({ repo: e.target.value })} /></label>
            <label className="small">Episodes per batch<input type="number" min={1} value={plan.batchSize} onChange={(e) => upd({ batchSize: +e.target.value })} /></label>
            <label className="small">Seconds per episode<input type="number" min={5} value={plan.episodeSeconds} onChange={(e) => upd({ episodeSeconds: +e.target.value })} /></label>
            <label className="small">Reset seconds<input type="number" min={0} value={plan.resetSeconds} onChange={(e) => upd({ resetSeconds: +e.target.value })} /></label>
            <label className="small">Break between batches (s)<input type="number" min={0} value={plan.breakSeconds} onChange={(e) => upd({ breakSeconds: +e.target.value })} /></label>
            <label className="small">Training steps<input type="number" min={100} max={10000} value={plan.trainSteps} onChange={(e) => upd({ trainSteps: Math.min(10000, +e.target.value) })} /></label>
          </div>
          <div className="row small" style={{ marginTop: 8 }}>
            <label style={{ flexDirection: "row" }}><input type="checkbox" checked={plan.visionCheck} onChange={(e) => upd({ visionCheck: e.target.checked })} /> Camera check before each batch (teach the objects first)</label>
            <label style={{ flexDirection: "row" }}><input type="checkbox" checked={plan.autoUpload} onChange={(e) => upd({ autoUpload: e.target.checked })} /> Auto-upload when done</label>
            <label style={{ flexDirection: "row" }}><input type="checkbox" checked={plan.autoTrain} onChange={(e) => upd({ autoTrain: e.target.checked })} /> Auto-train after upload (uses 1 of the team's 2 training jobs)</label>
          </div>

          <table className="table" style={{ marginTop: 12 }}>
            <thead><tr><th>Object (vision name)</th><th>Task instruction</th><th>Episodes</th><th>Setup variations (one per line)</th><th /></tr></thead>
            <tbody>
              {plan.targets.map((t, i) => (
                <tr key={i}>
                  <td><input value={t.object} onChange={(e) => updTarget(i, { object: e.target.value, id: t.id || e.target.value.replace(/\W+/g, "-") })} /></td>
                  <td><input value={t.task} onChange={(e) => updTarget(i, { task: e.target.value })} /></td>
                  <td style={{ width: 90 }}><input type="number" min={1} value={t.target} onChange={(e) => updTarget(i, { target: +e.target.value })} /></td>
                  <td><textarea rows={3} value={t.variations.join("\n")} onChange={(e) => updTarget(i, { variations: e.target.value.split("\n").filter(Boolean) })} /></td>
                  <td><button className="chip" onClick={() => upd({ targets: plan.targets.filter((_, j) => j !== i) })}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <button className="chip" onClick={() => upd({ targets: [...plan.targets, { id: `obj${plan.targets.length + 1}`, object: "", task: "pick up the ... and place it in the tray", target: 50, variations: [] }] })}>+ Add object</button>
            <button className="primary" onClick={save} disabled={!editing}>Save plan</button>
            {editing && <button onClick={() => { setEditing(false); setPlan(status.config); }}>Discard changes</button>}
          </div>
          <p className="small">For the demo policy, task instructions must match the robot worker’s (tea / coffee). Practice props are for testing the pipeline and vision.</p>
        </fieldset>
      </details>

      {status.history.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="small">Campaign log</summary>
          <ul className="small">
            {status.history.slice().reverse().map((h, i) => (
              <li key={i}>{new Date(h.t * 1000).toLocaleTimeString()}: {h.message}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

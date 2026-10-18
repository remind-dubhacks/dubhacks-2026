"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import StudioVoice from "./StudioVoice";
import VisionPanel from "./VisionPanel";
import CampaignPanel from "./CampaignPanel";
import { studio, workerUrl, type ArmStatus, type CampaignStatus, type Dataset, type MotorHealth, type StudioStatus, type UploadState } from "@/lib/studio";

const MIN_EPISODES = 50; // Perceptron mentors: ~50 demonstrations is the practical minimum

function asList(x: unknown): Record<string, unknown>[] {
  if (Array.isArray(x)) return x as Record<string, unknown>[];
  if (x && typeof x === "object") {
    for (const k of ["items", "data", "jobs", "deployments", "results"]) {
      const v = (x as Record<string, unknown>)[k];
      if (Array.isArray(v)) return v as Record<string, unknown>[];
    }
  }
  return [];
}

function Arm({ name, arm }: { name: string; arm?: ArmStatus }) {
  const cal = arm?.calibration;
  const narrow = cal ? Object.entries(cal).filter(([k, v]) => k !== "wrist_roll" && v < 500) : [];
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{name}</h2>
      <p className="small">{arm?.port || "port not set"}</p>
      <div className="row small">
        <span className="badge">{arm?.connected ? "USB connected" : "not connected"}</span>
        <span className="badge">{cal ? "calibrated" : "not calibrated"}</span>
      </div>
      {narrow.length > 0 && <p className="small warn">Narrow calibration on {narrow.map(([k]) => k).join(", ")}: recalibrate.</p>}
    </div>
  );
}

export default function Studio() {
  const [status, setStatus] = useState<StudioStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const lastSeq = useRef(0);
  const logBox = useRef<HTMLPreElement>(null);

  const [cams, setCams] = useState<{ index: number; width: number; height: number }[] | null>(null);
  const [previews, setPreviews] = useState(false);
  const [side, setSide] = useState(0);
  const [wrist, setWrist] = useState(1);

  const [rec, setRec] = useState({ repo: "", task: "pick up the tea box and place it in the tray", episodes: 10, episodeSeconds: 20, resetSeconds: 10, rerun: true });

  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [uploads, setUploads] = useState<Record<string, UploadState>>({});
  const [remote, setRemote] = useState<Record<string, unknown> | null>(null);
  const [datasetId, setDatasetId] = useState("");
  const [steps, setSteps] = useState(1000);
  const [campaign, setCampaign] = useState<CampaignStatus | null>(null);
  const [health, setHealth] = useState<Awaited<ReturnType<typeof studio.health>> | null>(null);
  const [jobs, setJobs] = useState<Record<string, unknown>[]>([]);
  const [deployments, setDeployments] = useState<Record<string, unknown>[]>([]);

  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // Poll status + logs.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await studio.status();
        if (!alive) return;
        setStatus(s);
        setOffline(false);
        studio.campaign().then(setCampaign, () => {});
        const l = await studio.logs(lastSeq.current);
        if (l.lines.length) {
          lastSeq.current = l.last;
          setLogs((prev) => [...prev, ...l.lines.map((x) => x.line)].slice(-600));
        }
      } catch {
        if (alive) setOffline(true);
      }
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (logBox.current) logBox.current.scrollTop = logBox.current.scrollHeight;
  }, [logs]);

  // One-time defaults from worker config.
  const seeded = useRef(false);
  useEffect(() => {
    if (!status || seeded.current) return;
    seeded.current = true;
    setSide(status.cameras.side);
    setWrist(status.cameras.wrist);
    setRec((r) => ({ ...r, repo: `${status.hfUser || "remind"}/remind-sort` }));
  }, [status]);

  const refreshData = useCallback(() => {
    studio.datasets().then(setDatasets, () => {});
    studio.uploads().then(setUploads, () => {});
  }, []);
  useEffect(() => {
    refreshData();
    const t = setInterval(refreshData, 3000);
    return () => clearInterval(t);
  }, [refreshData]);

  const busy = status?.process.running ?? false;
  const p = status?.process;
  const recording = busy && p?.kind === "record";
  const armsReady = status?.follower.connected && status?.leader.connected && status?.follower.calibration && status?.leader.calibration;

  if (offline && !status) {
    return (
      <main>
        <h1>Robot Studio</h1>
        <div className="card">
          <p>Can’t reach the robot worker at <code>{workerUrl}</code>.</p>
          <p className="small">Start it from <strong>Terminal.app</strong> (it needs Terminal’s camera permission):</p>
          <pre className="log">cd ~/dubhacks-2026/robot_worker && uv run uvicorn worker.main:app --port 8001</pre>
        </div>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 1200 }}>
      <h1>Robot Studio</h1>
      <p className="small">
        Teleop, record demonstrations, and train on Perceptron. Keep hands clear of the follower while it moves. The physical power switch is the emergency stop.
      </p>
      {offline && <p className="warn">Lost connection to the robot worker…</p>}
      {err && <p className="warn">⚠ {err}</p>}

      <StudioVoice
        status={status}
        logs={logs}
        datasets={datasets}
        uploads={uploads}
        rec={rec}
        campaign={campaign}
        actions={{
          teleop: async () => { setPreviews(false); await studio.teleop(true); },
          record: async () => { setPreviews(false); await studio.record({ ...rec, sounds: false }); },
          stop: async () => { await studio.stop(); },
          checkMotors: async () => { const h = await studio.health(); setHealth(h); return h; },
        }}
      />

      <div className="grid3" style={{ marginTop: 16 }}>
        <Arm name="Follower (robot)" arm={status?.follower} />
        <Arm name="Leader (handle)" arm={status?.leader} />
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Now</h2>
          <p>
            <span className="badge">{busy ? `${p?.kind} running` : "idle"}</span>{" "}
            {recording && p?.episode != null && (
              <span className="badge">episode {p.episode + 1} / {rec.episodes} · {p.phase}</span>
            )}
          </p>
          <div className="row">
            <button className="stop" onClick={() => run(studio.stop)} disabled={!busy}>Stop</button>
            <button onClick={() => run(async () => setHealth(await studio.health()))} disabled={busy}>Check motors</button>
          </div>
          {health && (
            <div className="small">
              {Object.entries(health).map(([arm, motors]) => (
                <div key={arm}>
                  <strong>{arm}:</strong>{" "}
                  {typeof motors.error === "string" ? <span className="warn">{motors.error}</span> :
                    Object.entries(motors as Record<string, MotorHealth>).map(([m, h]) => (
                      <span key={m} className={h.ok ? "" : "warn"}>{m.replace("_", " ")} {h.ok ? `${h.tempC}°` : `⚠ ${h.problem}`} · </span>
                    ))}
                </div>
              ))}
            </div>
          )}
          {!busy && p?.exitCode != null && p.exitCode !== 0 && <p className="small warn">Last {p.kind} exited with code {p.exitCode}. See the log.</p>}
        </div>
      </div>

      <section>
        <h2>1. Cameras</h2>
        <p className="small">
          Previews only work while nothing is running. During teleop/recording, watch the cameras live in the <strong>Rerun</strong> window.
        </p>
        <div className="row">
          <button onClick={() => run(async () => { setCams(await studio.cameras()); setPreviews(true); })} disabled={busy}>
            {cams ? "Rescan cameras" : "Find cameras"}
          </button>
          {previews && <button onClick={() => run(async () => { setPreviews(false); await studio.releaseCameras(); })}>Close previews</button>}
          <label className="small">Side <select value={side} onChange={(e) => setSide(+e.target.value)}>{[0, 1, 2, 3, 4].map((i) => <option key={i}>{i}</option>)}</select></label>
          <label className="small">Wrist <select value={wrist} onChange={(e) => setWrist(+e.target.value)}>{[0, 1, 2, 3, 4].map((i) => <option key={i}>{i}</option>)}</select></label>
          <button className="primary" onClick={() => run(() => studio.setCameras(side, wrist))}>Save</button>
          <span className="small">saved: side {status?.cameras.side}, wrist {status?.cameras.wrist}</span>
        </div>
        {cams && cams.length === 0 && <p className="warn small">No cameras opened. Give Terminal camera access in System Settings → Privacy & Security → Camera, then restart Terminal and the worker.</p>}
        {previews && !busy && cams && (
          <div className="grid3" style={{ marginTop: 12 }}>
            {cams.map((c) => (
              <figure key={c.index} className="card" style={{ margin: 0 }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={studio.cameraUrl(c.index)} alt={`camera ${c.index}`} style={{ width: "100%", borderRadius: 12 }} />
                <figcaption className="small">
                  index {c.index} · {c.width}×{c.height}
                  {c.index === side && " · side"}
                  {c.index === wrist && " · wrist"}
                </figcaption>
              </figure>
            ))}
          </div>
        )}
      </section>

      <VisionPanel busy={busy} cameras={status?.cameras ?? { side: 0, wrist: 1 }} onError={setErr} />

      <section>
        <h2>2. Teleoperate</h2>
        <p className="small">Move the leader by hand; the follower copies it. Opens a Rerun window with both camera feeds and joint plots.</p>
        <div className="row">
          <button className="primary" disabled={busy || !armsReady} onClick={() => run(async () => { setPreviews(false); await studio.teleop(true); })}>
            Start teleop + Rerun
          </button>
          <button disabled={busy || !armsReady} onClick={() => run(async () => { setPreviews(false); await studio.teleop(false); })}>
            Teleop without Rerun
          </button>
          {!armsReady && <span className="small warn">Both arms must be connected and calibrated.</span>}
        </div>
      </section>

      <CampaignPanel status={campaign} hfUser={status?.hfUser ?? ""} onError={setErr} />

      <section>
        <h2>3. Record episodes (manual)</h2>
        <p className="small">
          Each episode: do the whole task with the leader, then reset the scene during the reset time. Aim for {MIN_EPISODES}+ episodes, varying object position a little.
          Recording into an existing dataset name adds to it.
        </p>
        <div className="grid2">
          <label className="small">Dataset (user/name)<input value={rec.repo} onChange={(e) => setRec({ ...rec, repo: e.target.value })} /></label>
          <label className="small">Task instruction<input value={rec.task} onChange={(e) => setRec({ ...rec, task: e.target.value })} /></label>
          <label className="small">Episodes this run<input type="number" min={1} value={rec.episodes} onChange={(e) => setRec({ ...rec, episodes: +e.target.value })} /></label>
          <label className="small">Seconds per episode<input type="number" min={5} value={rec.episodeSeconds} onChange={(e) => setRec({ ...rec, episodeSeconds: +e.target.value })} /></label>
          <label className="small">Reset seconds<input type="number" min={0} value={rec.resetSeconds} onChange={(e) => setRec({ ...rec, resetSeconds: +e.target.value })} /></label>
          <label className="small" style={{ alignSelf: "end" }}><input type="checkbox" checked={rec.rerun} onChange={(e) => setRec({ ...rec, rerun: e.target.checked })} /> Show in Rerun</label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" disabled={busy || !armsReady || !rec.repo} onClick={() => run(async () => { setPreviews(false); await studio.record({ ...rec, sounds: false }); })}>
            Start recording
          </button>
          {recording && (
            <div style={{ flex: 1, minWidth: 200 }}>
              <div className="progress"><div style={{ width: `${(((p?.episode ?? 0) + (p?.phase === "reset" ? 1 : 0.5)) / rec.episodes) * 100}%` }} /></div>
              <span className="small">{p?.phase === "reset" ? "Reset the scene now" : p?.phase === "recording" ? "Recording: do the task" : p?.phase}</span>
            </div>
          )}
        </div>
      </section>

      <section>
        <h2>Log</h2>
        <pre ref={logBox} className="log" style={{ maxHeight: 280 }}>{logs.join("\n") || "No output yet."}</pre>
      </section>

      <section>
        <h2>4. Datasets</h2>
        <table className="table">
          <thead><tr><th>Dataset</th><th>Episodes</th><th>Frames</th><th>Size</th><th>Perceptron</th></tr></thead>
          <tbody>
            {datasets.length === 0 && <tr><td colSpan={5} className="small">No local datasets yet.</td></tr>}
            {datasets.map((d) => {
              const u = uploads[d.repo];
              return (
                <tr key={d.repo}>
                  <td>{d.repo}{d.error && <span className="warn small"> ({d.error})</span>}</td>
                  <td>{d.episodes ?? "?"}{(d.episodes ?? 0) < MIN_EPISODES && <span className="small warn"> (aim {MIN_EPISODES}+)</span>}</td>
                  <td>{d.frames ?? "?"}</td>
                  <td>{d.sizeMB} MB</td>
                  <td>
                    {u ? (
                      <span className="small">
                        {u.phase} {u.total ? `${u.done}/${u.total}` : ""} {u.datasetId && <code>{u.datasetId}</code>} {u.error && <span className="warn">{u.error}</span>}
                      </span>
                    ) : null}{" "}
                    <button disabled={!status?.perceptron.configured || busy} onClick={() => run(() => studio.upload(d.repo).then(refreshData))}>Upload</button>
                    {u?.datasetId && <button onClick={() => setDatasetId(u.datasetId!)}>Use for training</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!status?.perceptron.configured && <p className="small warn">Add PERCEPTRON_API_KEY to robot_worker/.env and restart the worker to enable upload and training.</p>}
      </section>

      <section>
        <h2>5. Train & deploy (Perceptron)</h2>
        <div className="row">
          <label className="small">Dataset ID <input value={datasetId} onChange={(e) => setDatasetId(e.target.value)} placeholder="from upload" /></label>
          <button disabled={!datasetId} onClick={() => run(async () => setRemote(await studio.remoteDataset(datasetId)))}>Check dataset</button>
          <label className="small">Steps <input type="number" min={1} max={10000} value={steps} onChange={(e) => setSteps(Math.min(10000, Math.max(1, +e.target.value)))} style={{ width: 100 }} /></label>
          <button className="primary" disabled={!datasetId} onClick={() => run(async () => { await studio.train(datasetId, steps); setJobs(asList(await studio.jobs())); })}>Start training</button>
          <button disabled={!status?.perceptron.configured} onClick={() => run(async () => { setJobs(asList(await studio.jobs())); setDeployments(asList(await studio.deployments())); })}>Refresh jobs & deployments</button>
        </div>
        {remote && <pre className="log" style={{ maxHeight: 200 }}>{JSON.stringify(remote, null, 2)}</pre>}
        <div className="grid2" style={{ marginTop: 12 }}>
          <div>
            <h3>Training jobs</h3>
            {jobs.length === 0 ? <p className="small">None loaded.</p> : (
              <table className="table"><tbody>
                {jobs.map((j, i) => (
                  <tr key={String(j.id ?? i)}><td><code>{String(j.id ?? "")}</code></td><td>{String(j.status ?? "")}</td><td className="small">{String(j.checkpoint_id ?? "")}</td></tr>
                ))}
              </tbody></table>
            )}
          </div>
          <div>
            <h3>Deployments</h3>
            {deployments.length === 0 ? <p className="small">None loaded.</p> : (
              <table className="table"><tbody>
                {deployments.map((d, i) => (
                  <tr key={String(d.id ?? i)}><td><code>{String(d.id ?? "")}</code></td><td>{String(d.status ?? "")}</td></tr>
                ))}
              </tbody></table>
            )}
            <p className="small">Put a <em>ready</em> deployment ID in PERCEPTRON_DEPLOYMENT_ID and run the worker with ROBOT_MODE=perceptron.</p>
          </div>
        </div>
      </section>
    </main>
  );
}

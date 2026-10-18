"use client";

/* Live color/object detection with teach-and-remember. Uses the worker's /studio/vision API.
 * Only runs while teleop/recording is idle (LeRobot owns the cameras otherwise). */

import { useEffect, useRef, useState } from "react";
import { studio, type Detection, type Remembered } from "@/lib/studio";

type Box = { x: number; y: number; w: number; h: number };

const SUGGESTED = ["blue keychain", "pink pen", "white keycap"];

function ago(s: number) {
  if (s < 5) return "just now";
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

export default function VisionPanel({ busy, cameras, onError }: { busy: boolean; cameras: { side: number; wrist: number }; onError: (e: string | null) => void }) {
  const [camera, setCamera] = useState(cameras.side);
  const [live, setLive] = useState(false);
  const [src, setSrc] = useState("");
  const [dets, setDets] = useState<Detection[]>([]);
  const [lib, setLib] = useState<{ name: string; examples: number; color: string | null }[]>([]);
  const [mem, setMem] = useState<Remembered[]>([]);
  const [name, setName] = useState(SUGGESTED[0]);
  const [box, setBox] = useState<Box | null>(null);
  const [libVersion, setLibVersion] = useState(0);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const imgWrap = useRef<HTMLDivElement>(null);

  useEffect(() => setCamera(cameras.side), [cameras.side]);

  // Stop the live view if LeRobot takes the cameras.
  useEffect(() => {
    if (busy && live) {
      setLive(false);
      setSrc("");
    }
  }, [busy, live]);

  const refreshLib = () => studio.library().then(setLib, () => {});
  useEffect(() => {
    refreshLib();
  }, [libVersion]);

  useEffect(() => {
    const t = setInterval(async () => {
      studio.memory().then(setMem, () => {});
      if (live) studio.detections(camera).then((d) => setDets(d.detections), () => {});
    }, 1000);
    return () => clearInterval(t);
  }, [live, camera]);

  const start = () => {
    onError(null);
    setBox(null);
    setSrc(studio.visionStreamUrl(camera));
    setLive(true);
  };
  const stop = async () => {
    setLive(false);
    setSrc("");
    setDets([]);
    await studio.releaseCameras().catch(() => {});
  };

  // Drag a box over the live image to mark the object to teach.
  const pos = (e: React.MouseEvent) => {
    const r = imgWrap.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  const onDown = (e: React.MouseEvent) => {
    drag.current = pos(e);
    setBox(null);
  };
  const onMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    const p = pos(e), s = drag.current;
    setBox({ x: Math.min(s.x, p.x), y: Math.min(s.y, p.y), w: Math.abs(p.x - s.x), h: Math.abs(p.y - s.y) });
  };
  const onUp = () => {
    drag.current = null;
    setBox((b) => (b && b.w > 0.02 && b.h > 0.02 ? b : null));
  };

  const teach = async () => {
    onError(null);
    try {
      const r = await studio.teach(camera, name, box ? [box.x, box.y, box.w, box.h] : undefined);
      setBox(null);
      setLibVersion((v) => v + 1);
      onError(null);
      alertSay(`Learned ${r.name}${r.color ? `, a ${r.color} object` : ""}. ${r.examples} example${r.examples === 1 ? "" : "s"}.`);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  const named = dets.filter((d) => d.name);
  const unnamed = dets.filter((d) => !d.name);

  return (
    <section>
      <h2>Vision: colors &amp; objects</h2>
      <p className="small">
        Finds colored objects and recognizes ones you teach it, and remembers where each was last seen. The cameras are shared with the arm, so stop teleop or recording to use this.
      </p>
      <div className="row">
        <label className="small">Camera
          <select value={camera} onChange={(e) => setCamera(+e.target.value)} disabled={live}>
            <option value={cameras.side}>side ({cameras.side})</option>
            <option value={cameras.wrist}>wrist ({cameras.wrist})</option>
          </select>
        </label>
        {!live ? (
          <button className="primary" onClick={start} disabled={busy}>Start live detection</button>
        ) : (
          <button onClick={stop}>Stop live detection</button>
        )}
        {busy && <span className="small warn">Stop teleop/recording first.</span>}
      </div>

      {live && (
        <div className="grid2" style={{ marginTop: 12, alignItems: "start" }}>
          <div>
            <div
              ref={imgWrap}
              className="vision-view"
              onMouseDown={onDown}
              onMouseMove={onMove}
              onMouseUp={onUp}
              onMouseLeave={onUp}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={src} alt="live detection" draggable={false} onError={() => onError("Detection stream failed. Is the camera free?")} />
              {box && (
                <div className="vision-box" style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * 100}%`, height: `${box.h * 100}%` }} />
              )}
            </div>
            <p className="small">Drag a box around one object, name it, then press Teach. No box: it teaches the largest colored object.</p>
            <div className="row">
              <input list="teach-names" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
              <datalist id="teach-names">{SUGGESTED.map((s) => <option key={s} value={s} />)}</datalist>
              <button className="primary" onClick={teach} disabled={!name.trim()}>Teach {box ? "boxed object" : "largest object"}</button>
            </div>
            <p className="small">Tip: teach each object 3–5 times in different spots and angles. Every press adds an example.</p>
          </div>
          <div>
            <h3>Seeing now</h3>
            {dets.length === 0 && <p className="small">Nothing detected yet.</p>}
            <ul className="det-list">
              {named.map((d, i) => (
                <li key={`n${i}`}><span className={`swatch ${d.color}`} /> <strong>{d.name}</strong> · {d.where} · {Math.round(d.score * 100)}%</li>
              ))}
              {unnamed.slice(0, 8).map((d, i) => (
                <li key={`u${i}`} className="small"><span className={`swatch ${d.color}`} /> {d.color} object · {d.where}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="grid2" style={{ marginTop: 16, alignItems: "start" }}>
        <div>
          <h3>Taught objects</h3>
          {lib.length === 0 && <p className="small">None yet. Start live detection and teach: {SUGGESTED.join(", ")}.</p>}
          <div className="lib-grid">
            {lib.map((o) => (
              <figure key={o.name} className="card lib-item">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`${studio.thumbUrl(o.name)}?v=${libVersion}`} alt={o.name} />
                <figcaption>
                  <strong>{o.name}</strong>
                  <span className="small">{o.color ?? "mixed"} · {o.examples} ex.</span>
                  <button className="chip" onClick={async () => { await studio.forget(o.name); setLibVersion((v) => v + 1); }}>Forget</button>
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
        <div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3>Memory</h3>
            {mem.length > 0 && <button className="chip" onClick={() => studio.clearMemory().then(() => setMem([]))}>Clear</button>}
          </div>
          {mem.length === 0 ? <p className="small">Nothing remembered yet.</p> : (
            <table className="table">
              <thead><tr><th>Object</th><th>Last seen</th><th>Where</th><th>Seen</th></tr></thead>
              <tbody>
                {mem.map((m) => (
                  <tr key={m.name}>
                    <td><span className={`swatch ${m.color}`} /> {m.name}</td>
                    <td>{ago(m.secondsAgo)}</td>
                    <td>{m.where} ({m.camera === cameras.side ? "side" : m.camera === cameras.wrist ? "wrist" : `cam ${m.camera}`})</td>
                    <td>{m.timesSeen}×</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  );
}

function alertSay(text: string) {
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

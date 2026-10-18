"use client";

import { useEffect, useState } from "react";
import { api, type Participant, type Session } from "@/lib/api";

type Health = Awaited<ReturnType<typeof api.health>>;

export default function Caregiver() {
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [session, setSession] = useState<Session | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function refreshParticipants() {
    const ps = await api.participants();
    setParticipants(ps);
    if (!ps.find((p) => p._id === selected)) setSelected(ps[0]?._id ?? "");
  }

  useEffect(() => {
    refreshParticipants().catch((e) => setMsg(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const t = setInterval(async () => {
      api.health().then(setHealth, () => setHealth(null));
      if (session) api.session(session._id).then(setSession, () => {});
    }, 1500);
    return () => clearInterval(t);
  }, [session?._id]); // eslint-disable-line react-hooks/exhaustive-deps

  const participant = participants.find((p) => p._id === selected);
  const job = session?.activeJob;

  async function start() {
    if (!selected) return;
    setMsg(null);
    try {
      setSession(await api.startSession(selected));
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function remove() {
    if (!participant || !confirm(`Delete ${participant.alias} and all their session data?`)) return;
    const r = await api.deleteParticipant(participant._id);
    setMsg(`Deleted: ${Object.entries(r.deleted).map(([k, v]) => `${v} ${k}`).join(", ")}`);
    setSession(null);
    await refreshParticipants();
  }

  return (
    <main>
      <h1>Caregiver</h1>
      <p className="small">
        Supervised use only. Keep the workspace clear and the physical emergency stop within reach.
      </p>

      <div className="row small">
        <span className="badge">Robot: {health ? (health.robot.ready ? `ready (${health.robot.mode})` : "not ready") : "unknown"}</span>
        <span className="badge">{health?.persistent ? "MongoDB: saving" : "Not saving (demo memory only)"}</span>
      </div>

      <h2>1. Profile</h2>
      <div className="row">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {participants.map((p) => (
            <option key={p._id} value={p._id}>{p.alias}</option>
          ))}
        </select>
        <button onClick={remove} disabled={!participant}>Delete profile data</button>
      </div>
      {participant && (
        <p className="small">
          Interests: {participant.interestTags.join(", ") || "none"} · Remember preferences:{" "}
          {participant.consentFlags.rememberPreferences ? "yes" : "no"} · Saved favourite:{" "}
          {participant.preferences?.favoriteObjectId ?? "none"}
        </p>
      )}

      <h2>2. Approve session</h2>
      <div className="row">
        <button className="primary" onClick={start} disabled={!selected}>Approve &amp; start “Sort &amp; Share”</button>
        {session && (
          <a href={`/participant?session=${session._id}`} target="_blank" rel="noreferrer">Open participant screen ↗</a>
        )}
      </div>

      {session && (
        <>
          <h2>3. Supervise</h2>
          <div className="card">
            <p>State: <span className="badge">{session.state}</span>{session.helpRequested && <span className="badge warn"> help requested</span>}</p>
            <p className="small">Agent said: “{session.lastReply}”</p>
            {job && <p className="small">Robot job: {job.objectId} · {job.status}{job.errorCode ? ` (${job.errorCode})` : ""}</p>}

            {job?.status === "verifying" && (
              <div className="row">
                <span>Did the object land in the tray?</span>
                <button className="primary" onClick={() => api.verify(job._id, true)}>Yes, it’s in the tray</button>
                <button onClick={() => api.verify(job._id, false)}>No</button>
              </div>
            )}
            {session.state === "needs_staff" && (
              <div className="row">
                <span className="warn">Check the workspace, then:</span>
                <button onClick={async () => setSession(await api.resume(session._id))}>Resume activity</button>
              </div>
            )}

            <div className="row" style={{ marginTop: 16 }}>
              <button className="stop" onClick={async () => setSession((await api.stop(session._id)).session)} disabled={session.state === "stopped"}>
                Stop session &amp; robot
              </button>
            </div>
          </div>

          <h2>Session summary (non-clinical)</h2>
          <p className="small">
            Objects moved: {session.selections.length ? session.selections.join(", ") : "none yet"} · Help requested:{" "}
            {session.helpRequested ? "yes" : "no"}
            {session.preferenceSaved !== undefined && ` · Preference saved: ${session.preferenceSaved ? "yes" : "no (not persistent)"}`}
          </p>
        </>
      )}
      {msg && <p className="small warn">{msg}</p>}
    </main>
  );
}

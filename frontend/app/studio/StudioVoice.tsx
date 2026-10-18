"use client";

/* Voice assistant for Robot Studio.
 * - Narrates robot state (teleop, recording progress, countdowns, faults) with speech synthesis.
 * - Answers training questions and takes commands by voice (Web Speech API) or typed text.
 * - Anything that moves the arm needs a spoken/typed "confirm"; "stop" acts immediately. */

import { useCallback, useEffect, useRef, useState } from "react";
import { studio, type CampaignStatus, type Dataset, type MotorHealth, type StudioStatus, type UploadState } from "@/lib/studio";

const MIN_EPISODES = 50;

type Health = Record<string, Record<string, MotorHealth | string>>;

export type VoiceActions = {
  teleop: () => Promise<void>;
  record: () => Promise<void>;
  stop: () => Promise<void>;
  checkMotors: () => Promise<Health>;
};

type Props = {
  status: StudioStatus | null;
  logs: string[];
  datasets: Dataset[];
  uploads: Record<string, UploadState>;
  rec: { repo: string; task: string; episodes: number; episodeSeconds: number; resetSeconds: number };
  campaign: CampaignStatus | null;
  actions: VoiceActions;
  compact?: boolean; // Record page: just the mic, the speak toggle and the last line
};

type Msg = { who: "you" | "robot"; text: string };

// ---------------------------------------------------------------- speech helpers

// Only one browser tab speaks (several Studio tabs used to talk over each other).
const TAB_ID = typeof window !== "undefined" ? Math.random().toString(36).slice(2) : "server";
const OWNER_KEY = "remind-voice-owner";

function readOwner(): { id: string; t: number } | null {
  try {
    return JSON.parse(localStorage.getItem(OWNER_KEY) || "null");
  } catch {
    return null;
  }
}

export function claimVoice(force = false) {
  try {
    const o = readOwner();
    if (force || !o || o.id === TAB_ID || Date.now() - o.t > 3000) localStorage.setItem(OWNER_KEY, JSON.stringify({ id: TAB_ID, t: Date.now() }));
  } catch {}
}

function isVoiceOwner() {
  const o = readOwner();
  return !o || o.id === TAB_ID;
}

let lastSpoken = { text: "", t: 0 };

function speak(text: string, opts: { interrupt?: boolean } = {}) {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  if (!isVoiceOwner()) return;
  if (text === lastSpoken.text && Date.now() - lastSpoken.t < 10000) return; // no duplicate lines
  lastSpoken = { text, t: Date.now() };
  if (opts.interrupt) window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.0;
  window.speechSynthesis.speak(u);
}

type Recognition = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  onresult: ((e: { results: { 0: { transcript: string } }[] }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function makeRecognition(): Recognition | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) return null;
  const r = new Ctor();
  r.lang = "en-US";
  r.interimResults = false;
  r.maxAlternatives = 1;
  return r;
}

const has = (t: string, ...words: string[]) => words.some((w) => t.includes(w));

// ---------------------------------------------------------------- knowledge

const GUIDE = {
  train:
    "Training has five steps. One: tape down the scene. Two: record about fifty episodes per skill with the leader arm. Three: upload the dataset to Perceptron. Four: start training and wait for a ready deployment. Five: test at least ten trials per object and write down the success rate.",
  episodes: `Aim for at least ${MIN_EPISODES} good episodes per skill: fifty for tea and fifty for coffee. Record in batches of ten so you can rest and check quality.`,
  tips:
    "Move slowly and smoothly, the robot copies your speed. Start and end every episode in the same rest pose. Shift the box a few centimetres between episodes. If an episode goes wrong, stop and redo it.",
  objects:
    "Use light, rigid, familiar objects under about 150 grams: small tea and coffee boxes or tins, a sugar box, foam blocks or large Lego for practice, and a shallow tray. Avoid balls, flat cards, glass, liquids, and anything heavy.",
  scene:
    "Tape down the arm base, the side camera, the tray, and the two pickup spots. Keep the same lighting and table for training and the demo. Plug the cameras into the fast USB adapter so frames do not drop.",
  usb: "If the camera lags, the cameras and arms are sharing one slow USB hub. Plug the side camera directly into the Mac, or use the Perceptron adapter.",
  safety: "Keep hands out of the follower's reach while it moves. Say stop at any time. The power switch is the emergency stop.",
  help: "You can ask: how do I train, how many episodes, tips, what objects, what's next, status, what do you see, or where is the pink pen. Commands: start teleop, start recording, stop, check motors, and remember this as a name.",
};

// ---------------------------------------------------------------- component

export default function StudioVoice({ status, logs, datasets, uploads, rec, campaign, actions, compact }: Props) {
  const [narrate, setNarrate] = useState(true);
  const [listening, setListening] = useState(false);
  const [typed, setTyped] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [pending, setPending] = useState<{ label: string; run: () => Promise<void>; at: number } | null>(null);
  const recog = useRef<Recognition | null>(null);
  const narrateRef = useRef(narrate);
  narrateRef.current = narrate;

  useEffect(() => {
    claimVoice();
    const t = setInterval(() => claimVoice(), 1000);
    return () => clearInterval(t);
  }, []);

  const say = useCallback((text: string, opts: { interrupt?: boolean; log?: boolean } = {}) => {
    if (opts.log !== false) setMsgs((m) => [...m.slice(-30), { who: "robot", text }]);
    if (narrateRef.current) speak(text, opts);
  }, []);

  // ---------- narration of process state

  const prev = useRef<{ kind: string | null; running: boolean; episode: number | null; phase: string | null } | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  useEffect(() => {
    const p = status?.process;
    if (!p) return;
    const before = prev.current;
    prev.current = { kind: p.kind, running: p.running, episode: p.episode, phase: p.phase };
    if (!before) return; // don't narrate the state we found on page load

    const byCampaign = !!campaign?.running;
    const total = byCampaign && campaign?.current ? campaign.current.episodes : rec.episodes;
    const epSec = byCampaign && campaign ? campaign.config.episodeSeconds : rec.episodeSeconds;
    const resetSec = byCampaign && campaign ? campaign.config.resetSeconds : rec.resetSeconds;
    if (!before.running && p.running && !byCampaign) {
      say(p.kind === "teleop" ? "Teleop on. Hands clear." : "Recording. Get ready.");
    }
    if (p.kind === "record" && p.running) {
      if (p.phase === "recording" && (before.phase !== "recording" || before.episode !== p.episode)) {
        const n = (p.episode ?? 0) + 1;
        clearTimers();
        say(`Episode ${n} of ${total}. Go.`);
        if (epSec > 8) timers.current.push(setTimeout(() => say("Five seconds.", { log: false }), (epSec - 5) * 1000));
      } else if (p.phase === "reset" && before.phase !== "reset") {
        const left = total - ((p.episode ?? 0) + 1);
        clearTimers();
        say(left > 0 ? `Reset. ${left} to go.` : "Reset. Last one done.");
        if (resetSec > 5) timers.current.push(setTimeout(() => say("Get ready.", { log: false }), (resetSec - 3) * 1000));
      } else if (p.phase === "re-record" && before.phase !== "re-record") {
        say("Redo that one.");
      } else if (p.phase === "finishing" && before.phase !== "finishing") {
        clearTimers();
        say("Saving.");
      }
    }
    if (before.running && !p.running) {
      clearTimers();
      if (byCampaign) {
        // the campaign announces what happens next
      } else if (p.stoppedByUser || p.exitCode === 0 || p.exitCode === null) {
        say(p.kind === "record" ? "Saved." : "Teleop off.");
      } else {
        const reason = [...logs].reverse().find((l) => /Error|error:|Timeout|Missing motor/.test(l));
        say(`${p.kind === "record" ? "Recording" : "Teleop"} stopped with an error. ${explain(reason)}`, { interrupt: true });
      }
    }
  }, [status, rec.episodes, rec.episodeSeconds, rec.resetSeconds, logs, say, campaign]);

  useEffect(() => () => clearTimers(), []);

  // ---------- campaign prompts (spoken to the operator)
  const campaignSeq = useRef<number | null>(null);
  useEffect(() => {
    if (!campaign) return;
    if (campaignSeq.current === null) {
      campaignSeq.current = campaign.messageSeq; // don't replay the last message on page load
      return;
    }
    if (campaign.messageSeq > campaignSeq.current) {
      campaignSeq.current = campaign.messageSeq;
      if (campaign.message) say(campaign.message, { interrupt: campaign.state === "paused" || campaign.state === "error" });
    }
  }, [campaign, say]);

  // ---------- warnings from the log

  const seen = useRef(0);
  const lastWarn = useRef<Record<string, number>>({});
  useEffect(() => {
    const fresh = logs.slice(seen.current);
    seen.current = logs.length;
    if (!prev.current) return;
    for (const line of fresh) {
      const key = /frame is too old|read failed/.test(line) ? "camera" : /Overload/.test(line) ? "overload" : /Missing motor/.test(line) ? "motor" : null;
      if (!key) continue;
      const now = Date.now();
      if (now - (lastWarn.current[key] ?? 0) < 20000) continue;
      lastWarn.current[key] = now;
      say(explain(line), { interrupt: key !== "camera" });
    }
  }, [logs, say]);

  // ---------- question answering

  const dataset = datasets.find((d) => d.repo === rec.repo);

  const nextStep = useCallback((): string => {
    if (!status) return "The robot worker is offline. Start it from Terminal.";
    const { follower, leader, process: p } = status;
    if (!follower.connected || !leader.connected) return `Connect the ${!follower.connected ? "follower" : "leader"} arm's USB cable.`;
    if (!follower.calibration || !leader.calibration) return `Calibrate the ${!follower.calibration ? "follower" : "leader"} arm in Terminal with arm dot py calibrate.`;
    if (p.running && p.kind === "record") return `You're recording episode ${(p.episode ?? 0) + 1} of ${rec.episodes}. Keep going.`;
    const eps = dataset?.episodes ?? 0;
    if (eps < MIN_EPISODES) return `Your dataset ${rec.repo || "for this task"} has ${eps} episodes. Record ${MIN_EPISODES - eps} more. Say start recording when the scene is ready.`;
    if (!status.perceptron.configured) return "You have enough episodes. Add your Perceptron API key to the robot worker's env file and restart it, then upload.";
    const u = uploads[rec.repo];
    if (!u) return "Upload the dataset to Perceptron with the Upload button.";
    if (u.phase === "error") return `The upload failed: ${u.error}. Try uploading again.`;
    if (u.phase !== "finalized") return `The upload is ${u.phase}. ${u.done} of ${u.total} files done.`;
    return "The dataset is uploaded. Click check dataset, then start training. When a deployment is ready, test ten trials per object.";
  }, [status, dataset, uploads, rec.repo, rec.episodes]);

  const describe = useCallback((): string => {
    if (!status) return "I can't reach the robot worker.";
    const p = status.process;
    const arms = `${status.follower.connected ? "Follower connected" : "Follower disconnected"}, ${status.leader.connected ? "leader connected" : "leader disconnected"}.`;
    const what = p.running
      ? p.kind === "record"
        ? `Recording episode ${(p.episode ?? 0) + 1} of ${rec.episodes}, ${p.phase === "reset" ? "resetting the scene" : "recording"}.`
        : "Teleop is running."
      : "The robot is idle.";
    const data = dataset ? ` The dataset has ${dataset.episodes ?? 0} episodes.` : "";
    return `${what} ${arms}${data}`;
  }, [status, dataset, rec.episodes]);

  const handle = useCallback(
    async (raw: string) => {
      const t = raw.toLowerCase().trim();
      if (!t) return;
      claimVoice(true); // the tab you're using becomes the one that speaks
      setMsgs((m) => [...m.slice(-30), { who: "you", text: raw }]);

      // Stop always wins and never needs confirmation.
      if (has(t, "stop", "halt", "freeze", "emergency")) {
        setPending(null);
        await actions.stop();
        say("Stopping now.", { interrupt: true });
        return;
      }
      if (pending && has(t, "confirm", "yes", "go ahead", "do it")) {
        const p = pending;
        setPending(null);
        if (Date.now() - p.at > 20000) return say("That request expired. Ask again.");
        say(`${p.label}. Keep hands clear.`);
        try {
          await p.run();
        } catch (e) {
          say(`I couldn't do that. ${e instanceof Error ? e.message : ""}`);
        }
        return;
      }
      if (pending && has(t, "cancel", "no", "never mind")) {
        setPending(null);
        return say("Cancelled.");
      }

      // Campaign: "ready" starts the waiting batch; pause / resume / skip.
      const waiting = campaign && (campaign.state === "setup" || campaign.state === "waiting_ready");
      if (waiting && has(t, "ready", "i'm ready", "im ready", "all set", "set up", "go ahead", "skip")) {
        await studio.campaignAction(has(t, "skip") ? "skip" : "ready");
        return say("Starting the batch. Keep hands clear of the follower.");
      }
      if (campaign && has(t, "pause campaign", "pause the campaign", "pause")) {
        await studio.campaignAction("pause");
        return say("The campaign will pause after this batch.");
      }
      if (campaign && has(t, "start campaign", "start the campaign", "resume campaign", "resume", "continue campaign")) {
        await studio.campaignAction("start");
        return say("Campaign started. I'll tell you what to set up.");
      }
      if (campaign && has(t, "progress", "how far", "how many left")) {
        const left = campaign.targets.map((x) => `${x.object} ${x.done} of ${x.target}`).join(", ");
        return say(`Campaign progress: ${left}.`);
      }

      // Questions ("how many episodes should I record?") never trigger motion commands.
      const question = /^(how|what|why|when|where|which|should|is|does|do i|tell me)\b/.test(t);

      if (!question && has(t, "start teleop", "teleop", "tele op", "teleoperate")) {
        if (status?.process.running) return say(`${status.process.kind === "record" ? "Recording" : "Teleop"} is already running. Say stop first.`);
        setPending({ label: "Starting teleop", run: actions.teleop, at: Date.now() });
        return say("Start teleop? The follower will move to match the leader. Say confirm.");
      }
      if (!question && has(t, "start record", "record", "recording")) {
        if (status?.process.running) return say(`${status.process.kind === "record" ? "Recording" : "Teleop"} is already running. Say stop first.`);
        setPending({ label: `Recording ${rec.episodes} episodes`, run: actions.record, at: Date.now() });
        return say(`Record ${rec.episodes} episodes of ${rec.episodeSeconds} seconds for: ${rec.task}? Say confirm.`);
      }
      if (!question && has(t, "check motor", "motors", "motor health", "check the motor")) {
        try {
          const h = await actions.checkMotors();
          const bad = Object.entries(h).flatMap(([arm, ms]) =>
            typeof ms.error === "string" ? [`${arm}: ${ms.error}`] : Object.entries(ms as Record<string, MotorHealth>).filter(([, x]) => !x.ok).map(([m, x]) => `${arm} ${m.replace("_", " ")} ${x.problem}`),
          );
          return say(bad.length ? `Problems found: ${bad.join(". ")}.` : "All twelve motors are healthy.");
        } catch (e) {
          return say(`I couldn't check the motors. ${e instanceof Error ? e.message : ""}`);
        }
      }

      // ---- vision: what do you see / where is X / remember this as X
      const remember = t.match(/^(?:remember|learn|teach)(?: this| that| it)?(?: as| is)? (?:the |a |my )?(.+)$/) ?? t.match(/^this is (?:the |a |my )?(.+)$/);
      if (remember) {
        const cam = status?.cameras.side ?? 0;
        try {
          const r = await studio.teach(cam, remember[1]);
          return say(`Got it. I'll remember the ${r.name}${r.color ? `, the ${r.color} one` : ""}. That's ${r.examples} example${r.examples === 1 ? "" : "s"}.`);
        } catch (e) {
          return say(`I couldn't learn that. ${e instanceof Error ? e.message : ""} Start live detection on the side camera first.`);
        }
      }
      const where = t.match(/where(?: is|'s| are)? (?:the |my |a )?(.+?)\??$/);
      if (where) {
        const mem = await studio.memory().catch(() => []);
        const q = where[1].replace(/\?$/, "");
        const hit = mem.find((m) => m.name.toLowerCase() === q) ?? mem.find((m) => m.name.toLowerCase().includes(q) || q.includes(m.name.toLowerCase()));
        if (!hit) return say(`I haven't seen the ${q} yet. Teach it in the vision panel, or show it to the camera.`);
        const when = hit.secondsAgo < 5 ? "right now" : hit.secondsAgo < 60 ? `${Math.round(hit.secondsAgo)} seconds ago` : `${Math.round(hit.secondsAgo / 60)} minutes ago`;
        return say(`I saw the ${hit.name} ${when}, at the ${hit.where} of the ${hit.camera === status?.cameras.wrist ? "wrist" : "side"} camera.`);
      }
      if (has(t, "what do you see", "what can you see", "what's on the table", "what is on the table", "what do you remember")) {
        const cam = status?.cameras.side ?? 0;
        const live = await studio.detections(cam).catch(() => null);
        if (live && live.detections.length) {
          const named = live.detections.filter((d) => d.name).map((d) => `the ${d.name} at the ${d.where}`);
          const colors = live.detections.filter((d) => !d.name).map((d) => d.color);
          const extra = colors.length ? ` Also ${colors.length} other ${[...new Set(colors)].join(" and ")} object${colors.length > 1 ? "s" : ""}.` : "";
          return say((named.length ? `I see ${named.join(", ")}.` : "I don't recognize anything I've been taught.") + extra);
        }
        const mem = await studio.memory().catch(() => []);
        if (!mem.length) return say("The camera isn't live and I don't remember anything yet. Start live detection in the vision panel.");
        return say(`The camera isn't live. From memory: ${mem.slice(0, 4).map((m) => `the ${m.name} was at the ${m.where}`).join(", ")}.`);
      }

      if (has(t, "next", "what now", "what should i do")) return say(nextStep());
      if (has(t, "status", "what's the robot", "what is the robot", "situation", "doing", "how's it going")) return say(describe());
      if (has(t, "how many episode", "how many demo", "how much data")) return say(GUIDE.episodes + (dataset ? ` You have ${dataset.episodes ?? 0} so far.` : ""));
      if (has(t, "object", "what can i use", "what to pick", "props")) return say(GUIDE.objects);
      if (has(t, "tip", "good episode", "how should i move", "demonstrat")) return say(GUIDE.tips);
      if (has(t, "scene", "setup", "set up", "tape")) return say(GUIDE.scene);
      if (has(t, "camera", "lag", "usb")) return say(GUIDE.usb);
      if (has(t, "safe", "danger")) return say(GUIDE.safety);
      if (has(t, "train", "how do i", "how to")) return say(GUIDE.train);
      return say(`Sorry, I didn't catch that. ${GUIDE.help}`);
    },
    [actions, pending, status, rec, dataset, nextStep, describe, say, campaign],
  );

  // ---------- microphone

  const listen = () => {
    if (listening) {
      recog.current?.stop();
      return;
    }
    const r = makeRecognition();
    if (!r) {
      say("Voice input isn't supported in this browser. Use Chrome, or type your question.");
      return;
    }
    recog.current = r;
    window.speechSynthesis?.cancel(); // don't transcribe ourselves
    r.onresult = (e) => handle(e.results[0][0].transcript);
    r.onerror = (e) => {
      if (e.error === "not-allowed") say("Microphone access was blocked. Allow it in the browser's site settings.");
    };
    r.onend = () => setListening(false);
    setListening(true);
    r.start();
  };

  if (compact) {
    const last = [...msgs].reverse().find((m) => m.who === "robot");
    return (
      <div className="row voice-compact">
        <button className={listening ? "stop" : ""} onClick={listen} aria-pressed={listening}>{listening ? "Listening…" : "🎙 Talk"}</button>
        <label className="small" style={{ flexDirection: "row", alignItems: "center" }}>
          <input type="checkbox" checked={narrate} onChange={(e) => { setNarrate(e.target.checked); if (e.target.checked) claimVoice(true); else window.speechSynthesis?.cancel(); }} /> Voice
        </label>
        {last && <span className="small">“{last.text}”</span>}
      </div>
    );
  }

  return (
    <div className="card voice">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Voice assistant</h2>
        <label className="small" style={{ flexDirection: "row", alignItems: "center" }}>
          <input type="checkbox" checked={narrate} onChange={(e) => { setNarrate(e.target.checked); if (!e.target.checked) window.speechSynthesis?.cancel(); }} /> Speak updates
        </label>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className={listening ? "stop" : "primary"} onClick={listen} aria-pressed={listening}>
          {listening ? "Listening… (tap to stop)" : "🎙 Talk"}
        </button>
        <form
          className="row"
          style={{ flex: 1, minWidth: 240 }}
          onSubmit={(e) => {
            e.preventDefault();
            handle(typed);
            setTyped("");
          }}
        >
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Ask: how do I train? what's next? status" style={{ flex: 1 }} />
          <button type="submit">Ask</button>
        </form>
      </div>
      <div className="row small" style={{ marginTop: 8 }}>
        {["What's next?", "Status", "How do I train?", "How many episodes?", "Tips", "What objects?", "Check motors", "What do you see?", "Where is the pink pen?", "Campaign progress"].map((q) => (
          <button key={q} className="chip" onClick={() => handle(q)}>{q}</button>
        ))}
      </div>
      {pending && (
        <div className="row" style={{ marginTop: 8 }}>
          <span className="warn">{pending.label}? Say “confirm”, or:</span>
          <button className="primary" onClick={() => handle("confirm")}>Confirm</button>
          <button onClick={() => handle("cancel")}>Cancel</button>
        </div>
      )}
      <div className="voice-log" aria-live="polite">
        {msgs.length === 0 && <p className="small">Updates and answers appear here. Say “stop” at any time.</p>}
        {msgs.slice(-8).map((m, i) => (
          <p key={i} className={m.who === "you" ? "you" : ""}>
            <strong>{m.who === "you" ? "You" : "Robot"}:</strong> {m.text}
          </p>
        ))}
      </div>
    </div>
  );
}

function explain(line?: string): string {
  if (!line) return "Check the log for details.";
  if (/frame is too old|read failed/.test(line)) return "The camera is lagging or dropped out. Check the USB cables, or plug the side camera straight into the Mac.";
  if (/Overload/.test(line)) return "A motor overloaded. Stop, make sure nothing is pinching the gripper, and run check motors.";
  if (/Missing motor/.test(line)) return "A motor is not responding. Unplug that arm's power for ten seconds, then check motors.";
  if (/Failed to open|Could not connect|not connected/i.test(line)) return "An arm or camera could not be opened. Check the cables.";
  return "Check the log for details.";
}

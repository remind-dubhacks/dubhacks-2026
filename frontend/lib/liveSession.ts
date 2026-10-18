// Shares the live game session between the resident tab and the caregiver dashboard (same browser).
// Placeholder for the real backend session events (see docs/CONTRACTS.md).
export type Phase = "idle" | "intro" | "shuffling" | "awaiting" | "checking" | "feedback" | "reveal" | "complete" | "stopped";

export type LiveSession = {
  resident: string;
  phase: Phase;
  attempt: number;
  maxTrials: number;
  target: string[];
  shuffledOrder: string[];
  lastFeedback: string;
  result: "none" | "correct" | "gave_up" | "stopped";
  helpRequested: boolean;
  startedAt: number;
  updatedAt: number;
};

const KEY = "remind.live";

export function saveLive(s: LiveSession) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...s, updatedAt: Date.now() }));
  } catch {}
}

export function loadLive(): LiveSession | null {
  try {
    const v = localStorage.getItem(KEY);
    return v ? (JSON.parse(v) as LiveSession) : null;
  } catch {
    return null;
  }
}

export function clearLive() {
  try {
    localStorage.removeItem(KEY);
  } catch {}
}

import { API } from "./api";

// What the patient screen shows (design.md: gradient, a photo, or a few words; nothing else).
export type Screen =
  | { kind: "rest" }
  | { kind: "message"; text: string }
  | { kind: "photo"; photo: string }
  | { kind: "photo_caption"; photo: string; caption: string };

export type Observation = { game: string | null; item: string | null; engagement: "engaged" | "some" | "withdrawn"; note: string };

export type VoiceState = {
  game: string | null;
  phase: "idle" | "awaiting" | "playing" | "complete" | "reveal" | "stopped";
  attempt: number;
  maxTrials: number;
  target: string[];
  shuffledOrder: string[];
  shuffleId: number;
  feedback: string;
  result: string;
  helpRequested: boolean;
  alerts: string[];
  itemIndex: number;
  screen: Screen;
  sound: { src: string; id: number } | null;
  observations: Observation[];
};

export type ToolCall = { name: string; args: Record<string, unknown>; result: Record<string, unknown> };

export async function voiceTurn(sessionId: string, text: string, tableOrder: string[]) {
  const r = await fetch(`${API}/api/voice/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, text, tableOrder }),
  });
  if (!r.ok) throw new Error(`${r.status}`);
  return (await r.json()) as { reply: string; toolCalls: ToolCall[]; state: VoiceState };
}

export const voiceReset = (sessionId: string) =>
  fetch(`${API}/api/voice/reset`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId }) });

export async function voiceStatus(): Promise<{ live: boolean; provider: "gemini" | "rules"; tts: boolean }> {
  try {
    return await (await fetch(`${API}/api/voice/status`)).json();
  } catch {
    return { live: false, provider: "rules", tts: false };
  }
}

// ElevenLabs speech from the backend; throws if unavailable so callers can fall back to the browser voice.
export async function fetchTts(text: string): Promise<Blob> {
  const r = await fetch(`${API}/api/voice/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(`tts ${r.status}`);
  return r.blob();
}

export type ToolInfo = { name: string; description: string; params: string[]; status: "real" | "mock" | "placeholder"; example: string; does: string };

export async function fetchTools(): Promise<ToolInfo[]> {
  try {
    return await (await fetch(`${API}/api/voice/tools`)).json();
  } catch {
    return [];
  }
}

export type CompanionSession = {
  _id: string;
  participantId?: string | null;
  patientName: string;
  startedAt: string;
  endedAt: string;
  gamesPlayed: string[];
  observations: Observation[];
  alerts: string[];
  acknowledgedAt?: string | null;
};

export async function fetchSessions(): Promise<CompanionSession[]> {
  const r = await fetch(`${API}/api/voice/sessions`);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

export async function sendTestText(phone: string): Promise<string | null> {
  try {
    const r = await fetch(`${API}/api/voice/test-text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone }) });
    if (r.ok) return null;
    return (await r.json().catch(() => null))?.detail ?? `Failed (${r.status})`;
  } catch {
    return "Could not reach the backend";
  }
}

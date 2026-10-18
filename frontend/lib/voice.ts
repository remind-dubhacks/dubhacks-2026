import { API } from "./api";

export type VoiceState = {
  game: string | null;
  phase: "idle" | "awaiting" | "complete" | "reveal" | "stopped";
  attempt: number;
  maxTrials: number;
  target: string[];
  shuffledOrder: string[];
  shuffleId: number;
  feedback: string;
  result: string;
  helpRequested: boolean;
  alerts: string[];
  exercise?: {
    phase?: string;
    row?: string[];
    watching?: boolean;
    robot?: { status?: "moving" | "done" | "failed"; purpose?: "shuffle" | "show"; error?: string };
    [k: string]: unknown;
  };
};

export type WatchEvent = { kind: string; obj?: string; spot?: number; right?: boolean; level?: number };

// Live table watching while the person restores the row: poll ~once a second, speak `say` when set.
export async function voiceWatch(sessionId: string) {
  const r = await fetch(`${API}/api/voice/watch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId }),
  });
  if (!r.ok) throw new Error(`${r.status}`);
  return (await r.json()) as { say: string | null; events: WatchEvent[]; camera?: boolean; state: VoiceState };
}

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

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

export async function voiceStatus(): Promise<{ realtime: boolean; provider: "gemini" | "grok" | "rules"; tts: boolean }> {
  try {
    return await (await fetch(`${API}/api/voice/status`)).json();
  } catch {
    return { realtime: false, provider: "rules", tts: false };
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

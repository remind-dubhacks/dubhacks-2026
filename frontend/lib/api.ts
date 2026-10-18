import type { CompanionSession } from "./voice";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Choice = { objectId: string; label: string };

export type Session = {
  _id: string;
  participantId: string;
  activityId: string;
  state: string;
  helpRequested: boolean;
  selections: string[];
  activeJobId: string | null;
  lastReply: string | null;
  preferenceSaved?: boolean;
  choices: Choice[];
  persistent: boolean;
  activeJob?: RobotJob | null;
};

export type AgentTurn = {
  reply: string;
  intent: string;
  objectId: string | null;
  requestedAction: string | null;
  needsConfirmation: boolean;
};

export type RobotJob = {
  _id: string;
  objectId: string;
  status: "queued" | "running" | "verifying" | "succeeded" | "failed" | "stopped";
  errorCode: string | null;
  sessionState?: string;
  reply?: string | null;
};

// The care sheet (backend CareProfile): all of it reaches the companion's prompt.
export type CareProfile = {
  preferredName?: string;
  pronunciation?: string;
  language?: string;
  speech?: string[];
  pace?: "normal" | "slow";
  hearing?: "good" | "hard_of_hearing" | "hearing_aid";
  vision?: string;
  bestTimeOfDay?: string;
  attentionMinutes?: number | null;
  stage?: string;
  orientation?: string;
  calmingStrategies?: string[];
  avoidTopics?: string[];
  distressSigns?: string[];
  lifeStory?: string[];
  interests?: string[];
  conversationStarters?: string[];
};

export type Participant = {
  _id: string;
  alias: string;
  room?: string;
  interestTags: string[];
  consentFlags: { sessionConsent: boolean; rememberPreferences: boolean };
  preferences?: { favoriteObjectId?: string };
  careProfile?: CareProfile;
  backboardAssistantId?: string | null;
};

// A fact in the resident's Backboard memory. kind: care_profile (seeded), session (learnt in a call), nurse.
export type Memory = { id: string; content: string; kind?: string; createdAt?: string | null };
export type MemoriesView = { enabled: boolean; remember: boolean; assistantId: string | null; memories: Memory[] };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

const post = <T,>(path: string, body: unknown) => req<T>(path, { method: "POST", body: JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) => req<T>(path, { method: "PUT", body: JSON.stringify(body) });
const patch = <T,>(path: string, body: unknown) => req<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const del = <T,>(path: string) => req<T>(path, { method: "DELETE" });

export const api = {
  health: () => req<{ persistent: boolean; robot: { ready: boolean; mode?: string; busy?: boolean; error?: string } }>("/api/health"),
  participants: () => req<Participant[]>("/api/participants"),
  participant: (id: string) => req<Participant>(`/api/participants/${id}`),
  deleteParticipant: (id: string) => req<{ deleted: Record<string, number> }>(`/api/participants/${id}`, { method: "DELETE" }),
  saveCareProfile: (id: string, profile: CareProfile) => put<Participant>(`/api/participants/${id}/care-profile`, profile),
  setConsent: (id: string, rememberPreferences: boolean) => put<Participant>(`/api/participants/${id}/consent`, { rememberPreferences }),
  memories: (id: string) => req<MemoriesView>(`/api/participants/${id}/memories`),
  addMemory: (id: string, content: string) => post<{ ok: boolean }>(`/api/participants/${id}/memories`, { content }),
  editMemory: (id: string, mid: string, content: string) => patch<{ ok: boolean }>(`/api/participants/${id}/memories/${mid}`, { content }),
  deleteMemory: (id: string, mid: string) => del<{ ok: boolean }>(`/api/participants/${id}/memories/${mid}`),
  forgetMemories: (id: string) => del<Participant>(`/api/participants/${id}/memories`),
  participantSessions: (id: string) => req<CompanionSession[]>(`/api/participants/${id}/sessions`),
  acknowledge: (sessionId: string) => post<CompanionSession>(`/api/voice/sessions/${sessionId}/acknowledge`, {}),
  startSession: (participantId: string, activityId = "sort_and_share") =>
    post<Session>("/api/sessions", { participantId, activityId, caregiverApproved: true }),
  session: (id: string) => req<Session>(`/api/sessions/${id}`),
  resume: (id: string) => post<Session>(`/api/sessions/${id}/resume`, {}),
  turn: (sessionId: string, text: string) => post<{ turn: AgentTurn; session: Session }>("/api/agent/turn", { sessionId, text }),
  createJob: (sessionId: string, objectId: string, actionId = "move_known_object") =>
    post<RobotJob>("/api/robot/jobs", { sessionId, objectId, actionId }),
  job: (id: string) => req<RobotJob>(`/api/robot/jobs/${id}`),
  verify: (id: string, success: boolean) => post<RobotJob>(`/api/robot/jobs/${id}/verify`, { success }),
  stop: (sessionId?: string) => post<{ workerStopped: boolean; session: Session | null }>("/api/robot/stop", { sessionId }),
};

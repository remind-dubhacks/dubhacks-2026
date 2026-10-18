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

export type Participant = {
  _id: string;
  alias: string;
  interestTags: string[];
  consentFlags: { sessionConsent: boolean; rememberPreferences: boolean };
  preferences?: { favoriteObjectId?: string };
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

const post = <T,>(path: string, body: unknown) => req<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => req<{ persistent: boolean; robot: { ready: boolean; mode?: string; busy?: boolean; error?: string } }>("/api/health"),
  participants: () => req<Participant[]>("/api/participants"),
  participant: (id: string) => req<Participant>(`/api/participants/${id}`),
  deleteParticipant: (id: string) => req<{ deleted: Record<string, number> }>(`/api/participants/${id}`, { method: "DELETE" }),
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

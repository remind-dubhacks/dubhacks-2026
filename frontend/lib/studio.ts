const WORKER = process.env.NEXT_PUBLIC_WORKER_URL ?? "http://localhost:8001";

export const workerUrl = WORKER;

export type ArmStatus = { port: string; connected: boolean; calibration: Record<string, number> | null };

export type StudioStatus = {
  process: {
    kind: string | null;
    running: boolean;
    startedAt: number | null;
    episode: number | null;
    phase: string | null;
    exitCode: number | null;
    stoppedByUser?: boolean;
    cmd: string;
  };
  ports: string[];
  follower: ArmStatus;
  leader: ArmStatus;
  cameras: { side: number; wrist: number };
  perceptron: { configured: boolean };
  hfUser: string;
};

export type Dataset = {
  repo: string;
  episodes?: number;
  frames?: number;
  fps?: number;
  sizeMB?: number;
  files?: number;
  features?: string[];
  error?: string;
};

export type MotorHealth = { ok: boolean; tempC?: number; problem?: string | null };

export type UploadState = { phase: string; done: number; total: number; datasetId?: string; error?: string };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${WORKER}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await r.text();
  if (!r.ok) {
    let detail = text;
    try {
      detail = JSON.parse(text).detail ?? text;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return text ? JSON.parse(text) : (null as T);
}

const post = <T,>(path: string, body: unknown = {}) => req<T>(path, { method: "POST", body: JSON.stringify(body) });

export const studio = {
  status: () => req<StudioStatus>("/studio/status"),
  logs: (since: number) => req<{ lines: { seq: number; line: string }[]; last: number }>(`/studio/logs?since=${since}`),
  cameras: () => req<{ index: number; width: number; height: number }[]>("/studio/cameras"),
  cameraUrl: (i: number) => `${WORKER}/studio/camera/${i}.mjpg`,
  health: () => req<Record<string, Record<string, MotorHealth | string>>>("/studio/health"),
  releaseCameras: () => post("/studio/cameras/release"),
  setCameras: (side: number, wrist: number) => post("/studio/config/cameras", { side, wrist }),
  teleop: (rerun = true) => post("/studio/teleop", { cameras: true, rerun }),
  record: (body: { repo: string; task: string; episodes: number; episodeSeconds: number; resetSeconds: number; rerun: boolean; sounds?: boolean }) =>
    post<{ resume: boolean }>("/studio/record", body),
  stop: () => post("/studio/stop"),
  datasets: () => req<Dataset[]>("/studio/datasets"),
  upload: (repo: string) => post<UploadState>("/studio/perceptron/upload", { repo }),
  uploads: () => req<Record<string, UploadState>>("/studio/perceptron/uploads"),
  registerHf: (repoId: string) => post<Record<string, unknown>>("/studio/perceptron/datasets/hf", { repoId }),
  remoteDataset: (id: string) => req<Record<string, unknown>>(`/studio/perceptron/datasets/${id}`),
  train: (datasetId: string, steps: number) => post<Record<string, unknown>>("/studio/perceptron/train", { datasetId, steps }),
  jobs: () => req<unknown>("/studio/perceptron/jobs"),
  job: (id: string) => req<Record<string, unknown>>(`/studio/perceptron/jobs/${id}`),
  deployments: () => req<unknown>("/studio/perceptron/deployments"),
};

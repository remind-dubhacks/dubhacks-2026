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
  serverVoice?: boolean; // the robot laptop speaks recording prompts itself
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

export type Detection = {
  color: string;
  name: string | null;
  score: number;
  bbox: [number, number, number, number];
  center: [number, number];
  areaFrac: number;
  where: string;
};

export type Remembered = {
  name: string;
  lastSeen: number;
  secondsAgo: number;
  camera: number;
  where: string;
  color: string;
  timesSeen: number;
  score: number;
};

export type CampaignTarget = { id: string; task: string; object: string; target: number; variations: string[]; done: number };

export type CampaignConfig = {
  repo: string;
  batchSize: number;
  episodeSeconds: number;
  resetSeconds: number;
  breakSeconds: number;
  visionCheck: boolean;
  autoUpload: boolean;
  autoTrain: boolean;
  trainSteps: number;
  targets: Omit<CampaignTarget, "done">[];
};

export type CampaignStatus = {
  state: string;
  running: boolean;
  paused: boolean;
  message: string;
  messageSeq: number;
  current: { targetId: string; task: string; object: string; episodes: number; batch: number; variation: string } | null;
  config: CampaignConfig;
  targets: CampaignTarget[];
  totalDone: number;
  totalTarget: number;
  datasetEpisodes: number;
  datasetId: string | null;
  jobId: string | null;
  history: { t: number; state: string; message: string }[];
};

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
  clearFault: (arm: "follower" | "leader" = "follower", motor = "gripper") => post<{ cleared: boolean; tempC: number }>("/studio/clear-fault", { arm, motor }),
  releaseCameras: () => post("/studio/cameras/release"),
  setCameras: (side: number, wrist: number) => post("/studio/config/cameras", { side, wrist }),
  teleop: (rerun = true) => post("/studio/teleop", { cameras: true, rerun }),
  record: (body: { repo: string; task: string; episodes: number; episodeSeconds: number; resetSeconds: number; rerun: boolean; sounds?: boolean }) =>
    post<{ resume: boolean }>("/studio/record", body),
  stop: () => post("/studio/stop"),
  datasets: () => req<Dataset[]>("/studio/datasets"),
  campaign: () => req<CampaignStatus>("/studio/campaign"),
  campaignConfig: (cfg: CampaignConfig) => req<CampaignStatus>("/studio/campaign/config", { method: "PUT", body: JSON.stringify(cfg) }),
  campaignAction: (a: "start" | "ready" | "skip" | "pause" | "stop" | "reset-progress") => post<CampaignStatus>(`/studio/campaign/${a}`),
  visionStreamUrl: (i: number) => `${WORKER}/studio/vision/stream/${i}.mjpg?t=${Date.now()}`,
  detections: (camera: number) => req<{ camera: number; age: number; detections: Detection[] }>(`/studio/vision/detections?camera=${camera}`),
  teach: (camera: number, name: string, bbox?: number[]) => post<{ name: string; color: string | null; examples: number }>("/studio/vision/teach", { camera, name, bbox }),
  library: () => req<{ name: string; examples: number; color: string | null }[]>("/studio/vision/library"),
  thumbUrl: (name: string) => `${WORKER}/studio/vision/library/${encodeURIComponent(name)}/thumb.jpg`,
  forget: (name: string) => req<{ removed: number }>(`/studio/vision/library/${encodeURIComponent(name)}`, { method: "DELETE" }),
  memory: () => req<Remembered[]>("/studio/vision/memory"),
  clearMemory: () => req<{ cleared: boolean }>("/studio/vision/memory", { method: "DELETE" }),
  upload: (repo: string) => post<UploadState>("/studio/perceptron/upload", { repo }),
  uploads: () => req<Record<string, UploadState>>("/studio/perceptron/uploads"),
  registerHf: (repoId: string) => post<Record<string, unknown>>("/studio/perceptron/datasets/hf", { repoId }),
  remoteDataset: (id: string) => req<Record<string, unknown>>(`/studio/perceptron/datasets/${id}`),
  train: (datasetId: string, steps: number) => post<Record<string, unknown>>("/studio/perceptron/train", { datasetId, steps }),
  jobs: () => req<unknown>("/studio/perceptron/jobs"),
  job: (id: string) => req<Record<string, unknown>>(`/studio/perceptron/jobs/${id}`),
  deployments: () => req<unknown>("/studio/perceptron/deployments"),
};

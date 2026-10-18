"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Status = "Stable" | "Needs attention" | "Critical" | "Reviewing event";
type AlertSeverity = "High" | "Medium" | "Low";
type Patient = {
  id: string;
  name: string;
  room: string;
  status: Status;
  activity: string;
  activityTime: string;
  lastTherapy: string;
  initials: string;
  color: string;
  connected: boolean;
  note: string;
  accuracy: number;
};
type Alert = {
  id: string;
  patientId: string;
  time: string;
  severity: AlertSeverity;
  title: string;
  description: string;
  state: "New" | "Acknowledged" | "Resolved";
};
type View = "Overview" | "Live Monitoring" | "Alerts" | "Patients" | "Patient History" | "Therapy Analytics" | "Sequence Game" | "Settings";
type TherapySession = {
  id: string;
  patientId: string;
  date: string;
  daysAgo: number;
  accuracy: number;
  responseSeconds: number;
  rounds: number;
  errors: number;
};
type GamePhase = "idle" | "showing" | "input" | "feedback" | "complete";

const initialPatients: Patient[] = [
  { id: "CS-2041", name: "Eleanor Brooks", room: "201", status: "Needs attention", activity: "Possible bed exit", activityTime: "2 min ago", lastTherapy: "Today, 9:32 AM", initials: "EB", color: "rose", connected: true, note: "Prefers a quiet environment. Please approach from the front and allow time to respond.", accuracy: 82 },
  { id: "CS-2018", name: "James Wilson", room: "202", status: "Stable", activity: "Reading in chair", activityTime: "8 min ago", lastTherapy: "Today, 10:14 AM", initials: "JW", color: "blue", connected: true, note: "Uses a walker. Keep pathway to the bathroom clear.", accuracy: 76 },
  { id: "CS-2033", name: "Margaret Chen", room: "203", status: "Reviewing event", activity: "Unusual movement detected", activityTime: "12 min ago", lastTherapy: "Today, 8:55 AM", initials: "MC", color: "teal", connected: true, note: "Enjoys conversation about gardening. Glasses are on the bedside table.", accuracy: 91 },
  { id: "CS-2056", name: "Robert Davis", room: "204", status: "Stable", activity: "Resting comfortably", activityTime: "18 min ago", lastTherapy: "Yesterday, 3:40 PM", initials: "RD", color: "gold", connected: false, note: "Hearing aids are kept in the labeled bedside case overnight.", accuracy: 88 },
];

const initialAlerts: Alert[] = [
  { id: "a1", patientId: "CS-2033", time: "10:42 AM", severity: "High", title: "Unusual movement detected", description: "Repeated movement near the bedside. Please review the video segment.", state: "New" },
  { id: "a2", patientId: "CS-2041", time: "10:36 AM", severity: "Medium", title: "Possible bed exit", description: "A change in position may indicate the resident is leaving the bed.", state: "New" },
  { id: "a3", patientId: "CS-2018", time: "10:21 AM", severity: "Low", title: "Extended inactivity", description: "No activity detected for longer than the usual interval.", state: "Resolved" },
  { id: "a4", patientId: "CS-2056", time: "Yesterday, 8:14 PM", severity: "Low", title: "Scheduled check completed", description: "Caregiver confirmed the resident was resting comfortably.", state: "Resolved" },
];

const therapyStorageKey = "remind.therapy.sessions";
const sequenceColors = [
  { name: "Violet", color: "#681bfa" },
  { name: "Cyan", color: "#19d0e2" },
  { name: "Pink", color: "#f653b4" },
  { name: "Blue", color: "#2878c7" },
];
const initialTherapySessions: TherapySession[] = [
  { id: "demo-eb-1", patientId: "CS-2041", date: "Oct 17, 9:32 AM", daysAgo: 0, accuracy: 82, responseSeconds: 4.2, rounds: 4, errors: 2 },
  { id: "demo-eb-2", patientId: "CS-2041", date: "Oct 16, 2:18 PM", daysAgo: 1, accuracy: 78, responseSeconds: 4.6, rounds: 3, errors: 2 },
  { id: "demo-eb-3", patientId: "CS-2041", date: "Oct 15, 10:05 AM", daysAgo: 2, accuracy: 74, responseSeconds: 4.8, rounds: 3, errors: 3 },
  { id: "demo-eb-4", patientId: "CS-2041", date: "Oct 13, 11:20 AM", daysAgo: 4, accuracy: 80, responseSeconds: 4.4, rounds: 4, errors: 2 },
  { id: "demo-eb-5", patientId: "CS-2041", date: "Oct 11, 9:12 AM", daysAgo: 6, accuracy: 72, responseSeconds: 5.0, rounds: 3, errors: 3 },
  { id: "demo-eb-6", patientId: "CS-2041", date: "Oct 9, 1:44 PM", daysAgo: 8, accuracy: 76, responseSeconds: 4.7, rounds: 3, errors: 2 },
  { id: "demo-eb-7", patientId: "CS-2041", date: "Oct 5, 10:30 AM", daysAgo: 12, accuracy: 69, responseSeconds: 5.2, rounds: 3, errors: 4 },
  { id: "demo-eb-8", patientId: "CS-2041", date: "Sep 29, 2:05 PM", daysAgo: 18, accuracy: 75, responseSeconds: 4.9, rounds: 3, errors: 3 },
  { id: "demo-eb-9", patientId: "CS-2041", date: "Sep 19, 9:55 AM", daysAgo: 28, accuracy: 68, responseSeconds: 5.4, rounds: 2, errors: 4 },
  { id: "demo-eb-10", patientId: "CS-2041", date: "Sep 2, 10:12 AM", daysAgo: 45, accuracy: 71, responseSeconds: 5.1, rounds: 3, errors: 3 },
  { id: "demo-eb-11", patientId: "CS-2041", date: "Jul 29, 11:03 AM", daysAgo: 80, accuracy: 65, responseSeconds: 5.8, rounds: 2, errors: 5 },
  { id: "demo-jw-1", patientId: "CS-2018", date: "Oct 17, 10:14 AM", daysAgo: 0, accuracy: 76, responseSeconds: 4.5, rounds: 3, errors: 2 },
  { id: "demo-mc-1", patientId: "CS-2033", date: "Oct 17, 8:55 AM", daysAgo: 0, accuracy: 91, responseSeconds: 3.8, rounds: 4, errors: 1 },
  { id: "demo-rd-1", patientId: "CS-2056", date: "Oct 16, 3:40 PM", daysAgo: 1, accuracy: 88, responseSeconds: 4.0, rounds: 4, errors: 1 },
];

const navItems: { label: string; view: View; icon: string }[] = [
  { label: "Monitoring", view: "Overview", icon: "monitor" },
  { label: "Alerts", view: "Alerts", icon: "bell" },
  { label: "Patient History", view: "Patients", icon: "users" },
  { label: "Memory Therapy", view: "Therapy Analytics", icon: "brain" },
];

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const };
  const paths: Record<string, React.ReactNode> = {
    grid: <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></>,
    camera: <><rect x="3" y="6" width="13" height="12" rx="2" /><path d="m16 10 5-3v10l-5-3z" /></>,
    brain: <><path d="M12 18V6a3 3 0 0 0-5.8-1A3.5 3.5 0 0 0 4 11.5 3.5 3.5 0 0 0 7 18h5Z" /><path d="M12 18V6a3 3 0 0 1 5.8-1 3.5 3.5 0 0 1 2.2 6.5A3.5 3.5 0 0 1 17 18h-5Zm-4-8h1m6 0h1m-9 4h1m6 0h1" /></>,
    dots: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
    menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
    monitor: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8m-4-4v4" /></>,
    bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="10" cy="7" r="4" /><path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    chart: <><path d="M4 19V5m0 14h17" /><path d="m7 15 4-4 3 2 6-7" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.7a8 8 0 0 1-1.8 1l-.3 1.8h-2.8l-.3-1.8a8 8 0 0 1-1.8-1l-1.7.7-1.4-2.4 1.4-1.1a8 8 0 0 1 0-2l-1.4-1.1 1.4-2.4 1.7.7a8 8 0 0 1 1.8-1l.3-1.8h2.8l.3 1.8a8 8 0 0 1 1.8 1l1.7-.7 1.4 2.4-1.4 1.1a8 8 0 0 1 0 2Z" transform="translate(-1 -1) scale(1.08)" /></>,
    search: <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.5 4.5" /></>,
    chevron: <path d="m9 18 6-6-6-6" />,
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    play: <path d="m9 6 10 6-10 6z" />,
    close: <><path d="m18 6-12 12M6 6l12 12" /></>,
    filter: <><path d="M4 7h16M7 12h10m-7 5h4" /></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11" /><path d="m9 12 2 2 4-4" /></>,
  };
  return <svg {...common}>{paths[name] ?? paths.grid}</svg>;
}

function StatusBadge({ status }: { status: Status }) {
  const className = status === "Stable" ? "stable" : status === "Critical" ? "critical" : status === "Reviewing event" ? "review" : "attention";
  return <span className={`status-badge ${className}`}><span className="status-dot" />{status}</span>;
}

function initialsColor(color: string) {
  return `avatar ${color}`;
}

function RoomScene({ patient, large = false }: { patient: Patient; large?: boolean }) {
  return (
    <div className={`room-scene ${large ? "large" : ""} scene-${patient.color}`} role="img" aria-label={`Simulated room view for ${patient.name}`}>
      <div className="scene-ceiling" />
      <div className="scene-window"><span /><span /><span /><span /></div>
      <div className="scene-wall-art" />
      <div className="scene-cabinet"><i /><i /></div>
      <div className="scene-bed"><div className="scene-pillow" /><div className="scene-blanket" /></div>
      <div className="scene-lamp"><i /></div>
      <div className="scene-person"><i /></div>
      <div className="scene-floor" />
      <span className="scene-label">SIMULATED ROOM VIEW</span>
    </div>
  );
}

export default function Home() {
  const [view, setView] = useState<View>("Overview");
  const [patients] = useState(initialPatients);
  const [alerts, setAlerts] = useState(initialAlerts);
  const [therapySessions, setTherapySessions] = useState(initialTherapySessions);
  const [therapyLoaded, setTherapyLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState("CS-2041");
  const [historyTab, setHistoryTab] = useState("Overview");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("All statuses");
  const [severityFilter, setSeverityFilter] = useState("All severity");
  const [alertPatientFilter, setAlertPatientFilter] = useState("All patients");
  const [alertTimeFilter, setAlertTimeFilter] = useState("All time");
  const [timeRange, setTimeRange] = useState("7 days");
  const [bellOpen, setBellOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [feedExpanded, setFeedExpanded] = useState(false);
  const [toast, setToast] = useState("");
  const [sortRooms, setSortRooms] = useState(true);
  const [eventFocus, setEventFocus] = useState<string | null>(null);
  const [gamePatientId, setGamePatientId] = useState("CS-2041");
  const [gamePhase, setGamePhase] = useState<GamePhase>("idle");
  const [gameSequence, setGameSequence] = useState<number[]>([]);
  const [gameDisplayIndex, setGameDisplayIndex] = useState(0);
  const [gameLitColor, setGameLitColor] = useState<number | null>(null);
  const [gameInput, setGameInput] = useState<number[]>([]);
  const [gameRound, setGameRound] = useState(0);
  const [gameErrors, setGameErrors] = useState(0);
  const [gameCorrectSelections, setGameCorrectSelections] = useState(0);
  const [gameResponseTotal, setGameResponseTotal] = useState(0);
  const [gameStartedAt, setGameStartedAt] = useState(0);
  const [gameLastInputAt, setGameLastInputAt] = useState(0);
  const [gameMessage, setGameMessage] = useState("");
  const gameTransitionRef = useRef<number | null>(null);

  const selected = patients.find((patient) => patient.id === selectedId) ?? patients[0];
  const gamePatient = patients.find((patient) => patient.id === gamePatientId) ?? patients[0];
  const latestGameSession = therapySessions.find((session) => session.patientId === gamePatientId);
  const patientAlerts = alerts.filter((alert) => alert.patientId === selectedId && alert.state !== "Resolved");
  const selectedTherapySessions = therapySessions.filter((session) => session.patientId === selectedId && session.daysAgo <= (timeRange === "7 days" ? 7 : timeRange === "30 days" ? 30 : 90));
  const latestTherapySession = selectedTherapySessions[0];
  const activeAlertCount = alerts.filter((alert) => alert.state !== "Resolved").length;
  const attentionCount = patients.filter((patient) => patient.status !== "Stable").length;
  const displayedPatients = useMemo(() => patients
    .filter((patient) => `${patient.name} ${patient.id} ${patient.room}`.toLowerCase().includes(search.toLowerCase()))
    .filter((patient) => statusFilter === "All statuses" || patient.status === statusFilter)
    .sort((a, b) => sortRooms ? Number(a.room) - Number(b.room) : a.name.localeCompare(b.name)), [patients, search, statusFilter, sortRooms]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(therapyStorageKey);
      if (stored) {
        const parsed: unknown = JSON.parse(stored);
        if (!Array.isArray(parsed) || !parsed.every((session) =>
          session && typeof session.id === "string" && typeof session.patientId === "string"
          && typeof session.date === "string" && typeof session.accuracy === "number"
          && typeof session.daysAgo === "number"
          && typeof session.responseSeconds === "number" && typeof session.rounds === "number"
          && typeof session.errors === "number")) {
          throw new Error("Saved therapy session data is invalid.");
        }
        setTherapySessions(parsed as TherapySession[]);
      }
    } catch (error) {
      notify(`Could not load saved therapy sessions: ${String(error)}`);
    } finally {
      setTherapyLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!therapyLoaded) return;
    try {
      window.localStorage.setItem(therapyStorageKey, JSON.stringify(therapySessions));
    } catch (error) {
      notify(`Could not save therapy sessions: ${String(error)}`);
    }
  }, [therapyLoaded, therapySessions]);

  useEffect(() => {
    if (gamePhase !== "showing") return;
    if (gameDisplayIndex >= gameSequence.length) {
      const timer = window.setTimeout(() => {
        setGameLitColor(null);
        setGameLastInputAt(Date.now());
        setGamePhase("input");
        setGameMessage("Your turn. Tap the colors in the same order.");
      }, 500);
      return () => window.clearTimeout(timer);
    }
    setGameLitColor(gameSequence[gameDisplayIndex]);
    const timer = window.setTimeout(() => {
      setGameLitColor(null);
      setGameDisplayIndex((index) => index + 1);
    }, 620);
    return () => window.clearTimeout(timer);
  }, [gameDisplayIndex, gamePhase, gameSequence]);

  useEffect(() => () => {
    if (gameTransitionRef.current !== null) window.clearTimeout(gameTransitionRef.current);
  }, []);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  }

  function acknowledgeAlert(id: string) {
    setAlerts((current) => current.map((alert) => alert.id === id && alert.state === "New" ? { ...alert, state: "Acknowledged" } : alert));
    notify("Alert acknowledged");
  }

  function resolveAlert(id: string) {
    setAlerts((current) => current.map((alert) => alert.id === id ? { ...alert, state: "Resolved" } : alert));
    notify("Alert marked resolved");
  }

  function showSequence(sequence: number[]) {
    setGameSequence(sequence);
    setGameInput([]);
    setGameDisplayIndex(0);
    setGameLitColor(null);
    setGamePhase("showing");
    setGameMessage("Watch the colors. You will repeat them next.");
  }

  function scheduleGameTransition(callback: () => void, delay: number) {
    if (gameTransitionRef.current !== null) window.clearTimeout(gameTransitionRef.current);
    gameTransitionRef.current = window.setTimeout(() => {
      gameTransitionRef.current = null;
      callback();
    }, delay);
  }

  function replaySequence() {
    setGameInput([]);
    setGameDisplayIndex(0);
    setGameLitColor(null);
    setGamePhase("showing");
    setGameMessage("Watch the colors again, then repeat them.");
  }

  function startSequenceGame() {
    if (gameTransitionRef.current !== null) window.clearTimeout(gameTransitionRef.current);
    gameTransitionRef.current = null;
    setGameStartedAt(Date.now());
    setGameLastInputAt(Date.now());
    setGameRound(1);
    setGameErrors(0);
    setGameCorrectSelections(0);
    setGameResponseTotal(0);
    showSequence(Array.from({ length: 3 }, () => Math.floor(Math.random() * sequenceColors.length)));
  }

  function finishSequenceGame(correctSelections: number, errors: number, responseTotal: number, rounds: number) {
    const attempts = correctSelections + errors;
    const session: TherapySession = {
      id: `session-${Date.now()}`,
      patientId: gamePatientId,
      date: new Date().toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
      daysAgo: 0,
      accuracy: attempts ? Math.round(correctSelections / attempts * 100) : 0,
      responseSeconds: attempts ? Math.round(responseTotal / attempts / 100) / 10 : 0,
      rounds,
      errors,
    };
    setTherapySessions((current) => [session, ...current]);
    setGamePhase("complete");
    setGameLitColor(null);
    setGameMessage("Session complete. Thank you for playing.");
  }

  function selectGameColor(colorIndex: number) {
    if (gamePhase !== "input") return;
    const responseTime = Math.max(0, Date.now() - gameLastInputAt);
    const nextCorrectCount = gameCorrectSelections + 1;
    const nextResponseTotal = gameResponseTotal + responseTime;
    setGameResponseTotal(nextResponseTotal);
    setGameLastInputAt(Date.now());
    if (colorIndex !== gameSequence[gameInput.length]) {
      const nextErrors = gameErrors + 1;
      setGameErrors(nextErrors);
      setGameMessage("That’s okay. Let’s watch the sequence again.");
      setGamePhase("feedback");
      scheduleGameTransition(() => replaySequence(), 900);
      return;
    }

    const nextInput = [...gameInput, colorIndex];
    setGameInput(nextInput);
    setGameCorrectSelections(nextCorrectCount);
    if (nextInput.length !== gameSequence.length) return;

    if (gameRound >= 4) {
      finishSequenceGame(nextCorrectCount, gameErrors, nextResponseTotal, gameRound);
      return;
    }

    const nextRound = gameRound + 1;
    setGameRound(nextRound);
    setGameMessage("Great remembering! Here comes a longer sequence.");
    setGamePhase("feedback");
    scheduleGameTransition(() => showSequence(Array.from({ length: nextRound + 2 }, () => Math.floor(Math.random() * sequenceColors.length))), 1000);
  }

  function openPatient(patientId: string, eventId?: string) {
    setSelectedId(patientId);
    setEventFocus(eventId ?? null);
    setView("Patient History");
    setHistoryTab("Overview");
    setBellOpen(false);
  }

  function navigate(next: View) {
    setView(next);
    setMobileNavOpen(false);
    setBellOpen(false);
    if (next === "Patient History" || next === "Therapy Analytics") {
      setHistoryTab(next === "Therapy Analytics" ? "Therapy Results" : "Overview");
    }
  }

  const filteredAlerts = alerts.filter((alert) =>
    (severityFilter === "All severity" || alert.severity === severityFilter)
    && (alertPatientFilter === "All patients" || alert.patientId === alertPatientFilter)
    && (alertTimeFilter === "All time" || (alertTimeFilter === "Today" && !alert.time.startsWith("Yesterday")) || (alertTimeFilter === "Last hour" && alert.time.startsWith("10:")))
    && (view === "Alerts" || alert.state !== "Resolved"));

  function renderPatientCard(patient: Patient) {
    const severityAlert = alerts.find((alert) => alert.patientId === patient.id && alert.state !== "Resolved");
    return (
      <article className={`patient-card ${patient.status === "Critical" ? "card-critical" : ""}`} key={patient.id}>
        <button className="feed-button" onClick={() => openPatient(patient.id)} aria-label={`Open monitoring for ${patient.name}`}>
          {patient.connected ? <RoomScene patient={patient} /> : (
            <div className="feed-unavailable">
              <span className="unavailable-icon"><Icon name="monitor" size={20} /></span>
              <strong>Video unavailable</strong>
              <span>Connection lost · last seen 10:19 AM</span>
              <span className="feed-demo-label">SIMULATED FEED</span>
            </div>
          )}
          <span className={`stream-label ${patient.connected ? "stream-live" : "stream-offline"}`}>
            <i />{patient.connected ? "DEMO FEED" : "OFFLINE"}
          </span>
          {severityAlert && <span className={`feed-alert-mark ${severityAlert.severity.toLowerCase()}`}><span />{severityAlert.severity} alert</span>}
        </button>
        <div className="patient-card-body">
          <div className="patient-card-heading">
            <div className={initialsColor(patient.color)}>{patient.initials}</div>
            <div className="patient-identity">
              <strong>{patient.name}</strong>
              <span>{patient.id} <i /> Room {patient.room}</span>
            </div>
            <StatusBadge status={patient.status} />
          </div>
          <div className="activity-line">
            <span className="activity-symbol"><Icon name="clock" size={14} /></span>
            <span>{patient.activity}</span>
            <time>{patient.activityTime}</time>
          </div>
          {!patient.connected && <p className="detection-note">Detection unavailable until connection is restored.</p>}
          <div className="patient-card-actions">
            <button className="button-primary compact" onClick={() => openPatient(patient.id)}>Open monitoring <Icon name="arrow" size={14} /></button>
            <button className="button-text compact" onClick={() => { setSelectedId(patient.id); navigate("Patient History"); }}>History</button>
          </div>
        </div>
      </article>
    );
  }

  function renderAlertsPanel(compact = false) {
    return (
      <section className={`alerts-panel ${compact ? "alerts-page-panel" : ""}`}>
        <div className="panel-heading">
          <div>
            <h2>{compact ? "Recent alerts" : "Needs your attention"}</h2>
            <p>{activeAlertCount} open · AI-detected observations</p>
          </div>
          {!compact && <button className="button-text" onClick={() => navigate("Alerts")}>View all <Icon name="arrow" size={14} /></button>}
        </div>
        {compact && (
          <div className="alert-filters">
            <label><span className="sr-only">Filter by severity</span><select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}><option>All severity</option><option>High</option><option>Medium</option><option>Low</option></select></label>
            <label><span className="sr-only">Filter by patient</span><select value={alertPatientFilter} onChange={(event) => setAlertPatientFilter(event.target.value)}><option>All patients</option>{patients.map((patient) => <option key={patient.id} value={patient.id}>{patient.name}</option>)}</select></label>
            <label><span className="sr-only">Filter by time</span><select value={alertTimeFilter} onChange={(event) => setAlertTimeFilter(event.target.value)}><option>All time</option><option>Today</option><option>Last hour</option></select></label>
            <span className="filter-caption"><Icon name="filter" size={14} /> {alerts.length} total</span>
          </div>
        )}
        <div className="alert-list">
          {filteredAlerts.length === 0 ? <p className="empty-state">No alerts match this filter.</p> : filteredAlerts.map((alert) => {
            const patient = patients.find((item) => item.id === alert.patientId)!;
            return (
              <article className={`alert-item severity-${alert.severity.toLowerCase()} ${alert.state.toLowerCase()}`} key={alert.id}>
                <div className="alert-mark"><span /></div>
                <div className="alert-content">
                  <div className="alert-item-top">
                    <span className={`severity-label ${alert.severity.toLowerCase()}`}>{alert.severity} priority</span>
                    <time>{alert.time}</time>
                  </div>
                  <button className="alert-title" onClick={() => openPatient(patient.id, alert.id)}>{alert.title}</button>
                  <p className="alert-patient">{patient.name} <i /> Room {patient.room}</p>
                  <p className="alert-description">{alert.description}</p>
                  <div className="alert-actions">
                    {alert.state === "New" ? <button className="button-primary compact" onClick={() => acknowledgeAlert(alert.id)}>Acknowledge</button> : alert.state === "Acknowledged" ? <><span className="alert-state acknowledged"><Icon name="check" size={13} />Acknowledged</span><button className="button-text compact" onClick={() => resolveAlert(alert.id)}>Mark resolved</button></> : <span className="alert-state resolved"><Icon name="check" size={13} />Resolved</span>}
                    <button className="button-text compact" onClick={() => openPatient(patient.id, alert.id)}>View patient</button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
        <div className="ai-disclaimer"><Icon name="shield" size={15} /><span>AI observations are suggestions, not diagnoses. Review video before confirming.</span></div>
      </section>
    );
  }

  function renderSummary() {
    return (
      <div className="summary-grid">
        <div className="summary-card"><span className="summary-icon blue-icon"><Icon name="users" /></span><div><span>Patients monitored</span><strong>04 <small>of 04</small></strong></div><span className="summary-foot">All assigned residents</span></div>
        <div className="summary-card"><span className="summary-icon amber-icon"><Icon name="bell" /></span><div><span>Needs attention</span><strong>{attentionCount.toString().padStart(2, "0")} <small>patients</small></strong></div><span className="summary-foot">{attentionCount} require a check-in</span></div>
        <div className="summary-card"><span className="summary-icon red-icon"><Icon name="shield" /></span><div><span>Active alerts</span><strong>{activeAlertCount.toString().padStart(2, "0")} <small>open</small></strong></div><span className="summary-foot">Across 3 patient rooms</span></div>
        <div className="summary-card"><span className="summary-icon teal-icon"><Icon name="monitor" /></span><div><span>Rooms connected</span><strong>03 <small>of 04</small></strong></div><span className="summary-foot"><i className="connection-warning" /> Room 205 reconnecting</span></div>
      </div>
    );
  }

  function renderOverview() {
    const overviewCards: { title: string; description: string; icon: string; accent: string; view: View; count: string }[] = [
      { title: "Monitoring", description: "Room cameras & activity", icon: "monitor", accent: "purple", view: "Live Monitoring", count: "04 rooms" },
      { title: "Alerts", description: "Review resident events", icon: "bell", accent: "pink", view: "Alerts", count: `${activeAlertCount.toString().padStart(2, "0")} open` },
      { title: "Patient History", description: "Resident notes & timeline", icon: "clock", accent: "cyan", view: "Patients", count: "04 residents" },
      { title: "Memory Therapy", description: "Remember the Sequence", icon: "brain", accent: "blue", view: "Therapy Analytics", count: "12 sessions today" },
    ];
    return <>
      <div className="page-title-row dashboard-welcome">
        <div><div className="eyebrow">MONDAY, OCTOBER 17, 2026</div><h1>Good morning, Sarah</h1><p>Your resident care overview.</p></div>
        <div className="welcome-tools"><span className="facility-status"><i /> 3 of 4 rooms connected</span></div>
      </div>
      <div className="overview-stats">
        <button onClick={() => navigate("Patients")}><span className="stat-icon cyan"><Icon name="users" size={17} /></span><span><strong>04</strong><small>Residents monitored</small></span></button>
        <button onClick={() => navigate("Alerts")}><span className="stat-icon pink"><Icon name="bell" size={17} /></span><span><strong>{activeAlertCount.toString().padStart(2, "0")}</strong><small>Unresolved alerts</small></span></button>
        <span className="facility-status"><i /> 3 of 4 rooms connected</span>
      </div>
      <section className="primary-destinations" aria-label="Primary destinations">
        {overviewCards.map((card) => <button className={`destination-card ${card.accent}`} key={card.title} onClick={() => navigate(card.view)}><span className="destination-icon"><Icon name={card.icon} size={21} /></span><span className="destination-copy"><strong>{card.title}</strong><small>{card.description}</small><em>{card.count} <Icon name="arrow" size={13} /></em></span></button>)}
      </section>
      <div className="monitoring-section-heading"><div><span className="eyebrow">ROOM OVERVIEW</span><h2>Resident monitoring</h2><p>All room previews are simulated demo feeds.</p></div><button className="button-text" onClick={() => navigate("Live Monitoring")}>Open monitoring <Icon name="arrow" size={14} /></button></div>
      <div className="patient-grid">{patients.map(renderPatientCard)}</div>
      <div className="video-footnote"><span className="demo-pill">DEMO</span> Simulated camera previews · Not connected to live cameras.</div>
    </>;
  }

  function renderMonitoring() {
    return <>
      <div className="page-title-row">
        <div><div className="eyebrow">CARE TEAM / LIVE MONITORING</div><h1>Live monitoring</h1><p>Room feeds and current resident activity.</p></div>
        <span className="facility-status"><i /> 3 of 4 rooms connected</span>
      </div>
      {renderSummary()}
      <div className="patient-grid monitoring-grid">{patients.map(renderPatientCard)}</div>
      <div className="system-notice"><span className="notice-icon"><Icon name="monitor" /></span><div><strong>Room 205 video connection lost</strong><p>Monitoring is paused for this room. AI activity detection is unavailable until the feed reconnects.</p></div><button className="button-secondary" onClick={() => notify("Reconnection requested for Room 205")}>Retry connection</button></div>
    </>;
  }

  function renderDirectory() {
    return <>
      <div className="page-title-row"><div><div className="eyebrow">CARE TEAM / RESIDENT RECORDS</div><h1>Patient History</h1><p>Search residents and open their care and activity history.</p></div><span className="directory-count">{patients.length} residents</span></div>
      <div className="directory-toolbar">
        <label className="search-box"><Icon name="search" size={18} /><span className="sr-only">Search patients</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, room, or ID..." /></label>
        <label className="select-box"><span className="sr-only">Filter by monitoring status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>All statuses</option><option>Stable</option><option>Needs attention</option><option>Reviewing event</option><option>Critical</option></select></label>
        <button className="button-secondary sort-button" onClick={() => setSortRooms((value) => !value)}>Sort by {sortRooms ? "room" : "name"} <Icon name="filter" size={15} /></button>
      </div>
      <div className="directory-table-wrap">
        <table className="directory-table"><thead><tr><th>Patient</th><th>Room</th><th>Monitoring status</th><th>Last activity</th><th>Last alert</th><th>Last therapy</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{displayedPatients.map((patient) => {
            const recentAlert = alerts.find((alert) => alert.patientId === patient.id);
            return <tr key={patient.id}><td><div className="table-person"><span className={initialsColor(patient.color)}>{patient.initials}</span><span><strong>{patient.name}</strong><small>{patient.id}</small></span></div></td><td>Room {patient.room}</td><td><StatusBadge status={patient.status} /></td><td><span>{patient.activity}</span><small className="table-subtext">{patient.activityTime}</small></td><td>{recentAlert ? <><span>{recentAlert.title}</span><small className="table-subtext">{recentAlert.time} · {recentAlert.state}</small></> : <span className="muted-cell">None</span>}</td><td>{patient.lastTherapy}</td><td><button className="icon-button" aria-label={`View ${patient.name}`} onClick={() => openPatient(patient.id)}><Icon name="arrow" size={17} /></button></td></tr>;
          })}</tbody>
        </table>
        {displayedPatients.length === 0 && <p className="empty-state directory-empty">No residents match your search.</p>}
      </div>
      <p className="privacy-caption"><Icon name="shield" size={15} /> Resident information is visible to authorized care-team members only.</p>
    </>;
  }

  function renderPatientView() {
    const chartHistory = selectedTherapySessions.slice(0, timeRange === "7 days" ? 7 : timeRange === "30 days" ? 30 : 90).reverse();
    const chartValues = chartHistory.length ? chartHistory.map((session) => session.accuracy) : [selected.accuracy];
    const chartPoints = chartValues.map((value, index) => `${chartValues.length === 1 ? 50 : (index / (chartValues.length - 1)) * 100},${100 - value}`).join(" ");
    const eventAlerts = alerts.filter((alert) => alert.patientId === selected.id);
    return <>
      <div className="breadcrumb"><button onClick={() => navigate("Patients")}>Patients</button><Icon name="chevron" size={13} /><span>{selected.name}</span></div>
      <div className="patient-detail-heading">
        <div className={initialsColor(selected.color)}>{selected.initials}</div>
        <div className="detail-identity"><h1>{selected.name}</h1><p>{selected.id} <i /> Room {selected.room} <i /> Last therapy: {selected.lastTherapy}</p></div>
        <StatusBadge status={selected.status} />
        <button className="button-secondary detail-back" onClick={() => navigate("Patients")}>All patients</button>
      </div>
      <div className="history-tabs" role="tablist" aria-label="Patient history sections">
        {["Overview", "Monitoring History", "Therapy Results", "Care Notes"].map((tab) => <button key={tab} role="tab" aria-selected={historyTab === tab} className={historyTab === tab ? "active" : ""} onClick={() => setHistoryTab(tab)}>{tab}</button>)}
      </div>
      {historyTab === "Overview" && <div className="detail-layout">
        <div className="detail-main">
          {eventFocus && <div className="event-focus"><span className="focus-mark"><Icon name="bell" size={16} /></span><div><strong>Alert event selected</strong><p>Review the related observation and video segment for context.</p></div><button aria-label="Dismiss selected event" onClick={() => setEventFocus(null)}><Icon name="close" size={16} /></button></div>}
          <section className="detail-video-card">
            <div className="detail-video-heading"><div><h2>Room {selected.room} · Demo feed</h2><p>Simulated camera preview · Not connected to a real camera</p></div><span className={`feed-connection ${selected.connected ? "connected" : "disconnected"}`}><i />{selected.connected ? "Demo available" : "Unavailable"}</span></div>
            {selected.connected ? <div className="detail-video"><RoomScene patient={selected} large /><button className="expand-feed" onClick={() => setFeedExpanded(true)}><Icon name="monitor" size={15} /> Expand view</button></div> : <div className="large-unavailable"><Icon name="monitor" size={28} /><strong>Video feed unavailable</strong><span>Connection lost at 10:19 AM. Activity detection is paused.</span><button className="button-secondary" onClick={() => notify("Reconnection requested for Room 205")}>Retry connection</button></div>}
            <div className="video-timeline"><span>10:00 AM</span><div className="timeline-track"><i style={{ left: "21%" }} /><i className="timeline-event" style={{ left: "62%" }} /><i style={{ left: "81%" }} /></div><span>Now</span></div>
            <div className="timeline-legend"><span><i />Activity</span><span><i className="legend-alert" />AI-detected event</span></div>
          </section>
          <section className="event-timeline-card"><div className="section-heading"><div><h2>Recent activity</h2><p>Today · AI-detected observations</p></div><button className="button-text" onClick={() => setHistoryTab("Monitoring History")}>Full history <Icon name="arrow" size={14} /></button></div>
            <div className="timeline-events"><div className="timeline-event-row"><span className="event-time">10:42 AM</span><span className="event-line high"><i /></span><div><strong>{selected.activity}</strong><p>Possible anomaly detected · Review before confirming</p><button className="inline-link" onClick={() => notify("Video segment opened for review")}>Review video segment <Icon name="arrow" size={12} /></button></div></div><div className="timeline-event-row"><span className="event-time">10:14 AM</span><span className="event-line"><i /></span><div><strong>Movement in room</strong><p>Resident moved from chair to bedside</p></div></div><div className="timeline-event-row"><span className="event-time">9:52 AM</span><span className="event-line"><i /></span><div><strong>Room activity detected</strong><p>Resident seated near the window</p></div></div></div>
          </section>
        </div>
        <aside className="detail-side">
          <section className="side-card care-profile"><div className="side-card-heading"><h2>Care profile</h2><span className="private-label"><Icon name="shield" size={13} /> Private</span></div><p>{selected.note}</p><div className="profile-divider" /><div className="profile-meta"><span>Last observed activity</span><strong>{selected.activity}</strong><small>{selected.activityTime}</small></div><div className="profile-meta"><span>Demo feed status</span><strong className={selected.connected ? "connected-text" : "error-text"}>{selected.connected ? "Available" : "Unavailable"}</strong></div></section>
          {patientAlerts.length > 0 && <section className="side-card active-detail-alert"><div className="side-card-heading"><h2>Open alert</h2><span className="severity-label high">{patientAlerts[0].severity} priority</span></div>{patientAlerts.map((alert) => <div key={alert.id}><strong>{alert.title}</strong><p>{alert.description}</p><div className="alert-actions">{alert.state === "New" ? <button className="button-primary compact" onClick={() => acknowledgeAlert(alert.id)}>Acknowledge alert</button> : <><span className="alert-state acknowledged"><Icon name="check" size={13} />Acknowledged</span><button className="button-text compact" onClick={() => resolveAlert(alert.id)}>Mark resolved</button></>}<button className="button-text compact" onClick={() => notify("Video segment opened for review")}>Review video</button></div></div>)}</section>}
          <section className="side-card care-progress-card"><div className="side-card-heading"><h2>Therapy progress</h2><button className="button-text compact" onClick={() => setHistoryTab("Therapy Results")}>Details</button></div><strong className="progress-number">{selected.accuracy}<small>%</small></strong><p>Latest activity accuracy <span className="trend-up">↑ 4%</span></p><div className="progress-track"><span style={{ width: `${selected.accuracy}%` }} /></div><small className="progress-caption">Illustrative activity data · not a clinical measure</small></section>
          <section className="side-card"><div className="side-card-heading"><h2>Recent events</h2><button className="button-text compact" onClick={() => setHistoryTab("Monitoring History")}>View all</button></div>{eventAlerts.length ? eventAlerts.map((alert) => <div className="mini-event" key={alert.id}><span className={`mini-event-dot ${alert.severity.toLowerCase()}`} /><div><strong>{alert.title}</strong><small>{alert.time} · {alert.state}</small></div></div>) : <p className="quiet-text">No recent alerts for this resident.</p>}</section>
        </aside>
      </div>}
      {historyTab === "Monitoring History" && <section className="history-content"><div className="section-heading"><div><h2>Monitoring history</h2><p>Timestamped activity and possible anomalies · Today</p></div><button className="button-secondary"><Icon name="filter" size={15} /> Filter events</button></div><div className="history-list"><div className="history-row"><span>10:42 AM</span><span className="history-level high">Possible anomaly</span><div><strong>{selected.activity}</strong><p>AI observation · Caregiver review recommended</p></div><button className="button-text compact" onClick={() => notify("Video segment opened for review")}>Review clip</button></div><div className="history-row"><span>10:14 AM</span><span className="history-level low">Activity</span><div><strong>Movement in room</strong><p>Resident moved from chair to bedside</p></div><span className="resolved-chip">Observed</span></div><div className="history-row"><span>9:52 AM</span><span className="history-level low">Activity</span><div><strong>Room activity detected</strong><p>Resident seated near the window</p></div><span className="resolved-chip">Observed</span></div><div className="history-row"><span>9:32 AM</span><span className="history-level low">Therapy</span><div><strong>Memory activity session completed</strong><p>Caregiver-supervised · 6 minutes</p></div><span className="resolved-chip">Completed</span></div></div><p className="privacy-caption"><Icon name="shield" size={15} /> AI detections are possible observations, not diagnoses or confirmed events.</p></section>}
      {historyTab === "Care Notes" && <section className="history-content care-notes"><div className="section-heading"><div><h2>Care notes</h2><p>Relevant reminders for the current shift</p></div><button className="button-primary compact" onClick={() => notify("Care note editor is ready")}>Add note</button></div><article className="care-note"><span className="note-avatar">AL</span><div><div className="note-byline"><strong>Alex Lee · Caregiver</strong><time>Today, 8:15 AM</time></div><p>{selected.note}</p><span className="note-tag">Shift handoff</span></div></article><article className="care-note"><span className="note-avatar sage">MR</span><div><div className="note-byline"><strong>Morgan Reed · RN</strong><time>Yesterday, 6:40 PM</time></div><p>Evening routine completed. Resident was comfortable and settled before quiet hours.</p><span className="note-tag">Care update</span></div></article></section>}
      {historyTab === "Therapy Results" && <section className="therapy-content">
        <div className="section-heading"><div><h2>Memory activity results</h2><p>Engagement over time · compare with this resident&apos;s own history</p></div><label className="select-box range-select"><span className="sr-only">Therapy chart date range</span><select value={timeRange} onChange={(event) => setTimeRange(event.target.value)}><option>7 days</option><option>30 days</option><option>90 days</option></select></label></div>
        <div className="therapy-metrics"><div className="therapy-metric"><span>Latest accuracy</span><strong>{latestTherapySession?.accuracy ?? selected.accuracy}%</strong><small>Remember the Sequence</small></div><div className="therapy-metric"><span>Avg. response time</span><strong>{(selectedTherapySessions.reduce((total, session) => total + session.responseSeconds, 0) / Math.max(1, selectedTherapySessions.length)).toFixed(1)} <small>sec</small></strong><small>Across saved sessions</small></div><div className="therapy-metric"><span>Completed sessions</span><strong>{selectedTherapySessions.length}</strong><small>Caregiver-supervised</small></div><div className="therapy-metric"><span>Completion rate</span><strong>90%</strong><small>Illustrative sample</small></div></div>
        <section className="chart-card"><div className="chart-title"><div><h3>Session accuracy</h3><p>Illustrative game activity · not a clinical measure</p></div><span className="chart-legend"><i />Remember the Sequence</span></div><div className="chart-wrap"><div className="chart-y-axis"><span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span></div><div className="chart-plot"><div className="chart-gridline one" /><div className="chart-gridline two" /><div className="chart-gridline three" /><div className="chart-gridline four" /><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`Sequence game accuracy for ${selected.name}, ${timeRange}`}><polyline points={chartPoints} fill="none" stroke="#681bfa" strokeWidth="2.2" vectorEffect="non-scaling-stroke" />{chartValues.map((value, index) => <circle key={index} cx={chartValues.length === 1 ? 50 : (index / (chartValues.length - 1)) * 100} cy={100 - value} r="1.4" fill="#fff" stroke="#19d0e2" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />)}</svg><div className="chart-x-axis">{chartHistory.map((session) => <span key={session.id}>{session.date.split(",")[0]}</span>)}</div></div></div></section>
        <section className="session-table-card"><div className="section-heading"><div><h2>Session history</h2><p>Remember the Sequence · most recent first</p></div></div><div className="session-table"><div className="session-row header"><span>Date</span><span>Game</span><span>Accuracy</span><span>Avg. response</span><span>Rounds</span></div>{selectedTherapySessions.map((session) => <div className="session-row" key={session.id}><span>{session.date}</span><span>Remember the Sequence</span><span>{session.accuracy}%</span><span>{session.responseSeconds.toFixed(1)} sec</span><span>{session.rounds}</span></div>)}</div>{selectedTherapySessions.length === 0 && <p className="empty-state">No sessions yet. Start a game to record this resident&apos;s progress.</p>}</section>
        <p className="privacy-caption"><Icon name="shield" size={15} /> Game activity supports engagement only; it does not diagnose or measure cognitive decline.</p>
      </section>}
    </>;
  }

  function renderMemoryTherapy() {
    const chartHistory = selectedTherapySessions.slice(0, timeRange === "7 days" ? 7 : timeRange === "30 days" ? 30 : 90).reverse();
    const chartValues = chartHistory.map((session) => session.accuracy);
    const chartPoints = chartValues.map((value, index) => `${chartValues.length === 1 ? 50 : (index / (chartValues.length - 1)) * 100},${100 - value}`).join(" ");
    const averageResponse = selectedTherapySessions.reduce((total, session) => total + session.responseSeconds, 0) / Math.max(1, selectedTherapySessions.length);
    return <>
      <div className="page-title-row"><div><div className="eyebrow">REMIND / MEMORY THERAPY</div><h1>Memory Therapy</h1><p>A guided sequence activity and resident progress, all in one place.</p></div><label className="select-box therapy-resident-select"><span className="sr-only">Select resident for therapy</span><select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{patients.map((patient) => <option value={patient.id} key={patient.id}>{patient.name} · Room {patient.room}</option>)}</select></label></div>
      <section className="sequence-feature"><div className="sequence-feature-copy"><span className="sequence-kicker"><Icon name="brain" size={16} /> GUIDED MEMORY ACTIVITY</span><h2>Remember the Sequence</h2><p>Practice memory and sequence recall through a guided activity. Watch the colors, then tap them back in order.</p><div className="sequence-resident"><span className={initialsColor(selected.color)}>{selected.initials}</span><span><small>Playing with</small><strong>{selected.name} · Room {selected.room}</strong></span></div><button className="button-primary sequence-start" onClick={() => { setGamePatientId(selectedId); startSequenceGame(); navigate("Sequence Game"); }}>Start Game <Icon name="arrow" size={15} /></button></div><div className="sequence-illustration" aria-hidden="true"><div className="sequence-ring ring-outer" /><div className="sequence-ring ring-inner" /><div className="sequence-pulse pulse-one" /><div className="sequence-pulse pulse-two" /><div className="sequence-color-chip chip-purple" /><div className="sequence-color-chip chip-cyan" /><div className="sequence-color-chip chip-pink" /><div className="sequence-center"><Icon name="brain" size={34} /></div></div></section>
      <div className="section-heading therapy-progress-heading"><div><h2>{selected.name}&apos;s progress</h2><p>Illustrative game activity · not a clinical assessment</p></div><label className="select-box range-select"><span className="sr-only">Filter therapy sessions by date range</span><select value={timeRange} onChange={(event) => setTimeRange(event.target.value)}><option>7 days</option><option>30 days</option><option>90 days</option></select></label></div>
      <div className="therapy-metrics"><div className="therapy-metric"><span>Latest accuracy</span><strong>{latestTherapySession?.accuracy ?? selected.accuracy}%</strong><small>Remember the Sequence</small></div><div className="therapy-metric"><span>Avg. response time</span><strong>{averageResponse.toFixed(1)} <small>sec</small></strong><small>Across saved sessions</small></div><div className="therapy-metric"><span>Sessions completed</span><strong>{selectedTherapySessions.length}</strong><small>Caregiver-supervised</small></div><div className="therapy-metric"><span>Completion rate</span><strong>90%</strong><small>Illustrative sample</small></div></div>
      <section className="chart-card therapy-chart-card"><div className="chart-title"><div><h3>Accuracy over time</h3><p>Compare with this resident&apos;s own activity history.</p></div><span className="chart-legend"><i />Sequence accuracy</span></div><div className="chart-wrap"><div className="chart-y-axis"><span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span></div><div className="chart-plot"><div className="chart-gridline one" /><div className="chart-gridline two" /><div className="chart-gridline three" /><div className="chart-gridline four" /><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`Memory game accuracy history for ${selected.name}`}><polyline points={chartPoints} fill="none" stroke="#681bfa" strokeWidth="2.3" vectorEffect="non-scaling-stroke" />{chartValues.map((value, index) => <circle key={chartHistory[index].id} cx={chartValues.length === 1 ? 50 : (index / (chartValues.length - 1)) * 100} cy={100 - value} r="1.5" fill="#fff" stroke={index % 2 ? "#19d0e2" : "#f653b4"} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />)}</svg><div className="chart-x-axis">{chartHistory.map((session) => <span key={session.id}>{session.date.split(",")[0]}</span>)}</div></div></div></section>
      <section className="session-table-card memory-session-table"><div className="section-heading"><div><h2>Recent sessions</h2><p>Remember the Sequence · most recent first</p></div><button className="button-text compact" onClick={() => { navigate("Patient History"); setHistoryTab("Therapy Results"); }}>Full history <Icon name="arrow" size={13} /></button></div><div className="session-table"><div className="session-row header"><span>Date</span><span>Game</span><span>Accuracy</span><span>Response</span><span>Rounds</span></div>{selectedTherapySessions.slice(0, timeRange === "7 days" ? 7 : timeRange === "30 days" ? 30 : 90).map((session) => <div className="session-row" key={session.id}><span>{session.date}</span><span>Remember the Sequence</span><span>{session.accuracy}%</span><span>{session.responseSeconds.toFixed(1)} sec</span><span>{session.rounds}</span></div>)}</div>{selectedTherapySessions.length === 0 && <p className="empty-state">No sessions recorded yet.</p>}</section>
      <p className="privacy-caption"><Icon name="shield" size={15} /> Progress reflects game performance only and is not a validated clinical measure.</p>
    </>;
  }

  function renderSequenceGame() {
    const averageResponse = latestGameSession?.responseSeconds.toFixed(1)
      ?? (gameResponseTotal / Math.max(1, gameCorrectSelections + gameErrors) / 1000).toFixed(1);
    return <section className="sequence-game-page">
      <div className="breadcrumb"><button onClick={() => navigate("Therapy Analytics")}>Memory Therapy</button><Icon name="chevron" size={13} /><span>Remember the Sequence</span></div>
      <div className="sequence-game-heading"><span className="eyebrow">GUIDED MEMORY ACTIVITY</span><h1>Remember the Sequence</h1><p>For {gamePatient.name} · Room {gamePatient.room}</p></div>
      {gamePhase === "idle" && <div className="sequence-idle"><p>Watch the colored buttons light up, then repeat the pattern in the same order. Each round adds one color. Take your time.</p><button className="button-primary" onClick={startSequenceGame}>Begin activity</button></div>}
      {(gamePhase === "showing" || gamePhase === "input" || gamePhase === "feedback") && <div className="sequence-game-card"><div className="sequence-game-status"><div><strong>{gamePhase === "showing" ? "Watch the pattern" : gamePhase === "input" ? "Your turn" : "Nice effort"}</strong><span>Round {gameRound} of 4 · Sequence of {gameSequence.length}</span></div><button className="button-text compact" onClick={() => { if (gameTransitionRef.current !== null) window.clearTimeout(gameTransitionRef.current); gameTransitionRef.current = null; setGamePhase("idle"); navigate("Therapy Analytics"); }}>Exit activity</button></div><p className="sequence-message" aria-live="polite">{gameMessage}</p><div className="sequence-pad" role="group" aria-label="Sequence color buttons">{sequenceColors.map((color, index) => <button type="button" key={color.name} className={`sequence-pad-button ${gameLitColor === index ? "lit" : ""}`} style={{ "--sequence-color": color.color } as React.CSSProperties} aria-label={`${color.name} button`} disabled={gamePhase !== "input"} onClick={() => selectGameColor(index)}><span className="sr-only">{color.name}</span></button>)}</div><div className="sequence-game-progress"><span>Correct taps <strong>{gameCorrectSelections}</strong></span><span>Try again <strong>{gameErrors}</strong></span></div><p className="sequence-demo-note">Illustrative activity · colors are not associated with clinical outcomes.</p></div>}
      {gamePhase === "complete" && <div className="sequence-complete"><span className="complete-check"><Icon name="check" size={24} /></span><h2>Activity complete</h2><p>Nice work, {gamePatient.name.split(" ")[0]}. Your session has been saved to their progress.</p><div className="complete-stats"><span><strong>{latestGameSession?.accuracy ?? 0}%</strong><small>Accuracy</small></span><span><strong>{averageResponse}s</strong><small>Avg. response</small></span><span><strong>{gameRound}</strong><small>Rounds</small></span><span><strong>{Math.round((Date.now() - gameStartedAt) / 1000)}s</strong><small>Duration</small></span></div><div className="complete-actions"><button className="button-primary" onClick={() => { setSelectedId(gamePatientId); navigate("Therapy Analytics"); }}>View progress</button><button className="button-secondary" onClick={startSequenceGame}>Play again</button></div></div>}
    </section>;
  }

  function renderSettings() {
    return <>
      <div className="page-title-row"><div><div className="eyebrow">CARE TEAM / PREFERENCES</div><h1>Settings</h1><p>Station and notification preferences for this device.</p></div></div>
      <section className="settings-card"><div className="settings-row"><div><strong>Shift status</strong><p>Day shift · 7:00 AM – 7:00 PM</p></div><span className="facility-status"><i /> In progress</span></div><div className="settings-row"><div><strong>Room feed status</strong><p>Three demo feeds available. Room 204 connection is unavailable.</p></div><span className="status-badge attention"><span className="status-dot" />Review needed</span></div><div className="settings-row"><div><strong>Notification preferences</strong><p>High and medium priority alerts are enabled for this station.</p></div><button className="button-secondary" onClick={() => notify("Notification preferences saved")}>Manage</button></div><div className="settings-row"><div><strong>Privacy & access</strong><p>Patient information is restricted to this authenticated care-team view.</p></div><Icon name="shield" /></div><div className="settings-links"><a href="/caregiver">Caregiver controls <Icon name="arrow" size={14} /></a></div></section>
    </>;
  }

  return (
    <div className="station">
      <header className="topbar">
        <button className="mobile-menu-button" aria-label="Toggle navigation" onClick={() => setMobileNavOpen(!mobileNavOpen)}><span /><span /><span /></button>
        <button className="sidebar-toggle" aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}><Icon name="menu" size={18} /></button>
        <button className="brand" onClick={() => navigate("Overview")} aria-label="ReMind Care home"><span className="brand-symbol"><i /><i /><i /><i /></span><span>Re<span className="brand-light">Mind</span><span className="brand-care"> Care</span></span></button>
        <div className="topbar-right"><button className="topbar-action live-action" onClick={() => navigate("Live Monitoring")}><Icon name="camera" size={15} /> View Live Rooms</button><button className="topbar-action history-action" onClick={() => { setSelectedId(patients[0].id); navigate("Patient History"); }}><Icon name="clock" size={15} /> Resident History</button><span className="top-facility-status"><i />Facility online</span><button className="notification-button" aria-label={`${activeAlertCount} open notifications`} onClick={() => setBellOpen(!bellOpen)}><Icon name="bell" size={18} />{activeAlertCount > 0 && <span>{activeAlertCount}</span>}</button><button className="profile-button" onClick={() => navigate("Settings")}><span className="profile-avatar">SM</span><span className="profile-text"><strong>Sarah Morgan</strong><small>Caregiver</small></span><Icon name="chevron" size={14} /></button></div>
        {bellOpen && <div className="notification-popover"><div className="popover-heading"><strong>Recent alerts</strong><button className="button-text compact" onClick={() => navigate("Alerts")}>View all</button></div>{alerts.filter((alert) => alert.state !== "Resolved").slice(0, 3).map((alert) => { const patient = patients.find((item) => item.id === alert.patientId)!; return <button className="popover-alert" key={alert.id} onClick={() => openPatient(patient.id, alert.id)}><span className={`popover-dot ${alert.severity.toLowerCase()}`} /><span><strong>{alert.title}</strong><small>{patient.name} · Room {patient.room} · {alert.time}</small></span></button>; })}</div>}
      </header>
      <div className={`station-layout ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        <aside className={`sidebar ${mobileNavOpen ? "mobile-open" : ""}`}>
          <div className="sidebar-label">CARE MANAGEMENT</div>
          <nav aria-label="Care team navigation">{navItems.map((item) => <button key={item.label} title={sidebarCollapsed ? item.label : undefined} onClick={() => navigate(item.view)} className={`nav-item ${view === item.view || (view === "Patient History" && item.view === "Patients") || (view === "Sequence Game" && item.view === "Therapy Analytics") ? "selected" : ""}`}><Icon name={item.icon} size={18} /><span>{item.label}</span>{item.label === "Alerts" && activeAlertCount > 0 && <span className="nav-count">{activeAlertCount}</span>}</button>)}</nav>
          <div className="sidebar-bottom"><div className="sidebar-secure"><Icon name="shield" size={16} /><span>Secure care-team view</span></div><div className="facility-name"><span className="facility-mark">E</span><span><strong>Evergreen Memory Care</strong><small>West Wing · Care Team</small></span></div><a href="/caregiver" className="sidebar-tool-link">Caregiver controls <Icon name="arrow" size={13} /></a></div>
        </aside>
        <main className="station-main">
          {view === "Overview" && renderOverview()}
          {view === "Live Monitoring" && renderMonitoring()}
          {view === "Patients" && renderDirectory()}
          {view === "Alerts" && <><div className="page-title-row"><div><div className="eyebrow">CARE TEAM / ALERT CENTER</div><h1>Alerts</h1><p>Review AI-detected observations and follow up with residents.</p></div><span className="directory-count">{activeAlertCount} open alerts</span></div>{renderAlertsPanel(true)}</>}
          {view === "Patient History" && renderPatientView()}
          {view === "Therapy Analytics" && renderMemoryTherapy()}
          {view === "Sequence Game" && renderSequenceGame()}
          {view === "Settings" && renderSettings()}
          <footer className="station-footer"><span>ReMind <i /> Secure caregiver station</span><span>Demonstration prototype · All patient data is synthetic</span></footer>
        </main>
      </div>
      {feedExpanded && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`Expanded room feed for ${selected.name}`} onClick={() => setFeedExpanded(false)}><div className="expanded-feed-modal" onClick={(event) => event.stopPropagation()}><div className="modal-heading"><div><strong>Room {selected.room} · {selected.name}</strong><span>Simulated room preview · Demonstration only</span></div><button className="icon-button" aria-label="Close expanded feed" onClick={() => setFeedExpanded(false)}><Icon name="close" /></button></div><RoomScene patient={selected} large /><p><span className="stream-label stream-live"><i />DEMO FEED</span> Video is simulated. AI observations require caregiver review.</p></div></div>}
      {toast && <div className="station-toast" role="status"><Icon name="check" size={16} />{toast}</div>}
    </div>
  );
}

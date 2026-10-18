import { ago } from "./time";

export type Alert = { sessionId: string; participantId: string | null; name: string; title: string; detail: string; at: string };

export function UrgentPanel({ alerts, onOpen, onAcknowledge }: {
  alerts: Alert[];
  onOpen: (participantId: string) => void;
  onAcknowledge: (sessionId: string) => void;
}) {
  if (alerts.length === 0) return null;
  return (
    <section className="urgent" aria-label="Urgent">
      <h2>URGENT <span className="urgent-count">{alerts.length}</span></h2>
      {alerts.map((a) => (
        <div key={a.sessionId} className="urgent-row" role="alert">
          <span className="dot" aria-hidden />
          <div className="urgent-text">
            <p className="urgent-title">{a.name} · {a.title}</p>
            <p className="urgent-detail">{a.detail} · {ago(a.at)}</p>
          </div>
          {a.participantId && <button className="key key-red" onClick={() => onOpen(a.participantId!)}>Open patient</button>}
          <button className="key key-grey" onClick={() => onAcknowledge(a.sessionId)}>Acknowledge</button>
        </div>
      ))}
    </section>
  );
}

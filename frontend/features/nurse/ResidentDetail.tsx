import { useState } from "react";
import { api, type Participant } from "@/lib/api";
import { ContextTab } from "./ContextTab";
import { MemoriesTab } from "./MemoriesTab";
import { SessionsTab } from "./SessionsTab";

const TABS = [["sessions", "Sessions"], ["memories", "Memories"], ["context", "Context"]] as const;
type Tab = (typeof TABS)[number][0];

export function ResidentDetail({ resident, onChange }: { resident: Participant; onChange: (p: Participant) => void }) {
  const [tab, setTab] = useState<Tab>("sessions");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const remember = resident.consentFlags?.rememberPreferences ?? false;

  const toggle = async () => {
    setSaving(true);
    setErr(null);
    onChange({ ...resident, consentFlags: { ...resident.consentFlags, rememberPreferences: !remember } });
    try {
      onChange(await api.setConsent(resident._id, !remember));
    } catch (e) {
      onChange(resident);  // roll back
      setErr(`Could not change consent: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <h2>{resident.alias}</h2>
          <p className="muted">{resident.room ? `Room ${resident.room}` : "No room set"}
            {resident.careProfile?.preferredName && resident.careProfile.preferredName !== resident.alias
              ? ` · likes to be called ${resident.careProfile.preferredName}` : ""}</p>
        </div>
        <div className="consent">
          <button className={`key toggle${remember ? " on" : ""}`} role="switch" aria-checked={remember}
                  disabled={saving} onClick={toggle}>
            <span className="toggle-led" aria-hidden />
            {remember ? "Remembering" : "Not remembering"}
          </button>
          <span className="muted small">Consent to remember</span>
        </div>
      </div>
      {err && <p className="nurse-error" role="alert">{err}</p>}

      <div className="tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={`key tab${tab === id ? " on" : ""}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === "sessions" && <SessionsTab residentId={resident._id} />}
        {tab === "memories" && <MemoriesTab resident={resident} onChange={onChange} />}
        {tab === "context" && <ContextTab resident={resident} onChange={onChange} />}
      </div>
    </div>
  );
}

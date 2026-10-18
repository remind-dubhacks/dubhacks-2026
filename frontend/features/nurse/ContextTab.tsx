import { useState } from "react";
import { api, type CareProfile, type Participant } from "@/lib/api";

type ListField = "interests" | "lifeStory" | "conversationStarters" | "calmingStrategies" | "avoidTopics" | "distressSigns";
const LISTS: [ListField, string, string][] = [
  ["interests", "Interests", "One per line, e.g. gardening, especially roses"],
  ["lifeStory", "Life story", "One fact per line: hometown, work, family, pets"],
  ["conversationStarters", "Conversation starters", "One question per line"],
  ["calmingStrategies", "What calms them", "One per line"],
  ["avoidTopics", "Topics to avoid", "One per line"],
  ["distressSigns", "Signs of distress", "One per line"],
];
const TEXTS: ["preferredName" | "pronunciation" | "bestTimeOfDay", string][] = [
  ["preferredName", "Likes to be called"],
  ["pronunciation", "Pronunciation"],
  ["bestTimeOfDay", "Best time of day"],
];
const toLines = (s: string) => s.split("\n").map((l) => l.trim()).filter(Boolean);

// The care sheet: everything here goes into the companion's prompt at the start of every call (consent to
// remember only governs the Backboard facts). New interests and life-story lines are also added to memory.
export function ContextTab({ resident, onChange }: { resident: Participant; onChange: (p: Participant) => void }) {
  const base = resident.careProfile ?? {};
  const [form, setForm] = useState<CareProfile>(base);
  const [lists, setLists] = useState(() => Object.fromEntries(LISTS.map(([k]) => [k, (base[k] ?? []).join("\n")])) as Record<ListField, string>);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [err, setErr] = useState<string | null>(null);

  const edit = (patch: Partial<CareProfile>) => { setForm((f) => ({ ...f, ...patch })); setState("idle"); };
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setState("saving");
    setErr(null);
    try {
      const profile = { ...form, ...Object.fromEntries(LISTS.map(([k]) => [k, toLines(lists[k])])) };
      onChange(await api.saveCareProfile(resident._id, profile));
      setState("saved");
    } catch (e) {
      setErr((e as Error).message);
      setState("idle");
    }
  };

  return (
    <form className="context" onSubmit={save}>
      <p className="muted">The companion reads this at the start of every call.</p>
      <div className="context-grid">
        {TEXTS.map(([k, label]) => (
          <label key={k} className="field">
            <span>{label}</span>
            <div className="field-well"><input value={form[k] ?? ""} onChange={(e) => edit({ [k]: e.target.value })} /></div>
          </label>
        ))}
        <div className="field">
          <span>Pace</span>
          <div className="segmented">
            {(["normal", "slow"] as const).map((p) => (
              <button type="button" key={p} className={`key tab${(form.pace ?? "normal") === p ? " on" : ""}`}
                      aria-pressed={(form.pace ?? "normal") === p} onClick={() => edit({ pace: p })}>
                {p === "normal" ? "Normal" : "Slow"}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="context-grid">
        {LISTS.map(([k, label, hint]) => (
          <label key={k} className="field">
            <span>{label}</span>
            <div className="field-well">
              <textarea rows={5} value={lists[k]} placeholder={hint}
                        onChange={(e) => { setLists((l) => ({ ...l, [k]: e.target.value })); setState("idle"); }} />
            </div>
          </label>
        ))}
      </div>
      {err && <p className="nurse-error" role="alert">{err}</p>}
      <div className="context-save">
        <button className="key key-pine" disabled={state === "saving"}>{state === "saving" ? "Saving…" : "Save context"}</button>
        {state === "saved" && <span className="muted">Saved. The next call uses this.</span>}
      </div>
    </form>
  );
}

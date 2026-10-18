import { useCallback, useEffect, useState } from "react";
import { api, type MemoriesView, type Participant } from "@/lib/api";
import { when } from "./time";

const KINDS: Record<string, string> = { care_profile: "Care profile", session: "Learnt in a call", nurse: "Added by nurse", fact: "Learnt in a call" };
const FILTERS = [["all", "All"], ["care_profile", "Care profile"], ["session", "Learnt"], ["nurse", "Added by nurse"]] as const;
const kindOf = (k?: string) => (k === "fact" ? "session" : k ?? "session");
const message = (e: unknown) => (e as Error).message.replace(/^\d+: /, "").replace(/^\{"detail":"(.*)"\}$/, "$1");

// The stored facts in this resident's Backboard memory: the companion reads all of them at the start of a call.
export function MemoriesTab({ resident, onChange }: { resident: Participant; onChange: (p: Participant) => void }) {
  const [view, setView] = useState<MemoriesView | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("all");
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);  // memory id, or "all" for forget everything
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pid = resident._id;
  const remember = resident.consentFlags?.rememberPreferences ?? false;

  const load = useCallback(() => api.memories(pid).then(setView, (e) => setErr(message(e))), [pid]);
  useEffect(() => { load(); }, [load, remember]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await action();
      await load();
      setTimeout(load, 2500);  // Backboard can take a moment to index a new fact
    } catch (e) {
      setErr(message(e));
    } finally {
      setBusy(false);
    }
  };

  const add = (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.trim()) return;
    run(async () => { await api.addMemory(pid, draft.trim()); setDraft(""); });
  };
  const save = () => editing && run(async () => { await api.editMemory(pid, editing.id, editing.text.trim()); setEditing(null); });
  const remove = (id: string) => run(async () => { await api.deleteMemory(pid, id); setConfirm(null); });
  const forget = () => run(async () => { onChange(await api.forgetMemories(pid)); setConfirm(null); });

  const shown = (view?.memories ?? []).filter((m) => filter === "all" || kindOf(m.kind) === filter);
  return (
    <div className="memories">
      {view && !view.enabled && <p className="banner">Long-term memory is off on the server (BACKBOARD_API_KEY is not set).</p>}
      {view && view.enabled && !remember && (
        <p className="banner">Not remembering. Nothing new is saved or used in calls. {view.memories.length > 0 && "What is already stored is kept until you forget it."}</p>
      )}
      {err && <p className="nurse-error" role="alert">{err}</p>}

      <form className="add" onSubmit={add}>
        <div className="field-well">
          <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={500} disabled={!remember || busy}
                 placeholder={remember ? `Add a fact, e.g. "${resident.alias}'s favourite food is hot dogs."` : "Turn on Remembering to add facts"} />
        </div>
        <button className="key key-pine" disabled={!remember || busy || !draft.trim()}>Add fact</button>
      </form>

      <div className="filters">
        {FILTERS.map(([id, label]) => (
          <button key={id} className={`chip${filter === id ? " on" : ""}`} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>
        ))}
      </div>

      {!view ? <p className="muted">Loading…</p> : shown.length === 0 ? (
        <p className="muted">{view.memories.length ? "No facts of this kind." : "Nothing is remembered about this person yet."}</p>
      ) : (
        <ul className="list">
          {shown.map((m) => (
            <li key={m.id} className="item fact">
              {editing?.id === m.id ? (
                <div className="field-well grow">
                  <input autoFocus value={editing.text} maxLength={500} onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                         onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(null); }} />
                </div>
              ) : (
                <div className="grow">
                  <p className="item-title">{m.content}</p>
                  <p className="muted small"><span className={`kind kind-${kindOf(m.kind)}`}>{KINDS[m.kind ?? ""] ?? m.kind}</span>{m.createdAt ? ` · ${when(m.createdAt)}` : ""}</p>
                </div>
              )}
              <div className="actions">
                {editing?.id === m.id ? (
                  <>
                    <button className="key key-pine" disabled={busy || !editing.text.trim()} onClick={save}>Save</button>
                    <button className="key key-grey" onClick={() => setEditing(null)}>Cancel</button>
                  </>
                ) : confirm === m.id ? (
                  <>
                    <button className="key key-red" disabled={busy} onClick={() => remove(m.id)}>Delete</button>
                    <button className="key key-grey" onClick={() => setConfirm(null)}>Keep</button>
                  </>
                ) : (
                  <>
                    <button className="key key-grey" disabled={!remember || busy} onClick={() => setEditing({ id: m.id, text: m.content })}>Edit</button>
                    <button className="key key-grey" disabled={busy} onClick={() => setConfirm(m.id)}>Delete</button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {view?.assistantId && (
        <div className="forget">
          {confirm === "all" ? (
            <>
              <p>Delete everything remembered about {resident.alias}? This can't be undone, and remembering turns off.</p>
              <button className="key key-red" disabled={busy} onClick={forget}>Clear Data</button>
              <button className="key key-grey" onClick={() => setConfirm(null)}>Cancel</button>
            </>
          ) : (
            <button className="key key-grey" onClick={() => setConfirm("all")}>Clear Data</button>
          )}
        </div>
      )}
    </div>
  );
}

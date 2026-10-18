import { useRef } from "react";
import type { Participant } from "@/lib/api";

export function ResidentStrip({ residents, selected, flagged, onSelect }: {
  residents: Participant[];
  selected: string | null;
  flagged: Set<string>;
  onSelect: (id: string) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const page = (dir: number) => track.current?.scrollBy({ left: dir * track.current.clientWidth * 0.8, behavior: "smooth" });
  return (
    <nav className="strip" aria-label="Residents">
      <button className="key strip-arrow" aria-label="Previous residents" onClick={() => page(-1)}>
        <svg viewBox="0 0 24 24" aria-hidden><path d="M15 5l-7 7 7 7" /></svg>
      </button>
      <div ref={track} className="strip-track">
        {residents.length === 0 && <p className="strip-none">No residents yet.</p>}
        {residents.map((r) => (
          <button key={r._id} className={`key resident${r._id === selected ? " on" : ""}`} aria-pressed={r._id === selected}
                  onClick={() => onSelect(r._id)}>
            {flagged.has(r._id) && <span className="dot" aria-label="Has an alert" />}
            <span className="resident-name">{r.alias}</span>
            <span className="resident-room">{r.room ? `Room ${r.room}` : "No room set"}</span>
          </button>
        ))}
      </div>
      <button className="key strip-arrow" aria-label="Next residents" onClick={() => page(1)}>
        <svg viewBox="0 0 24 24" aria-hidden><path d="M9 5l7 7-7 7" /></svg>
      </button>
    </nav>
  );
}

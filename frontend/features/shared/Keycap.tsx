// A keycap keyring drawn in CSS (top face, sloped sides, clear switch base), so the table looks like
// the real props: black, white and purple keycaps. Used by the patient table view and the playground.
import "./keycap.css";

const COLOURS: Record<string, string> = { black: "black", white: "white", purple: "purple" };

export function keycapColour(name?: string | null): string {
  return (name && COLOURS[name.split(" ")[0]]) || "plain";
}

export function Keycap({ name, size = 64, state }: { name?: string | null; size?: number; state?: "right" | "off" }) {
  if (!name) return <span className="kc-empty" style={{ width: size, height: size }} aria-hidden="true" />;
  return (
    <span className={`kc kc-${keycapColour(name)}${state ? ` kc-${state}` : ""}`} style={{ width: size, height: size }} aria-hidden="true">
      <span className="kc-cap"><span className="kc-top"><span className="kc-logo" /></span></span>
      <span className="kc-base" />
      {state && <span className="kc-badge">{state === "right" ? "✓" : "?"}</span>}
    </span>
  );
}

const SPOTS3 = ["Left", "Middle", "Right"];

// A row of slots on a soft table surface. Slot 4 (the robot's parking spot) is shown dashed and empty.
export function Board({ row, answer, judge, labels = true, parking = true, size = 72 }: {
  row: (string | null)[]; answer?: string[]; judge?: boolean; labels?: boolean; parking?: boolean; size?: number;
}) {
  const spots = row.length === 2 ? ["Left", "Right"] : SPOTS3;
  return (
    <div className="kc-board">
      {row.map((o, i) => {
        const state = judge && answer ? (o === answer[i] ? "right" : "off") : undefined;
        return (
          <div key={i} className={`kc-slot${state ? ` kc-slot-${state}` : ""}`}>
            <Keycap name={o} size={size} state={state} />
            {labels && <span className="kc-label">{o ? o.split(" ")[0] : "?"}</span>}
            {labels && <span className="kc-spot">{spots[i]}</span>}
          </div>
        );
      })}
      {parking && (
        <div className="kc-slot kc-park">
          <Keycap name={null} size={size} />
          {labels && <span className="kc-label">&nbsp;</span>}
          {labels && <span className="kc-spot">Robot&apos;s spot</span>}
        </div>
      )}
    </div>
  );
}

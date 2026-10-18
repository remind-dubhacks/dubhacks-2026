"use client";

// Renders one Screen at a time and cross-fades between them over 1200ms (design.md "Motion").
// The outgoing layer fades out while the incoming one fades in; nothing slides.
import { useEffect, useRef, useState } from "react";
import type { Screen } from "@/lib/voice";

const FADE_MS = 1200;
const FONT = "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;600&display=swap";

type Layer = { id: number; screen: Screen; visible: boolean };

// Keyring colours for the robot game (game object names from backend/app/games/shuffles.py).
const SWATCH: Record<string, string> = { black: "#23262a", white: "#f6f3ea", purple: "#8d72c9" };
const swatch = (name: string) => SWATCH[name.split(" ")[0]] ?? "#c9cfc6";
const SPOTS = ["Left", "Middle", "Right"];

// Remember the Order: the row as the camera and the game see it, what the robot is doing, and the current
// prompt. Updated live by the relay as the person moves things on the table.
function TableView({ screen }: { screen: Extract<Screen, { kind: "table" }> }) {
  const spots = screen.row.length === 2 ? ["Left", "Right"] : SPOTS;
  return (
    <div className="calm-table">
      {screen.status && <p className="calm-table-status">{screen.status}</p>}
      <div className="calm-row">
        {screen.row.map((o, i) => (
          <div key={i} className="calm-slot">
            <span className="calm-key" style={{ background: o ? swatch(o) : "transparent" }} />
            <span className="calm-slot-name">{o ?? "?"}</span>
            <span className="calm-slot-spot">{spots[i]}</span>
          </div>
        ))}
      </div>
      {screen.options.length > 0 && <p className="calm-table-choice">{screen.options.join("  ·  or  ·  ")}</p>}
    </div>
  );
}

function Content({ screen }: { screen: Screen }) {
  switch (screen.kind) {
    case "message":
      return <p className="calm-message">{screen.text}</p>;
    case "photo":
      return <img className="calm-photo" src={screen.photo} alt="" />;
    case "photo_caption":
      return (
        <>
          <img className="calm-photo with-caption" src={screen.photo} alt="" />
          <p className="calm-caption">{screen.caption}</p>
        </>
      );
    case "table":
      return <TableView screen={screen} />;
    default:
      return null;
  }
}

export function CalmStage({ screen, children }: { screen: Screen; children?: React.ReactNode }) {
  const [layers, setLayers] = useState<Layer[]>([]);
  const nextId = useRef(1);
  const key = JSON.stringify(screen);

  useEffect(() => {
    const id = nextId.current++;
    setLayers((ls) => [...ls.map((l) => ({ ...l, visible: false })), { id, screen, visible: false }]);
    // Two frames so the new layer is painted at opacity 0 before it transitions to 1.
    const raf = requestAnimationFrame(() => requestAnimationFrame(() =>
      setLayers((ls) => ls.map((l) => (l.id === id ? { ...l, visible: true } : l)))));
    const t = setTimeout(() => setLayers((ls) => ls.filter((l) => l.id >= id)), FADE_MS + 100);
    return () => { cancelAnimationFrame(raf); clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <div className="calm">
      <link rel="stylesheet" href={FONT} precedence="default" />
      {layers.map((l) => (
        <div key={l.id} className={`calm-layer${l.visible ? " visible" : ""}`} aria-hidden={!l.visible}>
          <Content screen={l.screen} />
        </div>
      ))}
      {children}
    </div>
  );
}

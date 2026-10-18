// Reorder game helpers. Mirrors backend/app/games/reorder.py so the UI works with or without the backend.
import { API } from "./api";

export type Item = { id: string; label: string; emoji: string };

export const ITEMS: Item[] = [
  { id: "cup", label: "Cup", emoji: "☕" },
  { id: "apple", label: "Apple", emoji: "🍎" },
  { id: "book", label: "Book", emoji: "📖" },
];
export const TARGET = ITEMS.map((i) => i.id);
export const MAX_TRIALS = 3;

export const item = (id: string) => ITEMS.find((i) => i.id === id)!;

export function shuffled(target: string[]): string[] {
  const o = [...target];
  do {
    for (let i = o.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [o[i], o[j]] = [o[j], o[i]];
    }
  } while (o.every((x, i) => x === target[i]));
  return o;
}

export type CheckResult = { correct: boolean; reason: string; misplaced: string[]; confidence: number; source: "backend" | "local" };

export function evaluateLocal(target: string[], observed: string[]): CheckResult {
  const misplaced = target.filter((t, i) => t !== observed[i]);
  const first = target.findIndex((t, i) => t !== observed[i]);
  return {
    correct: misplaced.length === 0,
    misplaced,
    confidence: 1,
    source: "local",
    reason: first < 0 ? "" : `The ${item(target[first]).label.toLowerCase()} should be in spot ${first + 1}, where the ${item(observed[first]).label.toLowerCase()} is now.`,
  };
}

// Uses the vision endpoint (mock mode accepts the order we pass); falls back to local rules offline.
export async function checkOrder(target: string[], observed: string[]): Promise<CheckResult> {
  try {
    const r = await fetch(`${API}/api/vision/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, mockOrder: observed }),
    });
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    return { correct: d.correct, reason: d.reason, misplaced: d.misplaced, confidence: d.confidence, source: "backend" };
  } catch {
    return evaluateLocal(target, observed);
  }
}

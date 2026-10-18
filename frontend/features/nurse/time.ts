// Mongo hands back UTC datetimes without a zone; read those as UTC, not local time.
export const parseTime = (iso: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);

export function ago(iso: string): string {
  const s = (Date.now() - +parseTime(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return parseTime(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

export const when = (iso: string) =>
  parseTime(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

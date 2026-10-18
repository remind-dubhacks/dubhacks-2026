import { item } from "@/lib/reorder";

export function ItemCard({ id, index, onClick, selected, flag }: { id: string; index?: number; onClick?: () => void; selected?: boolean; flag?: boolean }) {
  const it = item(id);
  const Tag = onClick ? "button" : "div";
  return (
    <Tag className={`item ${selected ? "selected" : ""} ${flag ? "flag" : ""}`} onClick={onClick} aria-label={it.label}>
      {index !== undefined && <span className="slot">{index + 1}</span>}
      <span className="emoji" aria-hidden>{it.emoji}</span>
      <span className="label">{it.label}</span>
    </Tag>
  );
}

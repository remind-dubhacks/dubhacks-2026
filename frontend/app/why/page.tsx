import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Why ReMind",
  description: "The care-home problem ReMind is built for, with sources.",
};

// Figures and sources: docs/USE_CASE.md. Keep both in sync.
const STATS: { big: string; what: string; source: string; href: string }[] = [
  { big: "55M+", what: "people live with dementia worldwide, heading for 139 million by 2050", source: "WHO (2021)", href: "https://www.paho.org/en/news/2-9-2021-world-failing-address-dementia-challenge" },
  { big: "41%", what: "of US nursing home residents live with Alzheimer's or another dementia", source: "CDC FastStats (2022)", href: "https://www.cdc.gov/nchs/fastats/alzheimers.htm" },
  { big: "47.5%", what: "of the waking day, residents with dementia were observed doing nothing", source: "BMC Geriatrics (2024)", href: "https://link.springer.com/article/10.1186/s12877-024-05641-7" },
  { big: "99%", what: "of nursing homes have open jobs; 72% are still below pre-pandemic staffing", source: "AHCA (2024)", href: "https://ahcancal.org/News-and-Communications/Press-Releases/Pages/State-Of-The-Sector-Nursing-Home-Staffing-Shortages-Persist-Despite-Unprecedented-Efforts-To-Attract-More-Staff-.aspx" },
];

const card: React.CSSProperties = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 20 };

export default function Why() {
  return (
    <main style={{ maxWidth: 880, margin: "0 auto", padding: "32px 16px 64px", color: "var(--text)" }}>
      <p style={{ color: "var(--muted)", margin: 0 }}>ReMind · primary use case</p>
      <h1 style={{ fontSize: "clamp(28px, 5vw, 42px)", lineHeight: 1.15, margin: "8px 0 12px" }}>
        One nurse, a room of residents living with dementia, and not enough hands.
      </h1>
      <p style={{ fontSize: 19, color: "var(--muted)", maxWidth: 680 }}>
        ReMind lets a nurse start a warm, familiar activity for a resident in seconds and step away. A voice companion
        talks with them, a robot arm takes part in a real-object memory game, and the caregiver gets a text the moment
        something needs a person.
      </p>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12, margin: "28px 0" }}>
        {STATS.map((s) => (
          <div key={s.big} style={card}>
            <div style={{ fontSize: 36, fontWeight: 700, color: "var(--accent)" }}>{s.big}</div>
            <p style={{ margin: "6px 0 10px" }}>{s.what}</p>
            <a href={s.href} target="_blank" rel="noreferrer" style={{ color: "var(--muted)", fontSize: 14 }}>{s.source}</a>
          </div>
        ))}
      </section>

      <h2>A session</h2>
      <ol style={{ fontSize: 18, lineHeight: 1.6, paddingLeft: 22 }}>
        <li>The nurse opens the resident&apos;s profile and starts a session. ReMind already knows their name and favourite things (with consent).</li>
        <li>The companion chats and offers activities: famous faces, finishing a saying, everyday sounds, or <b>Remember the Order</b> with the robot arm.</li>
        <li>The arm mixes up three keyrings; the resident puts them back. The camera follows the table, so ReMind says &ldquo;yes, the black one goes on the left&rdquo;, offers a choice of two when they hesitate, and never says &ldquo;wrong&rdquo;.</li>
        <li>If the resident says something worrying, or the robot needs help, the caregiver gets a text straight away.</li>
        <li>Afterwards the nurse reads engagement notes, never a score.</li>
      </ol>

      <h2>Why a robot arm</h2>
      <ul style={{ fontSize: 18, lineHeight: 1.6, paddingLeft: 22 }}>
        <li><b>Real objects.</b> Cognitive Stimulation Therapy, recommended by <a href="https://www.nice.org.uk/guidance/ng97" target="_blank" rel="noreferrer">NICE NG97</a> for mild-to-moderate dementia, uses real, familiar objects. A screen can&apos;t be picked up.</li>
        <li><b>Someone has to move them.</b> Today that&apos;s staff time. The arm does it, so one nurse can run activities for several residents.</li>
        <li><b>Safe by design.</b> Every motion is clamped to safe joint limits, the arm pauses while a hand is on the table, and an emergency stop is always within reach.</li>
      </ul>

      <h2>Why this game suits people living with dementia</h2>
      <p style={{ fontSize: 18, lineHeight: 1.6 }}>
        It is built from established methods: errorless learning (support before an error can stick), spaced retrieval,
        and optional reminiscence. ReMind&apos;s combination of them has not been clinically evaluated; it supports
        engagement and is not a diagnostic or treatment tool.
      </p>

      <p style={{ marginTop: 32, display: "flex", gap: 16, flexWrap: "wrap" }}>
        <Link href="/patient">Patient screen</Link>
        <Link href="/nurse">Nurse screen</Link>
        <Link href="/studio">Robot Studio</Link>
      </p>
    </main>
  );
}

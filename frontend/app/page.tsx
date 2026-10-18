import Link from "next/link";

export default function Home() {
  return (
    <main>
      <h1>ReMind</h1>
      <p>A caregiver-supervised activity companion. It supports engagement; it is not a medical device.</p>
      <div className="grid2">
        <Link href="/caregiver" className="card">
          <h2>Caregiver</h2>
          <p className="small">Choose a profile, approve and supervise a session.</p>
        </Link>
        <Link href="/participant" className="card">
          <h2>Participant</h2>
          <p className="small">Opened from the caregiver screen once a session is approved.</p>
        </Link>
      </div>
    </main>
  );
}

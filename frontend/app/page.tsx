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
        <Link href="/voice" className="card">
          <h2>Voice agent (prototype)</h2>
          <p className="small">Just say “play the ordering game”. The AI calls tools to run it.</p>
        </Link>
        <Link href="/play" className="card">
          <h2>Play Reorder</h2>
          <p className="small">Resident game screen: the robot shuffles, you put things back in order.</p>
        </Link>
        <Link href="/dashboard" className="card">
          <h2>Dashboard</h2>
          <p className="small">Residents, live session and alerts for the care team.</p>
        </Link>
      </div>
    </main>
  );
}

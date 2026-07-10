import { useState, useEffect } from "react"

function App() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch("http://localhost:8000/api/statistics")
      .then(res => res.json())
      .then(data => {
        setStats(data)
        setLoading(false)
      })
      .catch(err => {
        setError("Could not connect to backend")
        setLoading(false)
      })
  }, [])

  if (loading) return <p>Loading...</p>
  if (error) return <p>{error}</p>

  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>UCI Nature — Statistics</h1>
      <div style={{ display: "flex", gap: "2rem", marginTop: "1rem" }}>
        <StatCard label="Total Detections" value={stats.total_detections} />
        <StatCard label="Species Found" value={stats.species_count} />
        <StatCard label="Camera Sites" value={stats.cameras_count} />
      </div>
    </div>
  )
}

function StatCard({ label, value }) {
  return (
    <div style={{ padding: "1rem", border: "1px solid #ccc", borderRadius: "8px", minWidth: "150px" }}>
      <div style={{ fontSize: "2rem", fontWeight: "bold" }}>{value ?? "—"}</div>
      <div style={{ color: "#666", marginTop: "0.5rem" }}>{label}</div>
    </div>
  )
}

export default App
import { useState, useEffect } from 'react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Cell
} from 'recharts'

const COLORS = {
  calc: '#7c6af7',
  auth: '#4ade80',
  api: '#f87171',
  parser: '#facc15',
  pipeline: '#60a5fa',
}

const SERVICE_LABELS = {
  calc: 'calc — operator bug',
  auth: 'auth — off-by-one',
  api:  'api  — missing await',
  parser: 'parser — wrong key',
  pipeline: 'pipeline — bad slice',
}

function Badge({ ok }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 12,
      fontWeight: 600,
      background: ok ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)',
      color: ok ? '#4ade80' : '#f87171',
    }}>
      {ok ? '✓ pass' : '✗ fail'}
    </span>
  )
}

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{
      background: 'var(--bg2)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: '20px 24px',
      flex: 1,
      minWidth: 140,
    }}>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1 }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 700, color: color || 'var(--text-h)', marginTop: 4, fontFamily: 'var(--mono)' }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <h2 style={{
      fontSize: 16,
      fontWeight: 600,
      color: 'var(--text-h)',
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}>
      {children}
    </h2>
  )
}

const SAMPLE_DATA = {
  runs: [
    { service: 'calc',     roi: 0.446, tokens: 3500, file_reads: 8,  dup_reads: 4, waste: 4, target_pass: true,  suite_pass: false, wall_time: 128.5, file: 'calc_run1' },
    { service: 'calc',     roi: 0.550, tokens: 1915, file_reads: 3,  dup_reads: 1, waste: 2, target_pass: true,  suite_pass: true,  wall_time: 101.9, file: 'calc_run2' },
    { service: 'auth',     roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0,     file: 'pending' },
    { service: 'api',      roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0,     file: 'pending' },
    { service: 'parser',   roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0,     file: 'pending' },
    { service: 'pipeline', roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0,     file: 'pending' },
  ],
}

export default function App() {
  const [data, setData] = useState(null)
  const [selectedRun, setSelectedRun] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/summary.json')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setData(SAMPLE_DATA); setLoading(false) })
  }, [])

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-dim)', fontSize: 18 }}>
        Loading...
      </div>
    )
  }

  const runs = data?.runs || []
  const services = [...new Set(runs.map(r => r.service))]

  // Build trend data per service (run1 vs run2)
  const trendData = services.map(svc => {
    const svcRuns = runs.filter(r => r.service === svc)
    return {
      service: svc,
      run1_roi: svcRuns[0]?.roi ?? 0,
      run2_roi: svcRuns[1]?.roi ?? null,
      run1_tokens: svcRuns[0]?.tokens ?? 0,
      run2_tokens: svcRuns[1]?.tokens ?? null,
      run1_waste: svcRuns[0]?.waste ?? 0,
      run2_waste: svcRuns[1]?.waste ?? null,
    }
  })

  const completedRuns = runs.filter(r => r.tokens > 0)
  const avgRoi1 = completedRuns.filter((_, i) => i % 2 === 0).reduce((s, r) => s + r.roi, 0) / (completedRuns.filter((_, i) => i % 2 === 0).length || 1)
  const avgRoi2 = completedRuns.filter((_, i) => i % 2 === 1).reduce((s, r) => s + r.roi, 0) / (completedRuns.filter((_, i) => i % 2 === 1).length || 1)
  const totalTokens = completedRuns.reduce((s, r) => s + r.tokens, 0)
  const totalWaste = completedRuns.reduce((s, r) => s + r.waste, 0)

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    return (
      <div style={{ background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 13 }}>
        <div style={{ fontWeight: 600, color: 'var(--text-h)', marginBottom: 6 }}>{SERVICE_LABELS[label] || label}</div>
        {payload.map(p => (
          <div key={p.name} style={{ color: p.color }}>
            {p.name}: <strong>{typeof p.value === 'number' ? p.value.toFixed ? p.value.toFixed(3) : p.value : '—'}</strong>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 24px' }}>
      {/* Header */}
      <div style={{ marginBottom: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <span style={{ fontSize: 28, fontWeight: 800, color: 'var(--text-h)', fontFamily: 'var(--mono)' }}>AgentROI</span>
          <span style={{
            background: 'rgba(124,106,247,0.15)',
            color: 'var(--accent)',
            border: '1px solid rgba(124,106,247,0.3)',
            borderRadius: 6,
            padding: '2px 10px',
            fontSize: 12,
            fontWeight: 600,
          }}>DEMO</span>
        </div>
        <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>
          Self-improving agent swarm profiler — each run learns from the last
        </p>
      </div>

      {/* Hero stats */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 40 }}>
        <StatCard label="Runs completed" value={completedRuns.length} sub={`of ${runs.length} total`} />
        <StatCard label="Avg ROI Run 1" value={avgRoi1.toFixed(3)} color="var(--accent)" />
        <StatCard label="Avg ROI Run 2" value={avgRoi2 > 0 ? avgRoi2.toFixed(3) : '—'} color="var(--accent2)" sub={avgRoi2 > 0 ? `+${((avgRoi2 - avgRoi1) / (avgRoi1 || 1) * 100).toFixed(0)}% improvement` : 'pending'} />
        <StatCard label="Total tokens" value={totalTokens.toLocaleString()} sub="across all runs" />
        <StatCard label="Waste events" value={totalWaste} sub="detected & stored" />
      </div>

      {/* ROI Trend Chart */}
      <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 12, padding: 24, marginBottom: 24 }}>
        <SectionTitle>📈 ROI: Run 1 → Run 2 (per bug)</SectionTitle>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={trendData} barCategoryGap="30%">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="service" tick={{ fill: 'var(--text-dim)', fontSize: 12 }} />
            <YAxis domain={[0, 1]} tick={{ fill: 'var(--text-dim)', fontSize: 12 }} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 13 }} />
            <Bar dataKey="run1_roi" name="Run 1 (baseline)" fill="#6b7194" radius={[4,4,0,0]} />
            <Bar dataKey="run2_roi" name="Run 2 (memory-loaded)" fill="var(--accent)" radius={[4,4,0,0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Token Cost Chart */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
        <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 12, padding: 24 }}>
          <SectionTitle>💰 Token Cost: Run 1 → Run 2</SectionTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={trendData} barCategoryGap="30%">
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="service" tick={{ fill: 'var(--text-dim)', fontSize: 11 }} />
              <YAxis tick={{ fill: 'var(--text-dim)', fontSize: 11 }} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_tokens" name="Run 1 tokens" fill="#6b7194" radius={[4,4,0,0]} />
              <Bar dataKey="run2_tokens" name="Run 2 tokens" fill="var(--accent2)" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 12, padding: 24 }}>
          <SectionTitle>🗑️ Waste Events: Run 1 → Run 2</SectionTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={trendData} barCategoryGap="30%">
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="service" tick={{ fill: 'var(--text-dim)', fontSize: 11 }} />
              <YAxis tick={{ fill: 'var(--text-dim)', fontSize: 11 }} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_waste" name="Run 1 waste" fill="#f87171" radius={[4,4,0,0]} />
              <Bar dataKey="run2_waste" name="Run 2 waste" fill="var(--accent2)" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Run table */}
      <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 12, padding: 24, marginBottom: 24 }}>
        <SectionTitle>📋 All Runs</SectionTitle>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Bug', 'Run', 'ROI', 'Tokens', 'Reads', 'Dups', 'Waste', 'Wall(s)', 'Target', 'Suite'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: 'var(--text-dim)', fontWeight: 500 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((r, i) => {
              const isPending = r.tokens === 0
              const runNum = runs.filter(x => x.service === r.service).indexOf(r) + 1
              const roi = r.roi
              const roiColor = roi >= 0.6 ? 'var(--accent2)' : roi >= 0.35 ? 'var(--accent4)' : 'var(--accent3)'
              return (
                <tr
                  key={i}
                  onClick={() => !isPending && setSelectedRun(selectedRun === i ? null : i)}
                  style={{
                    borderBottom: '1px solid var(--border)',
                    cursor: isPending ? 'default' : 'pointer',
                    opacity: isPending ? 0.4 : 1,
                    background: selectedRun === i ? 'var(--bg3)' : 'transparent',
                    transition: 'background 0.15s',
                  }}
                >
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: COLORS[r.service] }}>
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: COLORS[r.service], marginRight: 8 }} />
                    {r.service}
                  </td>
                  <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>#{runNum}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)', fontWeight: 700, color: isPending ? 'var(--text-dim)' : roiColor }}>
                    {isPending ? '—' : roi.toFixed(3)}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)' }}>{isPending ? '—' : r.tokens.toLocaleString()}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)' }}>{isPending ? '—' : r.file_reads}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)', color: r.dup_reads > 2 ? 'var(--accent3)' : 'var(--text)' }}>{isPending ? '—' : r.dup_reads}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)', color: r.waste > 3 ? 'var(--accent3)' : 'var(--text)' }}>{isPending ? '—' : r.waste}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)' }}>{isPending ? '—' : r.wall_time.toFixed(0)}</td>
                  <td style={{ padding: '10px 12px' }}>{isPending ? '—' : <Badge ok={r.target_pass} />}</td>
                  <td style={{ padding: '10px 12px' }}>{isPending ? '—' : <Badge ok={r.suite_pass} />}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 12, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        AgentROI — self-improving agent swarm profiler · Run <code style={{ fontFamily: 'var(--mono)', background: 'var(--bg3)', padding: '1px 6px', borderRadius: 4 }}>demo/run_all.sh</code> to populate with live data
      </div>
    </div>
  )
}

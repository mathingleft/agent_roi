import { useState, useEffect } from 'react'
import Generalization from './Generalization.jsx'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, LineChart, Line, ReferenceLine
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
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      fontSize: 12, fontWeight: 600,
      background: ok ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)',
      color: ok ? '#4ade80' : '#f87171',
    }}>
      {ok ? '✓ pass' : '✗ fail'}
    </span>
  )
}

function StatCard({ label, v1, v2, sub, color, delta }) {
  return (
    <div style={{
      background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 12, padding: '16px 20px', flex: 1, minWidth: 130,
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>{label}</div>
      {v2 != null ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-dim)', fontFamily: 'var(--mono)', lineHeight: 1 }}>{v1}</div>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', lineHeight: 1 }}>↓</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: color || 'var(--text-h)', fontFamily: 'var(--mono)', lineHeight: 1 }}>{v2}</div>
        </div>
      ) : (
        <div style={{ fontSize: 26, fontWeight: 700, color: color || 'var(--text-h)', fontFamily: 'var(--mono)' }}>{v1}</div>
      )}
      {delta != null && (
        <div style={{ fontSize: 11, fontWeight: 600, marginTop: 6,
          color: delta <= 0 && label.toLowerCase().includes('roi') ? '#f87171'
               : delta >= 0 && label.toLowerCase().includes('roi') ? '#4ade80'
               : delta <= 0 ? '#4ade80' : '#f87171'
        }}>
          {delta > 0 ? '▲' : '▼'} {Math.abs(delta)}%
        </div>
      )}
      {sub && <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <h2 style={{
      fontSize: 15, fontWeight: 600, color: 'var(--text-h)',
      marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8,
    }}>
      {children}
    </h2>
  )
}

function ChartCard({ title, children, style }) {
  return (
    <div style={{
      background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 12, padding: 24, ...style,
    }}>
      <SectionTitle>{title}</SectionTitle>
      {children}
    </div>
  )
}

const SAMPLE_DATA = {
  runs: [
    { service: 'calc',     roi: 0.446, tokens: 3500, file_reads: 8,  dup_reads: 4, waste: 4, target_pass: true,  suite_pass: false, wall_time: 128.5 },
    { service: 'calc',     roi: 0.550, tokens: 1915, file_reads: 3,  dup_reads: 1, waste: 2, target_pass: true,  suite_pass: true,  wall_time: 94.2  },
    { service: 'auth',     roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
    { service: 'auth',     roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
    { service: 'api',      roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
    { service: 'api',      roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
    { service: 'parser',   roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
    { service: 'parser',   roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
    { service: 'pipeline', roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
    { service: 'pipeline', roi: 0.0,   tokens: 0,    file_reads: 0,  dup_reads: 0, waste: 0, target_pass: false, suite_pass: false, wall_time: 0 },
  ],
}

const CustomTooltip = ({ active, payload, label, fmt }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 13 }}>
      <div style={{ fontWeight: 600, color: 'var(--text-h)', marginBottom: 6 }}>{SERVICE_LABELS[label] || label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color, lineHeight: '22px' }}>
          {p.name}: <strong>{p.value == null ? '—' : (fmt ? fmt(p.value) : p.value)}</strong>
        </div>
      ))}
    </div>
  )
}

function pct(a, b) {
  if (!a || !b) return null
  return Math.round(((b - a) / a) * 100)
}

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedRun, setSelectedRun] = useState(null)
  const [tab, setTab] = useState('generalization')

  useEffect(() => {
    fetch('/summary.json')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setData(SAMPLE_DATA); setLoading(false) })
  }, [])

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-dim)', fontSize: 18 }}>Loading...</div>
  }

  const runs = data?.runs || []
  const services = [...new Set(runs.map(r => r.service))]

  const completedRuns = runs.filter(r => r.tokens > 0)

  const trendData = services.map(svc => {
    const svcRuns = runs.filter(r => r.service === svc)
    const r1 = svcRuns[0], r2 = svcRuns[1]
    const r1ok = r1?.tokens > 0, r2ok = r2?.tokens > 0
    return {
      service: svc,
      run1_roi:      r1ok ? (r1?.roi       ?? 0)    : 0,
      run2_roi:      r2ok ? (r2?.roi       ?? null)  : null,
      run1_tokens:   r1ok ? (r1?.tokens    ?? 0)    : 0,
      run2_tokens:   r2ok ? (r2?.tokens    ?? null)  : null,
      run1_waste:    r1ok ? (r1?.waste     ?? 0)    : 0,
      run2_waste:    r2ok ? (r2?.waste     ?? null)  : null,
      run1_wall:     r1ok ? (r1?.wall_time ?? 0)    : 0,
      run2_wall:     r2ok ? (r2?.wall_time ?? null)  : null,
      run1_reads:    r1ok ? (r1?.file_reads ?? 0)   : 0,
      run2_reads:    r2ok ? (r2?.file_reads ?? null) : null,
      run1_dups:     r1ok ? (r1?.dup_reads  ?? 0)   : 0,
      run2_dups:     r2ok ? (r2?.dup_reads  ?? null) : null,
    }
  })

  // Averages derived from trendData so pairing is always correct per service
  const paired = trendData.filter(d => d.run1_tokens > 0)
  const hasPairs = paired.some(d => d.run2_roi != null)
  const avg1 = key => paired.length ? paired.reduce((s, d) => s + (d[key] ?? 0), 0) / paired.length : 0
  const avg2 = key => {
    const valid = paired.filter(d => d[key] != null)
    return valid.length ? valid.reduce((s, d) => s + d[key], 0) / valid.length : 0
  }

  const avgRoi1  = avg1('run1_roi');   const avgRoi2  = avg2('run2_roi')
  const avgWall1 = avg1('run1_wall');  const avgWall2 = avg2('run2_wall')
  const avgTok1  = avg1('run1_tokens');const avgTok2  = avg2('run2_tokens')
  const avgDups1 = avg1('run1_dups');  const avgDups2 = avg2('run2_dups')
  const avgReads1= avg1('run1_reads'); const avgReads2= avg2('run2_reads')
  const totalWaste = completedRuns.reduce((s, r) => s + r.waste, 0)

  const roiDelta   = hasPairs ? pct(avgRoi1, avgRoi2)   : null
  const wallDelta  = hasPairs ? pct(avgWall1, avgWall2)  : null
  const tokDelta   = hasPairs ? pct(avgTok1, avgTok2)    : null
  const dupsDelta  = hasPairs ? pct(avgDups1, avgDups2)  : null
  const readsDelta = hasPairs ? pct(avgReads1, avgReads2): null

  const axisStyle = { fill: 'var(--text-dim)', fontSize: 11 }
  const gridStyle = { strokeDasharray: '3 3', stroke: 'var(--border)' }

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: '32px 24px' }}>

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <span style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-h)', fontFamily: 'var(--mono)' }}>AgentROI</span>
          <span style={{ background: 'rgba(124,106,247,0.15)', color: 'var(--accent)', border: '1px solid rgba(124,106,247,0.3)', borderRadius: 6, padding: '2px 10px', fontSize: 11, fontWeight: 600 }}>DEMO</span>
        </div>
        <p style={{ color: 'var(--text-dim)', fontSize: 13, marginBottom: 16 }}>
          Self-improving agent swarm — memory from Run 1 makes Run 2 faster, cheaper, and smarter
        </p>


        {/* Benchmark sourcing callout */}
        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--border)',
          borderLeft: '3px solid var(--accent)', borderRadius: 8,
          padding: '12px 16px', fontSize: 12, color: 'var(--text-dim)',
          display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start',
          marginBottom: 8,
        }}>
          <div style={{ flex: 2, minWidth: 260 }}>
            <span style={{ color: 'var(--text-h)', fontWeight: 600 }}>Benchmark: HumanEvalFix</span>
            {' '}— problems sourced from{' '}
            <a href="https://huggingface.co/datasets/bigcode/humanevalpack" target="_blank"
              style={{ color: 'var(--accent)', textDecoration: 'none' }}>
              bigcode/humanevalpack
            </a>
            {' '}(OctoPack, Muennighoff et al. 2023). 9 Python bug-fix instances manually
            selected and categorized into two generalization tiers.
          </div>
          <div style={{ flex: 3, minWidth: 300, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {[
              { tier: 'Tier 1', label: 'Same-domain', desc: 'op_get_positive → op_rescale → op_fizzbuzz — all operator misuse, memory transfers across different bugs', color: '#4ade80' },
              { tier: 'Tier 2', label: 'Cross-domain', desc: 'val_* (value misuse) → var_rolling_max (variable misuse) — strategies generalize across unrelated bug categories', color: '#facc15' },
            ].map(({ tier, label, desc, color }) => (
              <div key={tier} style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                <span style={{ background: color + '22', color, border: `1px solid ${color}55`,
                  borderRadius: 4, padding: '1px 6px', fontSize: 10, fontWeight: 700,
                  whiteSpace: 'nowrap', marginTop: 1 }}>{tier}</span>
                <span><strong style={{ color: 'var(--text-h)' }}>{label}</strong> — {desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {tab === 'generalization' && <Generalization />}
      {tab !== 'generalization' && <div style={{display:'none'}}></div>}
      {tab !== 'generalization' && <>

      {/* Hero stats */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 32 }}>
        <StatCard label="ROI"
          v1={avgRoi1.toFixed(3)} v2={hasPairs ? avgRoi2.toFixed(3) : null}
          color="var(--accent)" delta={roiDelta} />
        <StatCard label="Wall Time"
          v1={`${avgWall1.toFixed(0)}s`} v2={hasPairs ? `${avgWall2.toFixed(0)}s` : null}
          color="var(--accent4)" delta={wallDelta} />
        <StatCard label="Tokens"
          v1={Math.round(avgTok1).toLocaleString()} v2={hasPairs ? Math.round(avgTok2).toLocaleString() : null}
          color="var(--accent2)" delta={tokDelta} />
        <StatCard label="File Reads"
          v1={avgReads1.toFixed(1)} v2={hasPairs ? avgReads2.toFixed(1) : null}
          color="#60a5fa" delta={readsDelta} />
        <StatCard label="Dup Reads"
          v1={avgDups1.toFixed(1)} v2={hasPairs ? avgDups2.toFixed(1) : null}
          color="#f87171" delta={dupsDelta} />
        <StatCard label="Waste" v1={totalWaste} sub="events detected" />
        <StatCard label="Runs" v1={`${completedRuns.length}/${runs.length}`} sub="complete" />
      </div>

      {/* ROI + Wall time row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
        <ChartCard title="📈 ROI Score: Run 1 → Run 2">
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={trendData} barCategoryGap="28%">
              <CartesianGrid {...gridStyle} />
              <XAxis dataKey="service" tick={axisStyle} />
              <YAxis domain={[0, 1]} tick={axisStyle} tickFormatter={v => v.toFixed(1)} />
              <Tooltip content={<CustomTooltip fmt={v => v.toFixed(3)} />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_roi" name="Run 1 (baseline)" fill="#4b5270" radius={[4,4,0,0]} />
              <Bar dataKey="run2_roi" name="Run 2 (memory)" fill="var(--accent)" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="⏱ Wall-Clock Time (seconds): Run 1 → Run 2">
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={trendData} barCategoryGap="28%">
              <CartesianGrid {...gridStyle} />
              <XAxis dataKey="service" tick={axisStyle} />
              <YAxis tick={axisStyle} unit="s" />
              <Tooltip content={<CustomTooltip fmt={v => `${v.toFixed(0)}s`} />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_wall" name="Run 1 (s)" fill="#4b5270" radius={[4,4,0,0]} />
              <Bar dataKey="run2_wall" name="Run 2 (s)" fill="var(--accent4)" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* Tokens + Waste row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
        <ChartCard title="💰 Token Cost: Run 1 → Run 2">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={trendData} barCategoryGap="28%">
              <CartesianGrid {...gridStyle} />
              <XAxis dataKey="service" tick={axisStyle} />
              <YAxis tick={axisStyle} />
              <Tooltip content={<CustomTooltip fmt={v => v.toLocaleString()} />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_tokens" name="Run 1 tokens" fill="#4b5270" radius={[4,4,0,0]} />
              <Bar dataKey="run2_tokens" name="Run 2 tokens" fill="var(--accent2)" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="🗑️ Waste Events: Run 1 → Run 2">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={trendData} barCategoryGap="28%">
              <CartesianGrid {...gridStyle} />
              <XAxis dataKey="service" tick={axisStyle} />
              <YAxis tick={axisStyle} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_waste" name="Run 1 waste" fill="#f87171" radius={[4,4,0,0]} />
              <Bar dataKey="run2_waste" name="Run 2 waste" fill="var(--accent2)" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* File reads + Dup reads row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
        <ChartCard title="📂 File Reads: Run 1 → Run 2">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={trendData} barCategoryGap="28%">
              <CartesianGrid {...gridStyle} />
              <XAxis dataKey="service" tick={axisStyle} />
              <YAxis tick={axisStyle} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_reads" name="Run 1 reads" fill="#4b5270" radius={[4,4,0,0]} />
              <Bar dataKey="run2_reads" name="Run 2 reads" fill="#60a5fa" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="♻️ Duplicate Reads: Run 1 → Run 2">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={trendData} barCategoryGap="28%">
              <CartesianGrid {...gridStyle} />
              <XAxis dataKey="service" tick={axisStyle} />
              <YAxis tick={axisStyle} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ color: 'var(--text-dim)', fontSize: 12 }} />
              <Bar dataKey="run1_dups" name="Run 1 dup reads" fill="#f87171" radius={[4,4,0,0]} />
              <Bar dataKey="run2_dups" name="Run 2 dup reads" fill="var(--accent2)" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* Run table */}
      <ChartCard title="📋 All Runs" style={{ marginBottom: 20 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Bug', '#', 'ROI', 'Wall (s)', 'Tokens', 'Reads', 'Dups', 'Waste', 'Target', 'Suite'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: 'var(--text-dim)', fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((r, i) => {
              const isPending = r.tokens === 0
              const runNum = runs.filter(x => x.service === r.service).indexOf(r) + 1
              const roi = r.roi
              const roiColor = roi >= 0.6 ? '#4ade80' : roi >= 0.35 ? '#facc15' : '#f87171'
              const wallColor = r.wall_time < 100 ? '#4ade80' : r.wall_time < 150 ? '#facc15' : '#f87171'
              return (
                <tr key={i}
                  onClick={() => !isPending && setSelectedRun(selectedRun === i ? null : i)}
                  style={{
                    borderBottom: '1px solid var(--border)',
                    cursor: isPending ? 'default' : 'pointer',
                    opacity: isPending ? 0.35 : 1,
                    background: selectedRun === i ? 'var(--bg3)' : 'transparent',
                    transition: 'background 0.15s',
                  }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: COLORS[r.service] }}>
                    <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: COLORS[r.service], marginRight: 8 }} />
                    {r.service}
                  </td>
                  <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>#{runNum}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)', fontWeight: 700, color: isPending ? 'var(--text-dim)' : roiColor }}>
                    {isPending ? '—' : roi.toFixed(3)}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)', color: isPending ? 'var(--text-dim)' : wallColor, fontWeight: 600 }}>
                    {isPending ? '—' : `${r.wall_time.toFixed(0)}s`}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)' }}>{isPending ? '—' : r.tokens.toLocaleString()}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)' }}>{isPending ? '—' : r.file_reads}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)', color: r.dup_reads > 2 ? '#f87171' : 'var(--text)' }}>{isPending ? '—' : r.dup_reads}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--mono)', color: r.waste > 3 ? '#f87171' : 'var(--text)' }}>{isPending ? '—' : r.waste}</td>
                  <td style={{ padding: '10px 12px' }}>{isPending ? '—' : <Badge ok={r.target_pass} />}</td>
                  <td style={{ padding: '10px 12px' }}>{isPending ? '—' : <Badge ok={r.suite_pass} />}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </ChartCard>

      {/* Footer */}
      <div style={{ color: 'var(--text-dim)', fontSize: 11, paddingTop: 16, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <span>
          AgentROI · Run{' '}
          <code style={{ fontFamily: 'var(--mono)', background: 'var(--bg3)', padding: '1px 6px', borderRadius: 4 }}>demo/run_humaneval.sh</code>
          {' '}to populate with live data
        </span>
        <span>
          Benchmark problems from{' '}
          <a href="https://huggingface.co/datasets/bigcode/humanevalpack" target="_blank"
            style={{ color: 'var(--accent)', textDecoration: 'none' }}>bigcode/humanevalpack</a>
          {' '}·{' '}
          <a href="https://arxiv.org/abs/2308.07124" target="_blank"
            style={{ color: 'var(--accent)', textDecoration: 'none' }}>OctoPack paper (arXiv:2308.07124)</a>
        </span>
      </div>
      </>}
    </div>
  )
}

import { useState, useEffect } from 'react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine, Cell
} from 'recharts'

const axisStyle = { fill: 'var(--text-dim)', fontSize: 11 }
const gridStyle = { strokeDasharray: '3 3', stroke: 'var(--border)' }

function ChartCard({ title, children, style }) {
  return (
    <div style={{
      background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 12, padding: '20px 24px', ...style
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-h)', marginBottom: 16 }}>{title}</div>
      {children}
    </div>
  )
}

function NoData({ label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: 180, color: 'var(--text-dim)', fontSize: 13, flexDirection: 'column', gap: 8 }}>
      <span style={{ fontSize: 28 }}>⏳</span>
      <span>Waiting for {label} results…</span>
      <span style={{ fontSize: 11 }}>Run <code style={{ background: 'var(--bg3)', padding: '1px 6px', borderRadius: 4 }}>demo/run_humaneval.sh</code></span>
    </div>
  )
}

// ── Tier 1: learning curves per problem ────────────────────────────
function Tier1Chart({ runs }) {
  // Group by service, then by trajectory prefix (t1a/t1b/t1c)
  // Each chain: run1 → run2 → run3 for the same problem
  const chains = {}
  for (const r of runs) {
    if (!r.trajectory?.startsWith('t1')) continue
    const svc = r.service
    if (!chains[svc]) chains[svc] = []
    chains[svc].push(r)
  }

  const CHAIN_COLORS = ['#7c6af7', '#4ade80', '#facc15']
  const svcs = Object.keys(chains)

  if (!svcs.length) return <NoData label="Tier 1" />

  // Build one line per service: x = run index (1,2,3)
  const maxRuns = Math.max(...svcs.map(s => chains[s].length))
  const data = Array.from({ length: maxRuns }, (_, i) => {
    const pt = { run: `Run ${i + 1}` }
    for (const svc of svcs) pt[svc] = chains[svc][i]?.roi ?? null
    return pt
  })

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data}>
        <CartesianGrid {...gridStyle} />
        <XAxis dataKey="run" tick={axisStyle} />
        <YAxis domain={[0, 1]} tick={axisStyle} tickFormatter={v => v.toFixed(2)} />
        <Tooltip contentStyle={{ background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8 }}
          formatter={(v, name) => [v?.toFixed(3) ?? '—', name]} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {svcs.map((svc, i) => (
          <Line key={svc} type="monotone" dataKey={svc} stroke={CHAIN_COLORS[i % CHAIN_COLORS.length]}
            strokeWidth={2} dot={{ r: 4 }} connectNulls />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

// ── Tier 2: run1 vs run2 per bug, sequential domain chain ──────────
function Tier2Chart({ runs, metric = 'roi' }) {
  const t2runs = runs.filter(r => r.trajectory?.startsWith('t2'))
  if (!t2runs.length) return <NoData label="Tier 2" />

  // Group by service, pick run1 and run2
  const byService = {}
  for (const r of t2runs) {
    if (!byService[r.service]) byService[r.service] = []
    byService[r.service].push(r)
  }

  // Order by first appearance (reflects sequential order in the experiment)
  const ORDER = ['op_get_positive', 'op_rescale', 'op_solve', 'op_fizzbuzz']
  const svcs = ORDER.filter(s => byService[s])

  const data = svcs.map((svc, i) => {
    const sorted = byService[svc].slice().sort((a, b) => a.trajectory.localeCompare(b.trajectory))
    return {
      bug: svc.replace('op_', '').replace('_', ' '),
      order: i + 1,
      run1: sorted[0]?.[metric] ?? null,
      run2: sorted[1]?.[metric] ?? null,
    }
  })

  const label = metric === 'roi' ? 'ROI Score' : metric === 'tokens' ? 'Tokens' : metric
  const domain = metric === 'roi' ? [0, 1] : [0, 'auto']
  const fmt = metric === 'roi' ? v => v?.toFixed(3) : v => v

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} barCategoryGap="30%">
        <CartesianGrid {...gridStyle} />
        <XAxis dataKey="bug" tick={axisStyle} />
        <YAxis domain={domain} tick={axisStyle} tickFormatter={metric === 'roi' ? v => v.toFixed(1) : undefined} />
        <Tooltip contentStyle={{ background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8 }}
          formatter={(v, name) => [fmt(v), name]} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="run1" name="Run 1 (baseline)" fill="#4a4a6a" radius={[3,3,0,0]} />
        <Bar dataKey="run2" name="Run 2 (memory)" fill="#7c6af7" radius={[3,3,0,0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── Tier 3: cross-domain, value→variable boundary ──────────────────
function Tier3Chart({ runs, metric = 'roi' }) {
  const t3runs = runs.filter(r => r.trajectory?.startsWith('t3'))
  if (!t3runs.length) return <NoData label="Tier 3" />

  const byService = {}
  for (const r of t3runs) {
    if (!byService[r.service]) byService[r.service] = []
    byService[r.service].push(r)
  }

  const VALUE_ORDER = ['val_incr_list', 'val_triangle', 'val_sum_to_n']
  const VAR_ORDER   = ['var_gcd', 'var_rolling_max', 'var_decode']
  const ORDER = [...VALUE_ORDER, ...VAR_ORDER]
  const svcs = ORDER.filter(s => byService[s])

  const data = svcs.map(svc => {
    const sorted = byService[svc].slice().sort((a, b) => a.trajectory.localeCompare(b.trajectory))
    const domain = VALUE_ORDER.includes(svc) ? 'value' : 'variable'
    return {
      bug: svc.replace(/val_|var_/, '').replace(/_/g, ' '),
      domain,
      run1: sorted[0]?.[metric] ?? null,
      run2: sorted[1]?.[metric] ?? null,
    }
  })

  const boundaryIdx = data.findIndex(d => d.domain === 'variable')
  const fmt = metric === 'roi' ? v => v?.toFixed(3) : v => v

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} barCategoryGap="30%">
        <CartesianGrid {...gridStyle} />
        <XAxis dataKey="bug" tick={axisStyle} />
        <YAxis domain={metric === 'roi' ? [0, 1] : [0, 'auto']} tick={axisStyle}
          tickFormatter={metric === 'roi' ? v => v.toFixed(1) : undefined} />
        <Tooltip contentStyle={{ background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8 }}
          formatter={(v, name) => [fmt(v), name]} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {boundaryIdx > 0 && (
          <ReferenceLine x={data[boundaryIdx]?.bug} stroke="#f87171" strokeDasharray="4 2"
            label={{ value: '← value | variable →', position: 'insideTopRight', fill: '#f87171', fontSize: 10 }} />
        )}
        <Bar dataKey="run1" name="Run 1 (baseline)" radius={[3,3,0,0]}>
          {data.map((d, i) => <Cell key={i} fill={d.domain === 'value' ? '#3b5a4a' : '#3b3a5a'} />)}
        </Bar>
        <Bar dataKey="run2" name="Run 2 (memory)" radius={[3,3,0,0]}>
          {data.map((d, i) => <Cell key={i} fill={d.domain === 'value' ? '#4ade80' : '#7c6af7'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── Summary stat strip ──────────────────────────────────────────────
function TierStat({ label, value, sub, color }) {
  return (
    <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 10, padding: '12px 18px', flex: 1, minWidth: 120 }}>
      <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color || 'var(--text-h)', fontFamily: 'var(--mono)', marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

// ── Main export ─────────────────────────────────────────────────────
export default function Generalization() {
  const [data, setData] = useState(null)
  const [metric, setMetric] = useState('roi')

  useEffect(() => {
    fetch('/summary_humaneval.json')
      .then(r => r.ok ? r.json() : null)
      .catch(() => null)
      .then(setData)
    const iv = setInterval(() => {
      fetch('/summary_humaneval.json')
        .then(r => r.ok ? r.json() : null)
        .catch(() => null)
        .then(setData)
    }, 15000)
    return () => clearInterval(iv)
  }, [])

  const runs = data?.runs ?? []
  const t1runs = runs.filter(r => r.trajectory?.startsWith('t1'))
  const t2runs = runs.filter(r => r.trajectory?.startsWith('t2'))
  const t3runs = runs.filter(r => r.trajectory?.startsWith('t3'))

  // Aggregate improvement per tier
  const avgDelta = (tierRuns) => {
    const byService = {}
    for (const r of tierRuns) {
      if (!byService[r.service]) byService[r.service] = []
      byService[r.service].push(r)
    }
    const deltas = Object.values(byService)
      .filter(arr => arr.length >= 2)
      .map(arr => {
        const sorted = arr.slice().sort((a,b) => a.trajectory.localeCompare(b.trajectory))
        return sorted[sorted.length-1].roi - sorted[0].roi
      })
    if (!deltas.length) return null
    return (deltas.reduce((a,b) => a+b, 0) / deltas.length)
  }

  const t1delta = avgDelta(t1runs)
  const t2delta = avgDelta(t2runs)
  const t3delta = avgDelta(t3runs)

  const METRICS = [
    { key: 'roi', label: 'ROI Score' },
    { key: 'tokens', label: 'Tokens' },
    { key: 'wall_time', label: 'Wall Time (s)' },
  ]

  return (
    <div>
      {/* Tier stat strip */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        <TierStat label="Tier 1 avg Δ ROI" color="#7c6af7"
          value={t1delta != null ? (t1delta >= 0 ? '+' : '') + t1delta.toFixed(3) : '—'}
          sub="same-bug repeat" />
        <TierStat label="Tier 2 avg Δ ROI" color="#4ade80"
          value={t2delta != null ? (t2delta >= 0 ? '+' : '') + t2delta.toFixed(3) : '—'}
          sub="same-domain transfer" />
        <TierStat label="Tier 3 avg Δ ROI" color="#facc15"
          value={t3delta != null ? (t3delta >= 0 ? '+' : '') + t3delta.toFixed(3) : '—'}
          sub="cross-domain transfer" />
        <TierStat label="Total runs" color="var(--text-h)"
          value={runs.length} sub={`${t1runs.length} / ${t2runs.length} / ${t3runs.length} per tier`} />
      </div>

      {/* Metric selector */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {METRICS.map(m => (
          <button key={m.key} onClick={() => setMetric(m.key)} style={{
            padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer',
            border: '1px solid var(--border)',
            background: metric === m.key ? 'var(--accent)' : 'var(--bg2)',
            color: metric === m.key ? '#fff' : 'var(--text-dim)',
          }}>{m.label}</button>
        ))}
      </div>

      {/* Three tier charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
        <ChartCard title="🔁 Tier 1 — Same-bug repeat: ROI per run">
          <Tier1Chart runs={t1runs} />
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
            3 problems × 3 runs each (parallel chains, own memory). Claim: ROI improves with each identical rerun.
          </div>
        </ChartCard>

        <ChartCard title="🎯 Tier 2 — Same-domain transfer: operator misuse chain">
          <Tier2Chart runs={t2runs} metric={metric} />
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
            4 operator bugs run sequentially, shared memory. Claim: run2 improvement grows as domain memory accumulates.
          </div>
        </ChartCard>
      </div>

      <ChartCard title="🌐 Tier 3 — Cross-domain transfer: value misuse → variable misuse">
        <Tier3Chart runs={t3runs} metric={metric} />
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
          3 value-misuse bugs → 3 variable-misuse bugs, shared memory throughout. Red line = domain boundary.
          Claim: strategies learned fixing value bugs (wrong constants) generalize to variable bugs (wrong variable references).
        </div>
      </ChartCard>
    </div>
  )
}

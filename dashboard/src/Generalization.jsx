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
  // Group by chain prefix (t1a/t1b/t1c) — each is a distinct problem repeated 3×
  const chains = {}
  const chainLabel = {}
  for (const r of runs) {
    const m = r.trajectory?.match(/^(t1[abc])/)
    if (!m) continue
    const chain = m[1]
    if (!chains[chain]) { chains[chain] = []; chainLabel[chain] = r.service }
    chains[chain].push(r)
  }

  const CHAIN_COLORS = { t1a: '#7c6af7', t1b: '#4ade80', t1c: '#facc15' }
  const chainKeys = Object.keys(chains).sort()

  if (!chainKeys.length) return <NoData label="Tier 1" />

  const maxRuns = Math.max(...chainKeys.map(c => chains[c].length))
  const data = Array.from({ length: maxRuns }, (_, i) => {
    const pt = { run: `Run ${i + 1}` }
    for (const c of chainKeys) {
      const sorted = chains[c].slice().sort((a, b) => a.trajectory.localeCompare(b.trajectory))
      pt[c] = sorted[i]?.roi ?? null
    }
    return pt
  })

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data}>
        <CartesianGrid {...gridStyle} />
        <XAxis dataKey="run" tick={axisStyle} />
        <YAxis domain={[0, 1]} tick={axisStyle} tickFormatter={v => v.toFixed(2)} />
        <Tooltip contentStyle={{ background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8 }}
          formatter={(v, name) => [v?.toFixed(3) ?? '—', chainLabel[name] ?? name]} />
        <Legend wrapperStyle={{ fontSize: 11 }} formatter={name => chainLabel[name] ?? name} />
        {chainKeys.map(c => (
          <Line key={c} type="monotone" dataKey={c} name={c}
            stroke={CHAIN_COLORS[c] ?? '#aaa'}
            strokeWidth={2} dot={{ r: 4 }} connectNulls />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

// ── Tier 2: run1 vs run2 per bug, sequential domain chain ──────────
function Tier2Chart({ runs, metric = 'roi' }) {
  const t2runs = runs.filter(r => r.trajectory?.startsWith('t1'))
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
  const domain = metric === 'roi' ? [0, 2] : [0, 'auto']
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
  const t3runs = runs.filter(r => r.trajectory?.startsWith('t2'))
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
        <YAxis domain={metric === 'roi' ? [0, 2] : [0, 'auto']} tick={axisStyle}
          tickFormatter={metric === 'roi' ? v => v.toFixed(1) : undefined} />
        <Tooltip contentStyle={{ background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8 }}
          formatter={(v, name) => [fmt(v), name]} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {boundaryIdx > 0 && (
          <ReferenceLine x={data[boundaryIdx]?.bug} stroke="#f87171" strokeDasharray="4 2" />
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
  const [lastUpdated, setLastUpdated] = useState(null)
  const [live, setLive] = useState(false)

  useEffect(() => {
    const load = () =>
      fetch('/summary_humaneval.json')
        .then(r => r.ok ? r.json() : null)
        .catch(() => null)
        .then(d => { if (d) { setData(d); setLastUpdated(new Date()); setLive(true) } })
    load()
    const iv = setInterval(load, 15000)
    return () => clearInterval(iv)
  }, [])

  const runs = data?.runs ?? []
  const t1runs = runs.filter(r => r.trajectory?.startsWith('t1'))
  const t2runs = runs.filter(r => r.trajectory?.startsWith('t2'))

  // T1 groups by chain prefix (t1a/t1b/t1c), T2/T3 group by service+trajectory
  const avgDeltaByChain = (tierRuns, chainPrefixFn) => {
    const chains = {}
    for (const r of tierRuns) {
      const key = chainPrefixFn(r)
      if (!chains[key]) chains[key] = []
      chains[key].push(r)
    }
    const deltas = Object.values(chains)
      .filter(arr => arr.length >= 2)
      .map(arr => {
        const sorted = arr.slice().sort((a,b) => a.trajectory.localeCompare(b.trajectory))
        return { roi: sorted[sorted.length-1].roi - sorted[0].roi,
                 tok: sorted[sorted.length-1].tokens - sorted[0].tokens }
      })
    if (!deltas.length) return null
    return {
      roi: deltas.reduce((a,b) => a + b.roi, 0) / deltas.length,
      tok: deltas.reduce((a,b) => a + b.tok, 0) / deltas.length,
    }
  }

  const t1delta = avgDeltaByChain(t1runs, r => r.service)
  const t2delta = avgDeltaByChain(t2runs, r => r.service)

  const METRICS = [
    { key: 'roi', label: 'ROI Score' },
    { key: 'tokens', label: 'Tokens' },
    { key: 'wall_time', label: 'Wall Time (s)' },
  ]

  return (
    <div>
      {/* Live indicator + last updated */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11,
          color: live ? '#4ade80' : 'var(--text-dim)' }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%',
            background: live ? '#4ade80' : '#555', display: 'inline-block',
            boxShadow: live ? '0 0 6px #4ade80' : 'none' }} />
          {live ? 'Live — auto-refreshes every 15s' : 'Waiting for data…'}
        </span>
        {lastUpdated && <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
          Last updated: {lastUpdated.toLocaleTimeString()}
        </span>}
        <span style={{ fontSize: 11, color: 'var(--text-dim)', marginLeft: 'auto' }}>
          {t1runs.length} T1 · {t2runs.length} T2 runs complete
        </span>
      </div>

      {/* Tier stat strip */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        <TierStat label="T1 avg Δ ROI" color="#4ade80"
          value={t1delta ? (t1delta.roi >= 0 ? '+' : '') + t1delta.roi.toFixed(3) : '—'}
          sub={t1delta ? `tokens ${t1delta.tok > 0 ? '+' : ''}${Math.round(t1delta.tok)}` : 'same-domain'} />
        <TierStat label="T2 avg Δ ROI" color="#facc15"
          value={t2delta ? (t2delta.roi >= 0 ? '+' : '') + t2delta.roi.toFixed(3) : '—'}
          sub={t2delta ? `tokens ${t2delta.tok > 0 ? '+' : ''}${Math.round(t2delta.tok)}` : 'cross-domain'} />
        <TierStat label="Total runs" color="var(--text-h)"
          value={t1runs.length + t2runs.length} sub={`T1 + T2 runs`} />
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

      <ChartCard title="🎯 Tier 1 — Same-domain transfer: operator misuse chain" style={{ marginBottom: 20 }}>
        <Tier2Chart runs={t1runs} metric={metric} />
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
          4 operator bugs run sequentially, shared memory. Claim: run2 improves as same-domain memory accumulates.
        </div>
      </ChartCard>

      <ChartCard title="🌐 Tier 2 — Cross-domain transfer: value misuse → variable misuse">
        <Tier3Chart runs={t2runs} metric={metric} />
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
          3 value-misuse bugs → 3 variable-misuse bugs, shared memory throughout. Green = value domain, purple = variable domain. Dashed line = domain boundary.
          Claim: strategies learned fixing value bugs (wrong constants) generalize to variable bugs (wrong variable references).
        </div>
      </ChartCard>
    </div>
  )
}

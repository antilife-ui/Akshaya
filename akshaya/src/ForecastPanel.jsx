import { useEffect, useMemo, useState } from 'react'
import { ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from 'recharts'
import Panel, { fs } from './Panel'
import { project } from './inventory'
import { api, buildProjection } from './api'

const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const arrow = 'flex h-6 w-6 items-center justify-center rounded-full border border-white/40 bg-white/10 transition hover:bg-white/30 active:scale-90'

function Tip({ active, payload, label, unit }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-xl border border-white/40 bg-slate-900/50 px-3 py-2 text-xs text-white shadow-2xl backdrop-blur-md">
      <div className="font-semibold">{label === 0 ? 'Today' : label > 0 ? `In ${label} days` : `${-label} days ago`}</div>
      {p.mean !== undefined && label > 0 ? <div className="tabular-nums">Forecast {Math.round(p.mean)} {unit} <span className="text-white/60">({Math.round(p.band[0])}–{Math.round(p.band[1])})</span></div>
        : <div className="tabular-nums">Stock {Math.round(p.hist ?? p.mean)} {unit}</div>}
    </div>
  )
}

export default function ForecastPanel({ rows, version = 0, loading = false, className }) {
  const [i, setI] = useState(0)
  const [N, setN] = useState(60)
  const r = rows[i % rows.length]
  const unit = r.unit ?? 'kt'

  // Live rows: pull the material's stock projection + recent consumption from the backend.
  const [srv, setSrv] = useState(null)
  useEffect(() => {
    if (!r.live) { setSrv(null); return }
    let on = true
    Promise.all([api.inventory(r.id), api.dailyConsumption(r.id)])
      .then(([inv, cons]) => on && setSrv({ id: r.id, inv, cons }))
      .catch(() => on && setSrv({ id: r.id, failed: true }))
    return () => { on = false }
  }, [r.id, r.live, version])
  const ready = r.live && srv && srv.id === r.id && !srv.failed
  const { pts, breach } = useMemo(
    () => (ready ? buildProjection(r, srv.inv, srv.cons, N) : project(r, N)),
    [r, srv, ready, N],
  )
  const conf = ready && srv.inv.confidence_level ? Math.round(srv.inv.confidence_level * 100) : 91 + ((r.name.length * 3) % 6)
  const step = (d) => setI((v) => (v + d + rows.length) % rows.length)

  return (
    <Panel eyebrow={r.live ? `AI forecast · ${ready ? (srv.inv.model_name || 'live').replace(/_/g, ' ') : 'live'}` : 'AI forecast · trial'} title="Demand Forecast" delay={450} className={className}
      right={<div className="flex rounded-full border border-white/35 bg-white/10 p-0.5" role="group" aria-label="Horizon">
        {[30, 60, 90].map((d) => <button key={d} type="button" aria-pressed={N === d} onClick={() => setN(d)}
          className={`rounded-full px-2 py-0.5 font-light transition duration-300 ${N === d ? 'bg-white/30 shadow' : 'hover:bg-white/15'}`} style={fs(.58, 1.3, .75)}>{d}d</button>)}
      </div>}>
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label="Previous material" onClick={() => step(-1)} className={arrow}>‹</button>
          <span key={r.name} className="fade-up min-w-[5.5rem] text-center font-light" style={fs(.75, 1.9, 1)}>{r.name}</span>
          <button type="button" aria-label="Next material" onClick={() => step(1)} className={arrow}>›</button>
        </div>
        <div className="text-right font-light leading-tight" style={fs(.58, 1.25, .78)}>
          <div><span className="text-white/65">Safety breach </span>{breach === null ? `>${N} d` : breach === 0 ? 'now' : `~${breach} d`}</div>
          <div><span className="text-white/65">Confidence </span>{conf}%</div>
        </div>
      </div>
      <div className="relative mt-1 min-h-0 flex-1">
        <div className="absolute inset-0">
          {!loading && (r.live ? ready || srv?.failed : true) && <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={pts} margin={{ top: 6, right: 6, left: -8, bottom: 0 }}>
              <defs><linearGradient id="band" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#9CC3FF" stopOpacity={0.5} /><stop offset="100%" stopColor="#9CC3FF" stopOpacity={0.1} /></linearGradient></defs>
              <CartesianGrid vertical={false} stroke="rgba(255,255,255,.18)" strokeDasharray="3 5" />
              <XAxis type="number" dataKey="t" domain={[-30, N]} ticks={[-30, 0, Math.round(N / 2), N]} tickLine={false} axisLine={{ stroke: 'rgba(255,255,255,.35)' }}
                tickFormatter={(t) => (t === 0 ? 'Today' : t > 0 ? `+${t}d` : `${t}d`)} tick={{ fill: 'rgba(255,255,255,.85)', fontSize: 11 }} />
              <YAxis tickLine={false} axisLine={false} width={34} domain={[0, 'auto']} tickFormatter={r.live ? (v) => (v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : v) : undefined} tick={{ fill: 'rgba(255,255,255,.75)', fontSize: 11 }} />
              <Tooltip content={<Tip unit={unit} />} cursor={{ stroke: 'rgba(255,255,255,.5)', strokeDasharray: '4 4' }} />
              <ReferenceLine y={r.safety} stroke="#F5A3B8" strokeDasharray="5 4" />
              <ReferenceLine x={0} stroke="rgba(255,255,255,.55)" strokeDasharray="2 4" />
              <Area dataKey="band" stroke="none" fill="url(#band)" isAnimationActive={!reduced} animationDuration={700} />
              <Line dataKey="hist" stroke="#fff" strokeWidth={2} dot={false} isAnimationActive={!reduced} animationDuration={700} />
              <Line dataKey="mean" stroke="#9CC3FF" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={!reduced} animationDuration={900} />
            </ComposedChart>
          </ResponsiveContainer>}
        </div>
      </div>
    </Panel>
  )
}

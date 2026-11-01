import { useEffect, useMemo, useState } from 'react'
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'
import { MATERIALS, DATA } from './data'
import { api, toConsumptionModel } from './api'

const compact = (v) => (v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : `${Math.round(v)}`)
const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const fs = (min, cq, max) => ({ fontSize: `clamp(${min}rem, ${cq}cqw, ${max}rem)` })

function Tip({ active, payload, label, mats, unit, mt }) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + p.value, 0)
  return (
    <div className="min-w-[10rem] rounded-2xl border border-white/40 bg-slate-900/50 px-4 py-3 text-xs text-white shadow-2xl backdrop-blur-md">
      <div className="mb-2 font-semibold tracking-wide">{label}</div>
      {[...payload].reverse().map((p) => (
        <div key={p.dataKey} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-2"><i className="h-2 w-2 rounded-full" style={{ background: p.stroke }} />{mats.find((m) => m.key === p.dataKey)?.label}</span>
          <span className="tabular-nums">{p.value.toLocaleString('en-IN')} {unit}</span>
        </div>
      ))}
      <div className="mt-2 flex justify-between border-t border-white/30 pt-2 font-semibold"><span>Total</span><span className="tabular-nums">{mt(total)} Mt</span></div>
    </div>
  )
}

export default function ConsumptionPanel({ delay = 150, version = 0, className = '' }) {
  const [range, setRange] = useState(12)
  const [off, setOff] = useState({})
  // Live monthly consumption from the backend; falls back to the built-in synthetic trial data.
  const [src, setSrc] = useState({ status: 'loading' })
  useEffect(() => {
    let on = true
    api.consumption12M()
      .then((res) => { const m = toConsumptionModel(res); if (on) setSrc(m.rows.length ? { status: 'live', ...m } : { status: 'demo' }) })
      .catch(() => on && setSrc({ status: 'demo' }))
    return () => { on = false }
  }, [version])
  const live = src.status === 'live'
  const mats = live ? src.mats : MATERIALS
  const unit = live ? src.unit : 'kt'
  const mt = (v, d = 2) => (v / (live ? 1e6 : 1e3)).toFixed(d) // demo is in kt, live in tonnes -> million tonnes
  const data = useMemo(() => (src.status === 'loading' ? [] : (live ? src.rows : DATA).slice(-range)), [src, live, range])
  const visible = mats.filter((m) => !off[m.key])
  const total = data.reduce((s, r) => s + visible.reduce((a, m) => a + r[m.key], 0), 0)
  const toggle = (k) => { if (!off[k] && visible.length === 1) return; setOff((o) => ({ ...o, [k]: !o[k] })) }
  const move = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
    e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
  }

  return (
    <section aria-label="Material consumption" onMouseMove={move} style={{ '--d': `${delay}ms`, containerType: 'inline-size' }}
      className={`glass panel pointer-events-auto z-10 rounded-[2rem] lg:rounded-[2.5rem] text-white ${className}`}>
      <div className="relative z-10 flex h-full flex-col" style={{ padding: 'clamp(1rem,3.2cqw,2.6rem) clamp(1rem,3.8cqw,3rem) clamp(.8rem,2.2cqw,1.8rem)' }}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-light uppercase text-white/70" style={{ ...fs(.6, 1.15, .8), letterSpacing: '.28em' }}>SAIL · Raw material consumption</p>
            <h2 className="mt-1 font-extralight leading-tight" style={fs(1.4, 3.4, 2.6)}>Material Consumption</h2>
            <p className="font-light text-white/70" style={fs(.65, 1.3, .85)}>{live ? `${src.first} – ${src.last} · million tonnes · live data` : 'FY 2025-26 · million tonnes · synthetic trial data'}</p>
          </div>
          <div className="text-right">
            <div className="font-extralight tabular-nums leading-none" style={fs(1.6, 4.4, 3.4)}>{mt(total, 1)}<span className="ml-1 font-light text-white/70" style={fs(.8, 1.7, 1.1)}>Mt</span></div>
            <p className="font-light text-white/70" style={fs(.6, 1.2, .8)}>{range === 12 ? (live ? 'Last 12 months' : 'Full year') : 'Last 6 months'}</p>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1.5">
            {mats.map((m) => (
              <button key={m.key} type="button" aria-pressed={!off[m.key]} onClick={() => toggle(m.key)}
                className={`flex items-center gap-1.5 rounded-full border border-white/35 bg-white/10 px-2.5 py-1 font-light transition duration-300 hover:bg-white/25 active:scale-95 ${off[m.key] ? 'opacity-40' : ''}`}
                style={fs(.62, 1.25, .8)}>
                <i className="h-2 w-2 rounded-full transition-transform duration-300" style={{ background: m.color, transform: off[m.key] ? 'scale(.5)' : 'scale(1)' }} />{m.label}
              </button>
            ))}
          </div>
          <div className="flex rounded-full border border-white/35 bg-white/10 p-0.5" role="group" aria-label="Range">
            {[6, 12].map((r) => (
              <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}
                className={`rounded-full px-3 py-1 font-light transition duration-300 ${range === r ? 'bg-white/30 shadow' : 'hover:bg-white/15'}`} style={fs(.62, 1.25, .8)}>{r}M</button>
            ))}
          </div>
        </div>

        <div className="relative mt-3 min-h-0 flex-1">
          <div className="absolute inset-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 6, right: 6, left: -6, bottom: 0 }}>
                <defs>
                  {mats.map((m) => (
                    <linearGradient key={m.key} id={`g-${m.key}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={m.color} stopOpacity={0.75} /><stop offset="100%" stopColor={m.color} stopOpacity={0.12} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid vertical={false} stroke="rgba(255,255,255,.18)" strokeDasharray="3 5" />
                <XAxis dataKey="month" tickLine={false} axisLine={{ stroke: 'rgba(255,255,255,.35)' }} tick={{ fill: 'rgba(255,255,255,.85)', fontSize: 12 }} />
                <YAxis tickLine={false} axisLine={false} width={34} tickFormatter={(v) => (live ? compact(v) : mt(v, 0))} tick={{ fill: 'rgba(255,255,255,.75)', fontSize: 12 }} />
                <Tooltip content={<Tip mats={mats} unit={unit} mt={mt} />} cursor={{ stroke: 'rgba(255,255,255,.55)', strokeDasharray: '4 4' }} />
                {visible.map((m) => (
                  <Area key={m.key} type="monotone" dataKey={m.key} stackId="c" stroke={m.color} strokeWidth={1.6} fill={`url(#g-${m.key})`}
                    isAnimationActive={!reduced} animationDuration={900} animationEasing="ease-out" activeDot={{ r: 3.5, strokeWidth: 0, fill: '#fff' }} />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </section>
  )
}

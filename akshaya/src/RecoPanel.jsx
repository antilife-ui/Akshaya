import { useMemo } from 'react'
import Panel, { fs } from './Panel'
import { analyse } from './inventory'

const TONE = { Critical: '#F5A3B8', Low: '#FFD28A', Healthy: '#8FE3C8', Overstock: '#C9B6FF', Slow: '#A8E6F0' }

export default function RecoPanel({ rows, source, loading, className }) {
  // Backend rows arrive already analysed (status, cover, order quantity); demo rows are analysed locally.
  const list = useMemo(() => (rows[0]?.live ? rows : analyse(rows)), [rows])
  const urgent = list.filter((m) => m.status === 'Critical' || m.status === 'Low')
  const shown = list.slice(0, 5)
  return (
    <Panel eyebrow={`AI recommendations · ${source || (list[0].live ? 'live data' : 'demo data')}`} title="Replenishment Priorities" delay={600} className={className}
      right={<div className="text-right font-light leading-tight" style={fs(.62, 1.2, .85)}>
        <div><b className="font-semibold" style={{ color: urgent.length ? TONE.Critical : TONE.Healthy }}>{urgent.length}</b> of {list.length} need action</div>
        <div className="text-white/70">Scarcest: {list[0].name}{list.length > 5 ? ` · +${list.length - 5} more` : ''}</div>
      </div>}>
      <div key={`${source || ''}|${list[0].live ? 'live' : 'demo'}|${loading}`} className="fade-up mt-3 grid min-h-0 flex-1 grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
        {(loading ? [] : shown).map((m, i) => (
          <article key={m.name} className="flex flex-col justify-between rounded-2xl border border-white/30 bg-white/10 p-3 transition duration-300 hover:-translate-y-0.5 hover:bg-white/20">
            <div className="flex items-start justify-between gap-1">
              <span className="font-light leading-tight" style={fs(.75, 1.6, 1)}><span className="text-white/55">{i + 1}. </span>{m.name}</span>
              <span className="rounded-full px-1.5 py-0.5 font-medium text-slate-900" style={{ background: TONE[m.status], ...fs(.5, 1, .65) }}>{m.status}</span>
            </div>
            <div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/25" title={`${m.cover.toFixed(1)} days of cover`}>
                <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(100, (m.cover / (m.lead + 30)) * 100)}%`, background: TONE[m.status] }} />
              </div>
              <p className="mt-1 font-light text-white/75" style={fs(.58, 1.15, .75)}>{m.cover.toFixed(1)} d cover · lead {m.lead} d</p>
              <p className="font-light" style={fs(.65, 1.35, .9)}>{m.need > 0 ? `Order ${Math.round(m.need).toLocaleString('en-IN')} ${m.unit ?? 'kt'}` : 'Stock sufficient'}<span className="text-white/65"> · {m.act}</span></p>
            </div>
          </article>
        ))}
      </div>
    </Panel>
  )
}

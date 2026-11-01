import { useRef, useState } from 'react'
import Panel, { fs } from './Panel'
import { api, localSampleCsv } from './api'

const btn = 'rounded-full border border-white/45 bg-white/15 px-3 py-1 font-light backdrop-blur-sm transition duration-300 hover:bg-white/30 active:scale-95'

export default function UploadPanel({ source, onUploaded, onClear, className }) {
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const input = useRef(null)

  async function handle(file) {
    if (!file || busy) return
    setErr('')
    if (!/\.csv$/i.test(file.name)) return setErr('Please use a CSV datasheet (.csv).')
    if (file.size > 10 * 1024 * 1024) return setErr('That file is over 10 MB.')
    setBusy(true)
    try {
      // The backend validates the file, stores it, rebuilds the demand series and retrains the forecasts.
      const [res] = await Promise.all([api.uploadCsv(file), new Promise((r) => setTimeout(r, 800))])
      onUploaded({
        name: file.name, count: res.materials_processed,
        note: `${res.valid_rows.toLocaleString('en-IN')} rows loaded`,
        columns: [`${res.forecasts_generated} forecasts`, res.invalid_rows ? `${res.invalid_rows} rows skipped` : 'all rows valid'],
      })
    } catch (e) {
      const first = e.detail?.errors?.[0]
      setErr(first?.row ? `${e.message} (row ${first.row}: ${first.error})` : e.message || 'Could not upload that file.')
    }
    setBusy(false)
  }
  const sample = async () => {
    let text
    try { text = await api.sampleCsv() } catch { text = localSampleCsv() } // works offline too
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' })); a.download = 'akshaya-sample-inventory.csv'; a.click()
    URL.revokeObjectURL(a.href)
  }
  const pick = () => input.current?.click()

  return (
    <Panel eyebrow="Data intake" title="Upload Datasheet" delay={300} className={className}
      right={<button type="button" onClick={sample} className={btn} style={fs(.6, 1.2, .8)}>Sample CSV</button>}>
      <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => { handle(e.target.files[0]); e.target.value = '' }} />
      <div role="button" tabIndex={0} aria-label="Drop your inventory CSV datasheet here or press to browse" onClick={pick}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), pick())}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); handle(e.dataTransfer.files[0]) }}
        className={`mt-3 flex min-h-0 flex-1 cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed text-center outline-none transition duration-300 focus-visible:ring-2 focus-visible:ring-white/70 ${drag ? 'scale-[1.02] border-white bg-white/25' : 'border-white/45 bg-white/10 hover:bg-white/15'}`}
        style={{ padding: 'clamp(.6rem,2cqw,1.4rem)' }}>
        {busy ? (
          <div className="fade-up w-3/5"><p className="mb-3 font-light" style={fs(.8, 1.9, 1.1)}>Analysing datasheet…</p>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/25"><div className="h-full w-full origin-left animate-[load_.8s_ease-out] rounded-full bg-white/80" /></div></div>
        ) : source ? (
          <div className="fade-up">
            <svg viewBox="0 0 24 24" className="mx-auto mb-2 h-9 w-9 text-[#8FE3C8]" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="m8 12.5 3 3 5-6" /></svg>
            <p className="max-w-full truncate font-light" style={fs(.9, 2.3, 1.3)}>{source.name}</p>
            <p className="mt-1 font-light text-white/75" style={fs(.65, 1.5, .9)}>{source.count} materials · {source.note}</p>
            <div className="mt-2 flex flex-wrap justify-center gap-1">{source.columns.map((c) => <span key={c} className="rounded-full bg-white/20 px-2 py-0.5" style={fs(.55, 1.2, .75)}>{c}</span>)}</div>
            <div className="mt-3 flex justify-center gap-2" onClick={(e) => e.stopPropagation()}>
              <button type="button" onClick={pick} className={btn} style={fs(.6, 1.3, .8)}>Replace</button>
              <button type="button" onClick={onClear} className={btn} style={fs(.6, 1.3, .8)}>Remove</button>
            </div>
          </div>
        ) : (
          <>
            <svg viewBox="0 0 24 24" className={`mb-2 h-10 w-10 transition-transform duration-300 ${drag ? '-translate-y-1' : ''}`} fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4m0 0 4 4m-4-4L8 8" /><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
            <p className="font-light" style={fs(.9, 2.3, 1.3)}>Drop your datasheet / CSV here</p>
            <p className="mt-1 max-w-[28ch] font-light text-white/75" style={fs(.62, 1.4, .85)}>Only the CSV datasheet containing your inventory data. Or click to browse · .csv · max 10 MB</p>
          </>
        )}
      </div>
      <p role="alert" className={`mt-2 min-h-[1.2em] text-center font-light text-red-100 ${err ? 'fade-up' : ''}`} style={fs(.62, 1.4, .85)}>{err}</p>
    </Panel>
  )
}

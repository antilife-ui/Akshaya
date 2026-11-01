import { useEffect, useState } from 'react'
import ConsumptionPanel from './ConsumptionPanel'
import UploadPanel from './UploadPanel'
import ForecastPanel from './ForecastPanel'
import RecoPanel from './RecoPanel'
import { DEMO } from './inventory'
import { api, fromServer } from './api'

function Img({ src, alt, fallback, className, ...rest }) {
  const [failed, setFailed] = useState(false)
  if (failed) return fallback
  return <img src={src} alt={alt} className={className} onError={() => setFailed(true)} {...rest} />
}

/* SAIL logo: static, no glow, no hover. Sits above the background and BEHIND the glass cards. */
const SailLogo = () => (
  <div className="w-[170px] sm:w-[210px] lg:w-full">
    <Img
      src="/sail-logo.png" alt="SAIL - Steel Authority of India Limited"
      width="482" height="517" className="block w-full h-auto select-none" draggable="false"
      fallback={<span className="text-3xl font-semibold text-[#3a5694]">SAIL</span>}
    />
  </div>
)

function GlassCard({ n, delay, className = '' }) {
  const move = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
    e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
  }
  return (
    <button
      type="button" aria-label={`Section ${n}`} onMouseMove={move}
      style={{ '--d': `${delay}ms` }}
      className={`glass z-10 rounded-[2rem] lg:rounded-[2.5rem] cursor-pointer text-white flex items-center justify-center ${className}`}
    >
      <span className="num relative z-10 text-6xl sm:text-7xl font-extralight">{n}</span>
    </button>
  )
}

export default function App() {
  const [src, setSrc] = useState(null)        // last uploaded file (name + summary) for the Upload card
  const [version, setVersion] = useState(0)     // bump to make every panel re-read the backend
  const [live, setLive] = useState(null)        // rows from the backend, or null -> built-in demo data
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let on = true
    api.recommendations()
      .then((r) => { const rows = fromServer(r); if (on) setLive(rows.length ? rows : null) })
      .catch(() => on && setLive(null))
      .finally(() => on && setLoading(false))
    return () => { on = false }
  }, [version])
  const rows = live ?? DEMO
  return (
    <main className="min-h-screen relative overflow-hidden bg-slate-700">
      <div className="bg-factory absolute inset-0 saturate-[.55] contrast-95" aria-hidden="true" />
      <div className="absolute inset-0 bg-gradient-to-b from-slate-900/10 via-slate-700/30 to-slate-900/55 pointer-events-none" aria-hidden="true" />
      <div className="relative mx-auto w-full max-w-[1440px] lg:aspect-[1440/1024] flex flex-col lg:block">

        {/* Header */}
        <header className="fade-down lg:absolute lg:inset-0 lg:pointer-events-none px-4 pt-4 lg:px-0 lg:pt-0">
          <div className="flex items-start justify-between gap-3">
            <div className="lg:pl-[0.8%]">
              <h1 className="text-5xl sm:text-6xl lg:text-[clamp(3rem,6.7vw,6.2rem)] font-extralight leading-none tracking-wide drop-shadow-md">AKSHAYA</h1>
              <p className="mt-1 text-sm sm:text-base lg:text-[clamp(.8rem,1.15vw,1.1rem)] font-light drop-shadow-md">
                Powering Atmanirbhar Supply Chains for India’s Industrial Giants.
              </p>
            </div>
            <div className="flex items-center gap-3 lg:contents">
              <Img
                src="/emblem-india.png" alt="Government of India"
                width="249" height="111" className="h-12 sm:h-14 w-auto lg:h-auto lg:w-[17.29%] lg:absolute lg:left-[70.35%] lg:top-[1.9%]"
                fallback={<span className="text-sm">Government of India</span>}
              />
              <Img
                src="/emblem-jharkhand.png" alt="Government of Jharkhand"
                width="146" height="146" className="h-12 w-12 sm:h-14 sm:w-14 lg:h-auto lg:w-[10.14%] lg:absolute lg:left-[89.3%] lg:top-0"
                fallback={<span className="text-sm">Jharkhand</span>}
              />
            </div>
          </div>
          <div className="mt-3 h-px w-full bg-white/80 lg:absolute lg:left-0 lg:top-[14.45%] lg:mt-0" />
        </header>

        {/* SAIL logo: above background, below glass cards */}
        <div className="order-first lg:order-none z-[5] flex justify-center py-4 lg:py-0 lg:absolute lg:left-[50.4%] lg:top-[52%] lg:w-[23.6%] lg:-translate-x-1/2 lg:-translate-y-1/2 pointer-events-none">
          <SailLogo />
        </div>

        {/* Cards: stacked on mobile, positioned like the design on desktop */}
        <div className="relative flex flex-col gap-4 p-4 lg:p-0 lg:contents">
          <ConsumptionPanel delay={150} version={version} className="h-[28rem] lg:absolute lg:left-[5.2%] lg:top-[20.7%] lg:w-[52.8%] lg:!h-[49.8%]" />
          <UploadPanel source={src} onUploaded={(info) => { setSrc(info); setVersion((v) => v + 1) }} onClear={() => setSrc(null)} className="h-[26rem] lg:absolute lg:left-[59.4%] lg:top-[20.7%] lg:w-[35.7%] lg:!h-[40.6%]" />
          <ForecastPanel rows={rows} version={version} loading={loading} className="h-[24rem] lg:absolute lg:left-[65.8%] lg:top-[63.3%] lg:w-[29.3%] lg:!h-[33.9%]" />
          <RecoPanel rows={rows} source={src?.name} loading={loading} className="lg:absolute lg:left-[5.2%] lg:top-[72.5%] lg:w-[59.6%] lg:!h-[24.7%]" />
        </div>
      </div>
    </main>
  )
}

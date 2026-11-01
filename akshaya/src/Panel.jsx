export const fs = (min, cq, max) => ({ fontSize: `clamp(${min}rem, ${cq}cqw, ${max}rem)` })

export default function Panel({ eyebrow, title, right, delay = 0, className = '', children }) {
  const move = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
    e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
  }
  return (
    <section aria-label={title} onMouseMove={move} style={{ '--d': `${delay}ms`, containerType: 'inline-size' }}
      className={`glass panel pointer-events-auto z-10 rounded-[2rem] lg:rounded-[2.5rem] text-white ${className}`}>
      <div className="relative z-10 flex h-full flex-col" style={{ padding: 'clamp(.9rem,3.4cqw,2.2rem)' }}>
        <header className="flex items-start justify-between gap-3">
          <div>
            <p className="font-light uppercase text-white/70" style={{ ...fs(.55, 1.1, .8), letterSpacing: '.26em' }}>{eyebrow}</p>
            <h2 className="font-extralight leading-tight" style={fs(1.15, 3.2, 2.4)}>{title}</h2>
          </div>
          {right}
        </header>
        {children}
      </div>
    </section>
  )
}

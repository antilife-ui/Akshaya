export const PAL = ['#9CC3FF', '#FFD28A', '#8FE3C8', '#F5A3B8', '#C9B6FF', '#A8E6F0', '#FFC4A3', '#D6E39A']
// Demo inventory (kilo-tonnes). Shown until the backend has data (upload a CSV to go live).
export const DEMO = [
  { name: 'Iron ore', stock: 1500, daily: 88, safety: 900, lead: 7 },
  { name: 'Coking coal', stock: 520, daily: 63, safety: 600, lead: 21 },
  { name: 'Limestone', stock: 640, daily: 25, safety: 300, lead: 5 },
  { name: 'Dolomite', stock: 140, daily: 12.5, safety: 150, lead: 6 },
  { name: 'Scrap', stock: 95, daily: 8, safety: 60, lead: 10 },
]
export const SAMPLE_CSV = 'material,stock_kt,daily_use_kt,safety_stock_kt,lead_time_days\n' +
  DEMO.map((r) => [r.name, r.stock, r.daily, r.safety, r.lead].join(',')).join('\n') + '\n'

function splitCsv(text) {
  const first = text.split(/\r?\n/, 1)[0]
  const d = [',', ';', '\t'].map((c) => [c, first.split(c).length]).sort((a, b) => b[1] - a[1])[0][0]
  const rows = []; let row = [], cell = '', q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++ } else q = false } else cell += c }
    else if (c === '"') q = true
    else if (c === d) { row.push(cell); cell = '' }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = '' }
    else cell += c
  }
  row.push(cell); rows.push(row)
  return rows
}

export function parseInventory(text) {
  const rows = splitCsv(text.replace(/^\uFEFF/, '')).filter((r) => r.some((c) => c.trim()))
  if (rows.length < 2) return { error: 'The file needs a header row and at least one data row.' }
  const head = rows[0].map((h) => h.toLowerCase().replace(/[^a-z0-9]/g, ''))
  const find = (keys, not = []) => head.findIndex((h) => keys.some((k) => h.includes(k)) && !not.some((n) => h.includes(n)))
  const ix = {
    name: find(['material', 'item', 'commodity', 'name']),
    stock: find(['stock', 'inventory', 'onhand', 'quantity', 'qty'], ['safety', 'min', 'reorder', 'buffer']),
    daily: find(['daily', 'perday', 'consumption', 'usage']),
    safety: find(['safety', 'reorder', 'minstock', 'buffer']),
    lead: find(['lead', 'delivery']),
  }
  const missing = [['name', 'material name'], ['stock', 'current stock'], ['daily', 'daily consumption']].filter(([k]) => ix[k] < 0).map(([, l]) => l)
  if (missing.length) return { error: `Missing column(s): ${missing.join(', ')}. Download the sample CSV for the expected format.` }
  const num = (v) => parseFloat(String(v ?? '').replace(/,/g, ''))
  const out = rows.slice(1).map((r) => {
    const daily = num(r[ix.daily]), stock = num(r[ix.stock])
    const safety = ix.safety >= 0 ? num(r[ix.safety]) : daily * 7, lead = ix.lead >= 0 ? num(r[ix.lead]) : 7
    return { name: String(r[ix.name] || '').trim(), stock, daily, safety: Number.isFinite(safety) ? safety : daily * 7, lead: Number.isFinite(lead) ? lead : 7 }
  }).filter((r) => r.name && Number.isFinite(r.stock) && r.stock >= 0 && Number.isFinite(r.daily) && r.daily > 0).slice(0, 12)
  if (!out.length) return { error: 'No valid rows found. Check that stock and daily consumption are numbers.' }
  const labels = { name: 'Material', stock: 'Stock', daily: 'Daily use', safety: 'Safety stock', lead: 'Lead time' }
  return { rows: out, columns: Object.keys(ix).filter((k) => ix[k] >= 0).map((k) => labels[k]) }
}

export function analyse(rows) {
  return rows.map((r, i) => {
    const cover = r.stock / r.daily, rop = r.daily * r.lead + r.safety
    const status = r.stock < r.safety || cover < r.lead ? 'Critical' : r.stock < rop ? 'Low' : 'Healthy'
    const need = Math.max(0, r.daily * (r.lead + 30) + r.safety - r.stock)
    const act = status === 'Critical' ? 'Order now' : status === 'Low' ? `Order within ${Math.max(1, Math.floor(cover - r.lead))} d` : 'No action'
    return { ...r, color: PAL[i % PAL.length], cover, rop, status, need, act, score: (rop - r.stock) / rop }
  }).sort((a, b) => b.score - a.score)
}

export function project(r, N) {
  const pts = []
  for (let t = -30; t < 0; t += 2) pts.push({ t, hist: Math.max(0, r.stock + r.daily * -t * 0.55 * (1 + 0.4 * Math.sin(-t * 0.9))) })
  const step = N <= 30 ? 1 : N / 30
  for (let t = 0; t <= N; t += step) {
    const mean = Math.max(0, r.stock - r.daily * t * (1 + 0.06 * Math.sin(t / 7)))
    const w = r.daily * Math.sqrt(t) * 2.2
    pts.push({ t: Math.round(t), hist: t === 0 ? r.stock : undefined, mean, band: [Math.max(0, mean - w), mean + w] })
  }
  const hit = pts.find((p) => p.mean !== undefined && p.mean < r.safety)
  return { pts, breach: r.stock < r.safety ? 0 : hit ? hit.t : null }
}

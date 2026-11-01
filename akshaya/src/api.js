// Thin client for the Akshaya backend (FastAPI). Every call degrades gracefully:
// if the API is unreachable the panels keep showing the built-in demo data.
import { PAL } from './inventory'

// Dev: Vite proxies /api -> http://localhost:8000 (see vite.config.js). Production: set VITE_API_URL.
const BASE = (import.meta.env?.VITE_API_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status = 0, detail = null) { super(message); this.status = status; this.detail = detail }
}

async function request(path, { method = 'GET', body, timeout = 8000 } = {}) {
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), timeout)
  let res
  try { res = await fetch(BASE + path, { method, body, signal: ctl.signal }) }
  catch { throw new ApiError('Cannot reach the Akshaya API. Start the backend and try again.') }
  finally { clearTimeout(timer) }
  if (!res.ok) {
    const j = await res.json().catch(() => null)
    const d = j?.detail
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : d?.message || `Request failed (${res.status})`
    throw new ApiError(msg, res.status, d)
  }
  return res
}
const json = async (path, opts) => (await request(path, opts)).json()

// ---------------------------------------------------------------- colours
const COLOR_BY_ID = {
  'MAT-IRON-ORE': '#9CC3FF', 'MAT-COKING-COAL': '#FFD28A', 'MAT-LIMESTONE': '#8FE3C8',
  'MAT-DOLOMITE': '#F5A3B8', 'MAT-SCRAP': '#C9B6FF',
}
const colorFor = (id, i) => COLOR_BY_ID[id] || PAL[i % PAL.length]

// ---------------------------------------------------------------- endpoints
export const api = {
  recommendations: () => json('/recommendations'),
  inventory: (id) => json(`/inventory/${encodeURIComponent(id)}?projection_days=90`),
  dailyConsumption: (id) => json(`/analytics/consumption?material_id=${encodeURIComponent(id)}&period=6M`),
  consumption12M: () => json('/analytics/consumption?period=12M&granularity=monthly'),
  async uploadCsv(file) {
    const fd = new FormData(); fd.append('file', file)
    return json('/upload/csv', { method: 'POST', body: fd, timeout: 180000 }) // forecasting can take a while
  },
  async sampleCsv() { return (await request('/upload/sample-template')).text() },
}

export function localSampleCsv() {
  const d = new Date(Date.now() - 864e5).toISOString().slice(0, 10)
  const rows = [['Iron Ore', 820, 5000, 7], ['Coking Coal', 310, 2200, 12], ['Limestone', 480, 3500, 5], ['Dolomite', 250, 1800, 6], ['Scrap', 390, 2600, 8]]
  return 'material_name,date,quantity_consumed,current_stock,lead_time_days,unit\n' + rows.map(([n, q, s, l]) => `${n},${d},${q},${s},${l},tonne`).join('\n') + '\n'
}

// ---------------------------------------------------------------- mappers
// Server recommendation items -> the row shape the Replenishment / Forecast panels already use.
const STATUS = {
  CRITICAL_STOCKOUT_RISK: ['Critical', 0], REORDER_NOW: ['Low', 1], STOCKOUT_RISK: ['Low', 1],
  HEALTHY: ['Healthy', 2], SLOW_MOVING: ['Slow', 3], OVERSTOCK: ['Overstock', 4],
}
export function fromServer(reco) {
  const items = [reco.critical_materials, reco.reorder_now, reco.healthy_materials, reco.slow_moving_materials, reco.overstocked_materials]
    .flatMap((g) => g || [])
  return items.map((m, i) => {
    const [status, rank] = STATUS[m.stock_status] || ['Healthy', 2]
    const cover = m.days_of_cover, lead = m.lead_time_days
    const act = status === 'Critical' ? 'Order now'
      : status === 'Low' ? `Order within ${Math.max(1, Math.floor(cover - lead))} d`
      : status === 'Overstock' ? 'Hold purchases' : status === 'Slow' ? 'Review demand' : 'No action'
    return {
      id: m.material_id, name: m.material_name, unit: m.unit, live: true, rank,
      stock: m.current_stock, daily: m.average_daily_demand, safety: m.safety_stock, lead,
      color: colorFor(m.material_id, i), cover, rop: m.reorder_point, status,
      need: m.recommended_order_quantity, act, score: m.risk_score, depletion: m.predicted_depletion_date,
    }
  }).sort((a, b) => a.rank - b.rank || b.score - a.score)
}

// Monthly stacked consumption (12 months) for the Material Consumption chart.
export function toConsumptionModel(res) {
  const unit = res.materials[0]?.unit || 'tonne'
  const mats = res.materials.map((m, i) => ({ key: m.material_id, label: m.material_name, color: colorFor(m.material_id, i) }))
  let rows = res.stacked.map((r) => ({ ...r }))
  // The window's first month is usually a few days only; drop it so every bar is a (near-)full month.
  const startDay = Number((res.start_date || '').slice(8, 10))
  if (rows.length > 12 || (rows.length > 1 && startDay > 15)) rows = rows.slice(1)
  rows = rows.slice(-12)
  const names = rows.map((r) => new Date(r.date + 'T00:00:00').toLocaleString('en-US', { month: 'short' }))
  const dup = new Set(names).size !== names.length
  rows = rows.map((r, i) => ({ ...r, month: dup ? `${names[i]} ’${r.date.slice(2, 4)}` : names[i] }))
  return { mats, rows, unit, first: rows[0]?.month, last: rows[rows.length - 1]?.month }
}

// Forecast chart points from /inventory/{id} (projection) + /analytics/consumption (stock history).
export function buildProjection(r, inv, cons, N) {
  const pts = []
  const daily = (cons?.data || []).map((d) => d.quantity_consumed)
  for (let j = 30; j >= 2; j -= 2) {
    if (daily.length < j) continue
    const back = daily.slice(-j).reduce((s, v) => s + v, 0)  // stock j days ago = stock + what was consumed since
    pts.push({ t: -j, hist: r.stock + back })
  }
  pts.push({ t: 0, hist: r.stock, mean: r.stock, band: [r.stock, r.stock] })
  const proj = (inv.stock_projection || []).slice(0, N)
  proj.forEach((p, i) => pts.push({ t: i + 1, mean: p.projected_stock, band: [p.lower_bound, p.upper_bound] }))
  const hit = proj.findIndex((p) => p.projected_stock < r.safety)
  return { pts, breach: r.stock < r.safety ? 0 : hit >= 0 ? hit + 1 : null }
}

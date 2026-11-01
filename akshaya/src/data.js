// Synthetic trial data (kilo-tonnes per month, FY 2025-26). Replace with real feeds later.
export const MATERIALS = [
  { key: 'ironOre', label: 'Iron ore', color: '#9CC3FF', base: 2650 },
  { key: 'coal', label: 'Coking coal', color: '#FFD28A', base: 1900 },
  { key: 'limestone', label: 'Limestone', color: '#8FE3C8', base: 760 },
  { key: 'dolomite', label: 'Dolomite', color: '#F5A3B8', base: 380 },
  { key: 'scrap', label: 'Scrap', color: '#C9B6FF', base: 240 },
]
const MONTHS = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar']
const SEASON = [1.0, 1.02, 0.99, 0.9, 0.88, 0.92, 1.04, 1.06, 1.07, 1.05, 0.98, 1.1] // monsoon dip, winter peak
const rnd = (s) => { const x = Math.sin(s * 9301 + 49297) * 233280; return x - Math.floor(x) } // deterministic
export const DATA = MONTHS.map((month, i) => {
  const row = { month }
  MATERIALS.forEach((m, j) => { row[m.key] = Math.round(m.base * SEASON[i] * (0.96 + rnd(i * 7 + j * 13 + 1) * 0.08)) })
  return row
})

import { useEffect, useState } from 'react'
import { api, type J } from '../api'
import { Icon } from '../components/Icon'
import { fmtDate, fmtNum } from '../components/ui'
import type { SourceRef } from '../components/Source'

function RatePath({ path }: { path: J[] }) {
  if (!path.length) return null
  const W = 860, H = 240, P = 36
  const vals = path.map((p) => p.value)
  const mn = Math.min(...vals) - 0.5, mx = Math.max(...vals) + 0.5
  const x = (i: number) => P + (i * (W - 2 * P)) / Math.max(1, path.length - 1)
  const y = (v: number) => H - P - ((v - mn) / (mx - mn)) * (H - 2 * P)
  const d = path.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.value)}`).join(' ')
  return (
    <div className="chart"><svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Траектория ключевой ставки по прогнозу банка">
      {[0, 1, 2, 3].map((k) => { const v = mn + ((mx - mn) * k) / 3; return <g key={k}><line x1={P} x2={W - P} y1={y(v)} y2={y(v)} stroke="#eceef1" /><text x={4} y={y(v) + 4} fontSize="11" fill="#6e737d">{v.toFixed(1).replace('.', ',')}</text></g> })}
      <path d={d} fill="none" stroke="#f03024" strokeWidth="3" strokeLinejoin="round" />
      {path.map((p, i) => <g key={p.period}><circle cx={x(i)} cy={y(p.value)} r="5" fill={p.superseded.length ? '#fff' : '#f03024'} stroke="#f03024" strokeWidth="2.5" /><text x={x(i)} y={H - 8} fontSize="11" textAnchor="middle" fill="#6e737d">{p.period}</text>
        <text x={x(i)} y={y(p.value) - 11} fontSize="12" textAnchor="middle" fontWeight="700" fill="#17191c">{fmtNum(p.value)}</text></g>)}
    </svg><p className="disclaimer">Полые точки — значения, которые банк пересмотрел более поздним документом.</p></div>
  )
}

export function Analytics({ onSource }: { onSource: (s: SourceRef) => void }) {
  const [m, setM] = useState<J>(null)
  useEffect(() => { api.macro().then(setM).catch(() => {}) }, [])
  if (!m) return <main className="content"><div className="empty">Загрузка…</div></main>
  const kpi = (code: string, period: string) => m.rows.find((r: J) => r.indicator === code && r.period === period)
  const k = [['Ключевая ставка, конец 2026', kpi('key_rate_eoy', '2026'), '%'], ['USD/RUB, конец 2026', kpi('usd_rub_eoy', '2026'), ' ₽'], ['Инфляция 2026', kpi('inflation_dec_yoy', '2026'), '%']] as [string, J, string][]
  return (
    <main className="content">
      <section className="page-head"><div><p className="eyebrow"><Icon name="chart" size={16} /> Аналитика банка</p><h1>Прогнозы Альфа-Банка</h1>
        <p>Центр макроэкономических исследований. Если документы расходятся, действует самый поздний — прежние значения показаны как заменённые.</p></div></section>
      <section className="kpis">
        {k.map(([label, r, u], i) => r && (
          <button key={label} className={`kpi ${i === 0 ? 'accent' : ''}`} style={{ textAlign: 'left', border: i === 0 ? undefined : '1px solid var(--line)' }} onClick={() => onSource({ item_id: r.item_id, page: r.page })}>
            <span>{label}</span><strong>{fmtNum(r.value)}{u}</strong><span>{fmtDate(r.published_at)}, стр. {r.page}{r.superseded.length ? ` · было ${fmtNum(r.superseded[0].value)}` : ''}</span></button>))}
      </section>
      <section className="card"><h2>Траектория ключевой ставки</h2><p className="sub">Факт и прогноз банка на конец периода, %</p><RatePath path={m.key_rate_path} /></section>
      <section className="card"><h2>Показатели и версии прогнозов</h2><p className="sub">{m.changed} показателей обновлено относительно прежних документов</p>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Показатель</th><th>Период</th><th>Значение</th><th>Источник</th></tr></thead>
          <tbody>{m.rows.map((r: J) => (
            <tr key={r.indicator + r.period}><td>{r.label}</td><td>{r.period}</td>
              <td><b>{fmtNum(r.value)}</b> <small>{r.unit}</small>{r.superseded.length > 0 && <div><span className="chip warn">заменено: {r.superseded.map((s: J) => fmtNum(s.value)).join(', ')}</span></div>}</td>
              <td><button className="src-link" onClick={() => onSource({ item_id: r.item_id, page: r.page })}>{fmtDate(r.published_at)}, стр. {r.page}</button></td></tr>))}</tbody></table></div>
        <p className="disclaimer">{m.note}</p></section>
      <section className="card"><h2>Материалы Центра макроэкономических исследований</h2><p className="sub">Источники, на которые опираются выводы</p>
        {m.documents.map((d: J) => (
          <div className="doc-row" key={d.item_id}><div><b>{d.title}</b><br /><small>{d.source_file}</small></div><span>{fmtDate(d.published_at)}</span>
            <span>{d.stale ? <span className="chip warn">устарел</span> : <span className="chip ok">актуален</span>}</span>
            <button className="btn small" onClick={() => onSource({ item_id: d.item_id, page: 1 })}>Открыть</button></div>))}</section>
    </main>
  )
}

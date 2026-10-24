import type { ReactNode } from 'react'
import { Icon } from './Icon'

export const ORIGIN: Record<string, { label: string; cls: string }> = {
  bank_view: { label: 'Позиция Альфа-Банка', cls: 'bank' },
  bank_data: { label: 'Данные из аналитики банка', cls: 'bank' },
  fact: { label: 'Факт из новости', cls: 'fact' },
  unconfirmed: { label: 'Не подтверждено', cls: 'warn' },
  company_data: { label: 'Данные о компании', cls: 'company' },
  rule: { label: 'Расчёт по правилам', cls: 'ai' },
  ai: { label: 'Вывод AI', cls: 'ai' },
}

export function OriginChip({ origin, method }: { origin: string; method?: string }) {
  const o = ORIGIN[origin] ?? { label: origin, cls: '' }
  const label = origin === 'ai' && method === 'rules' ? 'Вывод AI · правила' : origin === 'ai' && method === 'llm' ? 'Вывод AI · модель' : o.label
  return <span className={`chip ${o.cls}`}>{label}</span>
}

export function Legend() {
  return (
    <div className="legend">
      <span>Как читать:</span>
      <OriginChip origin="bank_view" /> <OriginChip origin="fact" /> <OriginChip origin="company_data" /> <OriginChip origin="ai" method="rules" /> <OriginChip origin="unconfirmed" />
    </div>
  )
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h3>{title}</h3><button className="icon-button" onClick={onClose} aria-label="Закрыть"><Icon name="close" /></button></div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export const SEV: Record<string, string> = { high: 'Высокая значимость', medium: 'Средняя значимость', low: 'Низкая значимость' }
export const CONF: Record<string, string> = { high: 'Высокая уверенность', medium: 'Средняя уверенность', low: 'Низкая уверенность' }
// даты показываются по московскому времени — как опорная дата и возраст материалов на сервере
export const fmtDate = (iso?: string | null) => {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Moscow' })
}
export const fmtDayMonth = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', timeZone: 'Europe/Moscow' })

const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
/** Период прогноза: «2026-09» -> «сен 2026», «2026-H1» -> «1 пол. 2026», «2026-Q3» -> «3 кв. 2026», «2026» -> «2026». */
export const fmtPeriod = (p: string) => {
  const m = /^(\d{4})-(\d{2})$/.exec(p)
  if (m) return `${MONTHS_SHORT[Number(m[2]) - 1]} ${m[1]}`
  const h = /^(\d{4})-H([12])$/.exec(p)
  if (h) return `${h[2]} пол. ${h[1]}`
  const q = /^(\d{4})-Q([1-4])$/.exec(p)
  if (q) return `${q[2]} кв. ${q[1]}`
  return p
}

/** Русское согласование с числом: plural(4, ['показатель', 'показателя', 'показателей']) -> «показателя». */
export const plural = (n: number, forms: [string, string, string]) => {
  const a = Math.abs(n) % 100, b = a % 10
  return forms[a > 10 && a < 20 ? 2 : b === 1 ? 0 : b >= 2 && b <= 4 ? 1 : 2]
}

export const fmtNum = (v: number) => Number(v).toLocaleString('ru-RU', { minimumFractionDigits: Number.isInteger(v) ? 1 : 0, maximumFractionDigits: 2 })

/** Первое предложение с точкой в конце: «Есть депозиты: … доход.» (без «доход..», если предложение одно). */
export const firstSentence = (s: string) => {
  const first = s.split('. ')[0].trim()
  return /[.!?…]$/.test(first) ? first : first + '.'
}

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
export const fmtDate = (iso?: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

export const fmtNum = (v: number) => Number(v).toLocaleString('ru-RU', { minimumFractionDigits: Number.isInteger(v) ? 1 : 0, maximumFractionDigits: 2 })

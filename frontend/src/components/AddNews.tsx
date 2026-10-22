import { useState } from 'react'
import { api, type J } from '../api'
import { Modal } from './ui'

const SAMPLE = 'Правительство ввело квоты на экспорт зерна до конца сезона. Экспортёры зерна и оптовые торговцы продовольствием ожидают снижения выручки, а транспортные компании — падения объёмов перевозок.'

export function AddNews({ onClose, onOpen }: { onClose: () => void; onOpen: (itemId: string) => void }) {
  const [title, setTitle] = useState('Квоты на экспорт зерна')
  const [text, setText] = useState(SAMPLE)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<J>(null)
  const [err, setErr] = useState('')
  const send = async () => {
    setBusy(true); setErr('')
    try { setRes(await api.ingest(text, title)) } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <Modal title="Проверить на своей новости" onClose={onClose}>
      <p className="lead" style={{ fontSize: 14 }}>Вставьте текст любой новости: она пройдёт весь конвейер (классификация, отрасли, регионы, проверка безопасности), затем система оценит, насколько она значима для выбранной компании.</p>
      <label className="field">Заголовок<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="field">Текст новости<textarea value={text} onChange={(e) => setText(e.target.value)} /></label>
      {err && <div className="err">{err}</div>}
      {res && (
        <div className="block">
          <div className="meta" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <span className="chip ok">{res.outcome === 'created' ? 'Добавлена' : res.outcome === 'duplicate' ? 'Дубль' : res.outcome}</span>
            {(res.item?.topics ?? []).map((t: string) => <span key={t} className="chip fact">{t}</span>)}
            {(res.item?.countries ?? []).map((t: string) => <span key={t} className="chip company">{t}</span>)}
            {res.item?.injection && <span className="chip warn">заблокирована: инструкции для AI</span>}
            {res.item?.unconfirmed && <span className="chip warn">не подтверждено</span>}
          </div>
          {res.item && !res.item.injection && <button className="btn primary small" style={{ justifySelf: 'start' }} onClick={() => onOpen(res.item.id)}>Показать анализ для этой компании</button>}
        </div>
      )}
      <div className="cta-row"><button className="btn primary" disabled={busy || text.length < 40} onClick={send}>{busy ? 'Обрабатываю…' : 'Добавить и проанализировать'}</button></div>
    </Modal>
  )
}

import { useEffect, useState } from 'react'
import { api, type J } from '../api'
import { Modal, fmtDate } from './ui'
import { Icon } from './Icon'

export type SourceRef = { item_id: string; page?: number | null; highlight?: string }

export function SourceModal({ s, onClose }: { s: SourceRef; onClose: () => void }) {
  const [d, setD] = useState<J>(null)
  const [err, setErr] = useState('')
  const [view, setView] = useState<'pdf' | 'text'>('pdf')
  useEffect(() => { api.source(s.item_id, s.page).then(setD).catch((e) => setErr(e.message)) }, [s.item_id, s.page])
  return (
    <Modal title="Первоисточник" onClose={onClose}>
      {err && <div className="err">{err}</div>}
      {!d && !err && <p className="lead">Загрузка…</p>}
      {d && (
        <>
          <div className="meta" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <span className="chip fact">{d.title}</span>
            {d.page && <span className="chip">стр. {d.page}{d.pages ? ` из ${d.pages}` : ''}</span>}
            <span className="chip">{fmtDate(d.published_at)}</span>
            {d.synthetic && <span className="chip synthetic">синтетическая демо-новость</span>}
            {d.source_file && <span className="chip">{d.source_file}</span>}
          </div>
          <p className="lead" style={{ fontSize: 13 }}>Издатель: {d.publisher}. {d.kind === 'bank' ? 'Текст получен транскрипцией страницы PDF по изображению — для критичных цифр сверяйте исходный документ.' : ''}</p>
          {d.pdf_url && (
            <div className="src-tabs" role="tablist">
              <button role="tab" aria-selected={view === 'pdf'} className={view === 'pdf' ? 'active' : ''} onClick={() => setView('pdf')}>Документ PDF{d.page ? `, стр. ${d.page}` : ''}</button>
              <button role="tab" aria-selected={view === 'text'} className={view === 'text' ? 'active' : ''} onClick={() => setView('text')}>Текст страницы</button>
              <a className="btn small" href={d.pdf_url} target="_blank" rel="noreferrer"><Icon name="external" size={15} /> Открыть в новой вкладке</a>
            </div>
          )}
          {d.pdf_url && view === 'pdf'
            ? <iframe className="pdf-frame" title={`PDF: ${d.title}`} src={d.pdf_url} />
            : <div className="src-text">{d.text}</div>}
        </>
      )}
    </Modal>
  )
}

import { useState } from 'react'
import { api, type J } from '../api'
import { Icon } from './Icon'
import { OriginChip } from './ui'
import type { SourceRef } from './Source'

export function AnswerView({ a, onSource }: { a: J; onSource: (s: SourceRef) => void }) {
  return (
    <div className="assistant-answer">
      <div><OriginChip origin={a.origin === 'rule' ? 'rule' : a.origin} /></div>
      <p>{a.answer}</p>
      {(a.blocks ?? []).map((b: J, i: number) => {
        if (b.type === 'table') return (
          <div className="tbl-wrap" key={i}><table className="tbl"><thead><tr>{b.columns.map((c: string) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{b.rows.map((r: string[], j: number) => <tr key={j}>{r.map((c, k) => <td key={k}>{c}</td>)}</tr>)}</tbody></table></div>)
        if (b.type === 'list') return <ul key={i} style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.5 }}>{b.items.map((x: string) => <li key={x}>{x}</li>)}</ul>
        if (b.type === 'finding') return <div className="block risk" key={i}><h4>{b.title}</h4><p>{b.text}</p>{b.hypothesis && <span className="chip warn">гипотеза</span>}</div>
        if (b.type === 'quote') return <div key={i}><OriginChip origin={b.origin} /><blockquote className="quote">{b.text}<br /><small>{b.source}</small></blockquote></div>
        return null
      })}
      {(a.refs ?? []).filter((r: J) => r.item_id).slice(0, 3).map((r: J, i: number) => (
        <button className="src-link" key={i} onClick={() => onSource({ item_id: r.item_id, page: r.page })}><Icon name="file" size={14} /> {r.label}{r.page ? `, стр. ${r.page}` : ''}</button>
      ))}
    </div>
  )
}

export function Ask({ company, role, itemId, chips, onSource }: { company: string; role: string; itemId?: string; chips: string[]; onSource: (s: SourceRef) => void }) {
  const [q, setQ] = useState('')
  const [ans, setAns] = useState<J>(null)
  const [busy, setBusy] = useState(false)
  const go = async (text: string) => {
    if (!text.trim()) return
    setQ(text); setBusy(true)
    try { setAns(await api.ask(company, role, text, itemId)) } catch (e: any) { setAns({ answer: e.message, origin: 'rule', blocks: [] }) } finally { setBusy(false) }
  }
  return (
    <>
      <div className="q-chips">{chips.map((c) => <button key={c} onClick={() => go(c)}>{c}</button>)}</div>
      {ans && <AnswerView a={ans} onSource={onSource} />}
      <div className="ask-box"><input value={q} placeholder="Задайте свой вопрос" aria-label="Вопрос" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && go(q)} />
        <button aria-label="Отправить" disabled={busy} onClick={() => go(q)}><Icon name="send" size={18} /></button></div>
    </>
  )
}

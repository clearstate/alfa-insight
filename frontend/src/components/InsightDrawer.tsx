import { useEffect, useRef, useState } from 'react'
import { api, type J } from '../api'
import { Icon } from './Icon'
import { Ask } from './Assistant'
import { CONF, Legend, OriginChip, SEV, fmtDate, fmtNum } from './ui'
import type { SourceRef } from './Source'

type Props = { itemId: string; company: string; role: string; onClose: () => void; onSource: (s: SourceRef) => void; notify: (m: string) => void }

function Finding({ f, kind, evs, onEv }: { f: J; kind: string; evs: Record<string, J>; onEv: (id: string) => void }) {
  return (
    <div className={`block ${kind}`}>
      <div className="meta" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <OriginChip origin="ai" method={f.method} />
        <span className="chip">{SEV[f.severity]}</span>
        <span className="chip">{CONF[f.confidence]}</span>
        {f.hypothesis && <span className="chip warn">гипотеза</span>}
        <span className="chip">{f.horizon}</span>
      </div>
      <h4>{f.title}</h4>
      <p>{f.text}</p>
      <div className="meta" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {f.evidence.map((id: string) => <button key={id} className="src-link" onClick={() => onEv(id)}>{id}{evs[id]?.source?.page ? ` · стр. ${evs[id].source.page}` : ''}</button>)}
      </div>
    </div>
  )
}

export function InsightDrawer({ itemId, company, role, onClose, onSource, notify }: Props) {
  const [d, setD] = useState<J>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [voted, setVoted] = useState<string>('')
  const actionsRef = useRef<HTMLDivElement>(null)
  useEffect(() => { setD(null); setErr(''); api.insight(itemId, company, role).then(setD).catch((e) => setErr(e.message)) }, [itemId, company, role])

  const evs: Record<string, J> = Object.fromEntries((d?.evidence ?? []).map((e: J) => [e.id, e]))
  const openEv = (id: string) => { setOpen((o) => ({ ...o, evidence: true })); setTimeout(() => document.getElementById('ev-' + id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60) }
  const act = async (type: string) => { try { const r = await api.action(company, role, itemId, type); notify(`${r.message} № ${r.ticket}`) } catch (e: any) { notify(e.message) } }
  const vote = async (rating: 'up' | 'down') => { setVoted(rating); try { await api.feedback(company, role, itemId, rating, rating === 'down' ? 'irrelevant' : undefined); notify('Спасибо, оценка учтена') } catch (e: any) { notify(e.message) } }
  const tog = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }))

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="detail-drawer" onClick={(e) => e.stopPropagation()} aria-label="Подробный разбор">
        <div className="drawer-header">
          <div>
            {d && <span className={`tag ${d.type}`}>{{ risk: 'Требует внимания', opportunity: 'Возможность', event: 'Событие' }[d.type as string]}</span>}
            {d && <small>{fmtDate(d.what_happened?.published_at)}</small>}
            {d?.mode && <span className="chip ai">{d.mode === 'llm' ? 'AI-модель' : 'AI · правила'}</span>}
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть"><Icon name="close" /></button>
        </div>
        <div className="drawer-content">
          {err && <div className="err">{err}</div>}
          {!d && !err && <p className="lead">Агент собирает данные о компании, новости и позиции банка…</p>}
          {d && d.status === 'blocked' && <div className="note"><b>{d.headline}</b><br />{d.summary}</div>}
          {d && d.status === 'ok' && (
            <>
              <h2>{d.what_happened.title}</h2>
              <div className="for-you"><Icon name="spark" size={18} /><span>Для вашей компании: {d.headline}</span></div>
              <p className="lead">{d.summary}</p>
              <Legend />

              <section className="sec">
                <h3><span className="n">1</span>Что произошло</h3>
                <div className="meta" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                  <span className="chip fact">{d.what_happened.publisher}</span><span className="chip">{d.what_happened.reliability}</span>
                  {d.what_happened.synthetic && <span className="chip synthetic">синтетическая демо-новость</span>}
                </div>
                {d.what_happened.key_facts.map((k: J, i: number) => (
                  <div className="block" key={i}>
                    <div className="meta" style={{ display: 'flex', gap: 6 }}><OriginChip origin={k.status === 'confirmed' ? (d.what_happened.kind === 'bank' ? 'bank_data' : 'fact') : 'unconfirmed'} /></div>
                    <p>{k.text}</p>
                  </div>
                ))}
                {d.what_happened.status_notes.map((n: string) => <div className="note" style={{ marginTop: 9 }} key={n}>{n}</div>)}
                <div className="cta-row"><button className="btn small" onClick={() => onSource({ item_id: d.news_item_id })}><Icon name="file" size={15} /> Открыть первоисточник</button></div>
              </section>

              <section className="sec">
                <h3><span className="n">2</span>Почему это важно именно для вас</h3>
                {d.why_it_matters.map((w: J, i: number) => (
                  <div className="block" key={i}><div className="meta" style={{ display: 'flex', gap: 6 }}><OriginChip origin={w.origin} /></div><p>{w.statement}</p>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{w.evidence.map((id: string) => <button className="src-link" key={id} onClick={() => openEv(id)}>{id}</button>)}</div></div>
                ))}
                <div className="rel" style={{ marginTop: 10 }}><span>Релевантность для «{d.role_title}»: {d.relevance.relevance} из 100</span><i><b style={{ width: `${d.relevance.relevance}%` }} /></i></div>
              </section>

              <section className="sec">
                <h3><span className="n">3</span>Какие последствия возможны</h3>
                {d.consequences.risks.map((f: J) => <Finding key={'r' + f.index} f={f} kind="risk" evs={evs} onEv={openEv} />)}
                {d.consequences.opportunities.filter((f: J) => !d.consequences.risks.some((r: J) => r.index === f.index)).map((f: J) => <Finding key={'o' + f.index} f={f} kind="opportunity" evs={evs} onEv={openEv} />)}
                {d.consequences.notes.map((f: J) => <Finding key={'n' + f.index} f={f} kind="neutral" evs={evs} onEv={openEv} />)}
                {d.consequences.scenarios.length > 0 && (
                  <div className="tbl-wrap" style={{ marginTop: 12 }}><table className="tbl"><thead><tr><th>Сценарий</th><th>Условие</th><th>Эффект</th></tr></thead>
                    <tbody>{d.consequences.scenarios.map((s: J, i: number) => <tr key={i}><td><b>{s.name}</b></td><td>{s.condition}</td><td>{s.effect}</td></tr>)}</tbody></table></div>
                )}
              </section>

              <section className="sec">
                <h3><span className="n">4</span>Как это оценивает банк</h3>
                {!d.bank_view.has_position && <div className="note">{d.bank_view.note} Все выводы выше сформированы AI и не являются позицией банка.</div>}
                {d.bank_view.items.map((b: J, i: number) => (
                  <div className="block bank" key={i}>
                    <div className="meta" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}><OriginChip origin={b.origin} /><span className="chip">{fmtDate(b.published_at)}</span></div>
                    <p>{b.statement}</p>
                    <blockquote className="quote">{b.quote}</blockquote>
                    <button className="src-link" onClick={() => onSource({ item_id: b.item_id, page: b.page })}><Icon name="file" size={14} /> {b.doc_title}, стр. {b.page}</button>
                  </div>
                ))}
                {d.bank_view.indicators.length > 0 && (
                  <div className="tbl-wrap" style={{ marginTop: 12 }}><table className="tbl"><thead><tr><th>Показатель банка</th><th>Период</th><th>Значение</th><th>Документ</th></tr></thead>
                    <tbody>{d.bank_view.indicators.map((x: J) => (
                      <tr key={x.indicator + x.period}><td>{x.label}</td><td>{x.period}</td>
                        <td><b>{fmtNum(x.value)}</b> <small>{x.unit}</small>{x.superseded.length > 0 && <div><span className="chip warn">обновлено: было {x.superseded.map((s: J) => fmtNum(s.value)).join(' → ')}</span></div>}</td>
                        <td><button className="src-link" onClick={() => onSource({ item_id: x.item_id, page: x.page })}>{fmtDate(x.published_at)}, стр. {x.page}</button></td></tr>))}</tbody></table></div>
                )}
              </section>

              <section className="sec" ref={actionsRef}>
                <h3><span className="n">5</span>Что можно сделать</h3>
                {d.actions.map((a: J) => (
                  <div className="action" key={a.title}><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}><OriginChip origin="ai" method="rules" />{a.kind === 'monitor' && <span className="chip">наблюдение</span>}</div><b>{a.title}</b><p>{a.text}</p></div>
                ))}
                {d.offer && (
                  <div className="offer"><span className="chip synthetic">{d.offer.label}</span><b>{d.offer.title}</b><p style={{ fontSize: 13, color: 'var(--muted)' }}>{d.offer.text}</p></div>
                )}
                <div className="cta-row">
                  <button className="btn primary" onClick={() => act('manager')}>Связаться с менеджером</button>
                  <button className="btn" onClick={() => act('callback')}>Заказать звонок</button>
                  <button className="btn" onClick={() => act('request')}>Оставить заявку</button>
                </div>
              </section>

              <section className="sec">
                <h3><span className="n">6</span>На чём основан вывод</h3>
                <div className="acc"><button onClick={() => tog('evidence')}><span>Источники и доказательства ({d.evidence.length})</span><Icon name="chevron" size={18} /></button>
                  {open.evidence && <div className="acc-body">{d.evidence.map((e: J) => (
                    <div className="ev" id={'ev-' + e.id} key={e.id}><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}><span className="id">{e.id}</span><OriginChip origin={e.origin} /><small>{e.label}</small></div>
                      <div>{e.text}</div>
                      {e.source?.item_id && <button className="src-link" onClick={() => onSource({ item_id: e.source.item_id, page: e.source.page })}><Icon name="file" size={14} /> {e.source.title}{e.source.page ? `, стр. ${e.source.page}` : ''}</button>}
                      {e.source?.rule_id && <small>правило {e.source.rule_id}; основание: {(e.source.based_on ?? []).slice(0, 3).join('; ')}</small>}
                    </div>))}</div>}
                </div>
                <div className="acc"><button onClick={() => tog('checks')}><span>Проверки качества: {d.checks.items.filter((c: J) => c.status === 'pass').length} из {d.checks.items.length} пройдено</span><Icon name="chevron" size={18} /></button>
                  {open.checks && <div className="acc-body">{d.checks.items.map((c: J) => (
                    <div className="check" key={c.code}><span className={`dot ${c.status === 'pass' ? '' : c.status}`}><Icon name={c.status === 'pass' ? 'check' : 'alert'} size={13} /></span><span><b>{c.code}</b> — {c.detail}</span></div>))}</div>}
                </div>
                <div className="acc"><button onClick={() => tog('trace')}><span>Действия агента ({d.trace.steps.length} шагов, {Math.round(d.trace.total_ms)} мс)</span><Icon name="chevron" size={18} /></button>
                  {open.trace && <div className="acc-body">{d.trace.steps.map((s: J) => (
                    <div className="step" key={s.n}><i>{s.n}</i><span><b>{s.name}</b> <small>{s.kind}{s.status !== 'ok' ? ` · ${s.status}` : ''}</small><small>{s.summary}</small></span></div>))}</div>}
                </div>
                {d.data_gaps.length > 0 && <div className="note" style={{ marginTop: 10 }}><b>Ограничения данных.</b> {d.data_gaps.map((g: string) => g.replace(/\.$/, '') + '.').join(' ')}</div>}
              </section>

              <section className="sec">
                <h3>Уточнить</h3>
                <Ask company={company} role={role} itemId={itemId} chips={d.questions} onSource={onSource} />
              </section>
              <p className="disclaimer">{d.disclaimer}</p>
            </>
          )}
        </div>
        <div className="drawer-footer">
          <button className="btn" onClick={onClose}>Вернуться в ленту</button>
          <span className="spacer" />
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>Вывод полезен?</span>
          <button className={`btn small ${voted === 'up' ? 'dark' : ''}`} aria-label="Полезно" onClick={() => vote('up')}><Icon name="up" size={16} /></button>
          <button className={`btn small ${voted === 'down' ? 'dark' : ''}`} aria-label="Не по теме" onClick={() => vote('down')}><Icon name="down" size={16} /></button>
          <button className="btn primary" onClick={() => actionsRef.current?.scrollIntoView({ behavior: 'smooth' })}>Перейти к действиям <Icon name="arrow" size={16} /></button>
        </div>
      </aside>
    </div>
  )
}

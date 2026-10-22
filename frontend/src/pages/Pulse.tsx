import { useState } from 'react'
import type { J } from '../api'
import { Icon } from '../components/Icon'
import { Ask } from '../components/Assistant'
import type { SourceRef } from '../components/Source'

const TABS: [string, string][] = [['all', 'Все события'], ['risk', 'Риски'], ['opportunity', 'Возможности'], ['event', 'События'], ['bank', 'Аналитика банка']]

export function FeedCard({ c, onOpen }: { c: J; onOpen: (id: string) => void }) {
  const icon = c.type === 'risk' ? 'shield' : c.type === 'opportunity' ? 'trend' : c.is_bank ? 'bank' : 'news'
  return (
    <article className={`feed-card ${c.type}`} onClick={() => onOpen(c.id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen(c.id)}>
      <div className="card-top">
        <span className={`type-icon ${c.type}`}><Icon name={icon} /></span>
        <span className={`tag ${c.type}`}>{c.label}</span>
        {c.is_bank && <span className="chip bank">Аналитика Альфа-Банка</span>}
        {c.unconfirmed && <span className="chip warn">Не подтверждено</span>}
        {c.synthetic && <span className="chip synthetic">демо-новость</span>}
        <time>{c.time}</time>
      </div>
      <h3>{c.title}</h3>
      <div className="for-you"><Icon name="spark" size={17} /><span>{c.headline}</span></div>
      <p>{c.text}</p>
      <div className="metric-row">
        {c.metric ? <div className="m"><strong>{c.metric.value}</strong><span>{c.metric.label}</span></div> : <div className="m"><span>{c.source}{c.also_reported ? ` · ещё ${c.also_reported} публ.` : ''}</span></div>}
        <span className="rel">Релевантность {c.relevance}<i><b style={{ width: `${c.relevance}%` }} /></i></span>
      </div>
      <div className="card-foot">
        {c.has_bank_view && <span className="chip bank">Есть позиция банка</span>}
        <span className="chip">{c.confidence_label}</span>
        <button className="card-link" onClick={(e) => { e.stopPropagation(); onOpen(c.id) }}>Подробнее <Icon name="arrow" size={17} /></button>
      </div>
    </article>
  )
}

type Props = { user: J; company: J; role: J; feed: J | null; ctx: J | null; loading: boolean; onOpen: (id: string) => void; onAdd: () => void; onSource: (s: SourceRef) => void }

export function Pulse({ user, company, role, feed, ctx, loading, onOpen, onAdd, onSource }: Props) {
  const [tab, setTab] = useState('all')
  const cards: J[] = (feed?.cards ?? []).filter((c: J) => tab === 'all' || (tab === 'bank' ? c.is_bank : tab === 'event' ? c.type === 'event' && !c.is_bank : c.type === tab))
  const counts = feed?.counts ?? {}
  const topFactor = (ctx?.factors ?? []).filter((f: J) => f.level === 'high')[0]
  return (
    <main className="content">
      <section className="page-head">
        <div><p className="eyebrow"><Icon name="spark" size={16} /> Новостная аналитика</p><h1>Добрый день, {user.name.split(' ')[0]}</h1>
          <p>Событий, которые важны вашему бизнесу — с объяснением, чем они грозят или что дают именно этой компании.</p></div>
        <div className="summary-pill"><span className="summary-icon"><Icon name="shield" /></span><div><small>Ключевой признак компании</small><b>{topFactor ? topFactor.title : 'Высоких нет'}</b></div><span className="score" title="Событий, требующих внимания">{counts.risk ?? 0}</span></div>
      </section>

      <section className="stats-grid" aria-label="Показатели банка">
        {(ctx?.stats ?? []).map((s: J) => (
          <button key={s.label} className="stat-card" style={{ textAlign: 'left' }} onClick={() => onSource({ item_id: s.item_id, page: s.page })}>
            <span className="stat-label">{s.label}</span><strong>{s.value}</strong>
            <span className="stat-sub">обновлено {s.updated}{s.changed && <span className="chip warn">было {s.was}</span>}</span>
          </button>
        ))}
      </section>

      <div className="feed-layout">
        <section aria-label="Персональная лента">
          <div className="section-heading"><div><h2>Персональная лента</h2><span className="sub">Данные на {feed?.as_of_ru ?? '—'} · для роли «{role.title}»</span></div>
            <button className="btn small" onClick={onAdd}><Icon name="plus" size={16} /> Проверить свою новость</button></div>
          <div className="filter-tabs" role="tablist">
            {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{label}{k === 'risk' && counts.risk ? <span>{counts.risk}</span> : null}</button>)}
          </div>
          <div className="feed-list">
            {loading && <div className="empty">Подбираем события под вашу компанию…</div>}
            {!loading && cards.length === 0 && <div className="empty">В этой категории пока нет событий, значимых для компании. Нерелевантные материалы скрыты: {feed?.hidden_low_relevance ?? 0}.</div>}
            {!loading && cards.map((c) => <FeedCard key={c.id} c={c} onOpen={onOpen} />)}
          </div>
          <p className="disclaimer">{feed?.disclaimer}</p>
        </section>

        <aside className="right-rail">
          <div className="rail-card">
            <div className="rail-title"><span className="assistant-icon"><Icon name="spark" /></span><div><h3>Бизнес-ассистент</h3><p>Отвечает по данным компании и аналитике банка</p></div></div>
            <p className="rail-question">Что хотите узнать?</p>
            <Ask company={company.company_id} role={role.code} chips={['Как ставка влияет на мою компанию?', 'Что с курсом и внешней торговлей?', 'Что с расходами на персонал?']} onSource={onSource} />
          </div>
          <div className="rail-card">
            <div className="rail-title"><span className="calendar">{(ctx?.calendar?.[0]?.date ?? '').slice(8, 10) || '—'}</span><div><h3>Ближайшее важное</h3><p>Из материалов банка</p></div></div>
            {(ctx?.calendar ?? []).map((e: J) => (
              <div className="deadline" key={e.date}><span /><div><b>{e.title}</b><p>{new Date(e.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} · {e.detail}</p></div></div>))}
          </div>
          <div className="rail-card">
            <div className="rail-title"><span className="summary-icon"><Icon name="building" /></span><div><h3>Какие признаки учтены</h3><p>Правила на данных банка о компании</p></div></div>
            <div style={{ marginTop: 10 }}>
              {(ctx?.factors ?? []).filter((f: J) => f.level !== 'none').map((f: J) => (
                <div className="factor-row" key={f.code}><b>{f.title}</b><span className={`lvl ${f.level}`}>{f.level_ru}</span><small>{f.rationale.split('. ')[0]}.</small></div>))}
            </div>
            {(ctx?.data_gaps ?? []).length > 0 && <p className="disclaimer">Ограничения данных: {(ctx.data_gaps as string[]).slice(0, 3).join('; ')}.</p>}
          </div>
        </aside>
      </div>
    </main>
  )
}

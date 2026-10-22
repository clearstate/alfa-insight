import type { J } from '../api'
import { Icon } from '../components/Icon'

type Props = { user: J; company: J; feed: J | null; onOpenFeed: () => void; onOpen: (id: string) => void; go: (p: string) => void }

export function Home({ user, company, feed, onOpenFeed, onOpen, go }: Props) {
  const c = feed?.counts ?? {}
  const top: J[] = (feed?.cards ?? []).slice(0, 3)
  return (
    <main className="content">
      <section className="page-head"><div><p className="eyebrow"><Icon name="grid" size={16} /> Главная</p><h1>{company.name}</h1><p>{company.okved_name}. {company.city}.</p></div></section>

      <section className="entry-banner" aria-label="Новостная аналитика">
        <div>
          <h2>Что происходит на рынке — и что это значит для вашей компании</h2>
          <p>Новости и аналитика Альфа-Банка, отобранные под ваш бизнес: что произошло, чем это грозит или что даёт, что думает банк и что можно сделать.</p>
          <div className="entry-counts"><span>{c.risk ?? 0} требуют внимания</span><span>{c.opportunity ?? 0} возможностей</span><span>{c.bank ?? 0} материала банка</span></div>
        </div>
        <button className="btn primary" style={{ minHeight: 52, padding: '0 24px', fontSize: 15 }} onClick={onOpenFeed}>Открыть аналитику <Icon name="arrow" size={18} /></button>
      </section>

      <div className="section-heading" style={{ marginTop: 30 }}><div><h2>Главное сегодня</h2><span className="sub">Три самых значимых для вашей компании события</span></div></div>
      <div className="mini-grid">
        {top.map((t) => (
          <button className={`mini-card ${t.type}`} key={t.id} onClick={() => onOpen(t.id)}>
            <span className={`tag ${t.type}`} style={{ justifySelf: 'start' }}>{t.label}</span><h4>{t.headline}</h4><p>{t.title}</p>
          </button>))}
        {top.length === 0 && <div className="empty" style={{ gridColumn: '1/-1' }}>Загружаем ленту…</div>}
      </div>

      <div className="tiles">
        <button className="tile" onClick={() => go('accounts')}><Icon name="wallet" /><b>Счета и платежи</b><span>Остатки, переводы и выписки (демонстрационный раздел)</span></button>
        <button className="tile" onClick={() => go('analytics')}><Icon name="chart" /><b>Аналитика банка</b><span>Прогнозы по ставке, курсу, инфляции и актуальные версии</span></button>
        <button className="tile" onClick={onOpenFeed}><Icon name="spark" /><b>Новостная аналитика</b><span>Персональная лента с объяснением влияния на бизнес</span></button>
      </div>
      <p className="disclaimer">{user.name}, {user.role_title}. Данные демонстрационные: профиль компании построен по обезличенным данным кейса.</p>
    </main>
  )
}

import type { J } from '../api'
import { Icon } from '../components/Icon'
import { plural } from '../components/ui'

const count = (n: number, forms: [string, string, string]) => `${n} ${plural(n, forms)}`

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
          <div className="entry-counts"><span>{count(c.risk ?? 0, ['требует внимания', 'требуют внимания', 'требуют внимания'])}</span><span>{count(c.opportunity ?? 0, ['возможность', 'возможности', 'возможностей'])}</span><span>{count(c.bank ?? 0, ['материал банка', 'материала банка', 'материалов банка'])}</span></div>
        </div>
        <button className="btn primary" style={{ minHeight: 52, padding: '0 24px', fontSize: 15 }} onClick={onOpenFeed}>Открыть аналитику <Icon name="arrow" size={18} /></button>
      </section>

      <section className="brief" aria-label="Утренняя сводка">
        <div className="brief-head"><h2>Сводка на {feed?.as_of_ru?.replace(' г.', '') ?? 'сегодня'}</h2><small>Три события, важные для компании сегодня, и что с ними сделать</small></div>
        {top.length > 0 ? (
          <ol className="brief-list">
            {top.map((t, i) => (
              <li key={t.id}><button className="brief-item" onClick={() => onOpen(t.id)}>
                <span className="brief-n">{i + 1}</span>
                <span>
                  <span className={`tag ${t.type}`}>{t.label}</span>
                  <h4>{t.headline}</h4>
                  <p>{t.title}{(t.reasons ?? []).length > 0 ? ` · почему вам: ${t.reasons.join(', ')}` : ''}</p>
                  {t.action && <p className="brief-do"><b>Что сделать:</b> {t.action}</p>}
                </span>
              </button></li>))}
          </ol>
        ) : <div className="empty" style={{ marginTop: 12 }}>{feed ? 'Значимых для компании событий пока нет' : 'Загружаем ленту…'}</div>}
      </section>

      <div className="tiles">
        <button className="tile" onClick={() => go('accounts')}><Icon name="wallet" /><b>Счета и платежи</b><span>Платёжные потоки, контрагенты и продукты компании</span></button>
        <button className="tile" onClick={() => go('analytics')}><Icon name="chart" /><b>Аналитика банка</b><span>Прогнозы по ставке, курсу, инфляции и актуальные версии</span></button>
        <button className="tile" onClick={onOpenFeed}><Icon name="spark" /><b>Новостная аналитика</b><span>Персональная лента с объяснением влияния на бизнес</span></button>
      </div>
      <p className="disclaimer">{user.name}, {user.role_title}. Данные демонстрационные: профиль компании построен по обезличенным данным кейса.</p>
    </main>
  )
}

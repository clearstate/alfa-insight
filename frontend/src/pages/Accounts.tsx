import { useEffect, useState } from 'react'
import { api, type J } from '../api'
import { Icon } from '../components/Icon'
import { plural } from '../components/ui'

const money = (v: number) => {
  if (v >= 1e9) return `${(v / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} млрд ₽`
  if (v >= 1e6) return `${(v / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн ₽`
  return `${Math.round(v).toLocaleString('ru-RU')} ₽`
}
const pct = (v: number | null) => (v == null ? 'нет данных' : `${(v * 100).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`)
const ops = (n: number) => `${n.toLocaleString('ru-RU')} ${plural(n, ['операция', 'операции', 'операций'])}`

function Side({ title, d }: { title: string; d: J }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <p className="sub">{money(d.total_amt)} · операций: {d.total_cnt.toLocaleString('ru-RU')} · контрагентов: {d.n_counterparties}{d.known_coverage != null && ` · профиль известен для ${pct(d.known_coverage)} оборота`}</p>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Контрагент</th><th>Отрасль (ОКВЭД)</th><th>Регион</th><th style={{ textAlign: 'right' }}>Сумма</th><th style={{ textAlign: 'right' }}>Операций</th><th style={{ textAlign: 'right' }}>Доля</th></tr></thead>
        <tbody>{d.top.length === 0 && <tr><td colSpan={6}><small style={{ color: 'var(--muted)' }}>Платежей с контрагентами в данных нет</small></td></tr>}
          {d.top.map((r: J, i: number) => (
          <tr key={i}>
            <td><b>{r.counterparty}</b></td>
            <td>{r.known ? <>{r.okved_code}{r.okved_name && <><br /><small style={{ color: 'var(--muted)' }}>{r.okved_name.length > 70 ? r.okved_name.slice(0, 70) + '…' : r.okved_name}</small></>}</> : <small style={{ color: 'var(--muted)' }}>нет в выборке</small>}</td>
            <td>{r.region ?? '—'}</td>
            <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{money(r.amount)}</td>
            <td style={{ textAlign: 'right' }}>{r.count.toLocaleString('ru-RU')}</td>
            <td style={{ textAlign: 'right' }}><span className="share"><i style={{ width: `${Math.min(100, r.share * 100)}%` }} /></span>{pct(r.share)}</td>
          </tr>))}</tbody>
      </table></div>
    </section>
  )
}

export function Accounts({ company }: { company: J }) {
  const [d, setD] = useState<J>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let alive = true
    setD(null); setErr('')
    api.payments(company.company_id).then((r) => alive && setD(r)).catch((e) => alive && setErr(e.message))
    return () => { alive = false }
  }, [company.company_id])
  return (
    <main className="content">
      <section className="page-head"><div><p className="eyebrow"><Icon name="wallet" size={16} /> Счета и платежи</p><h1>Платёжные потоки</h1>
        <p>{company.name} · {company.headline}</p></div></section>
      {err && <div className="err" style={{ marginTop: 20 }}>{err}</div>}
      {!d && !err && <div className="empty" style={{ marginTop: 24 }}>Загружаем платежи компании…</div>}
      {d && (
        <>
          <section className="balance-overview">
            <div><span>Поступления от контрагентов</span><strong>{money(d.incoming.total_amt)}</strong><small><Icon name="check" size={17} /> {ops(d.incoming.total_cnt)} от {d.incoming.n_counterparties} {plural(d.incoming.n_counterparties, ['плательщика', 'плательщиков', 'плательщиков'])}</small></div>
            <div><span>Списания контрагентам</span><strong>{money(d.outgoing.total_amt)}</strong><small style={{ color: '#ffb4ad' }}>{ops(d.outgoing.total_cnt)}, {d.outgoing.n_counterparties} {plural(d.outgoing.n_counterparties, ['получатель', 'получателя', 'получателей'])}</small></div>
            {d.self_transfers && <div><span>Переводы между своими счетами</span><strong style={{ fontSize: 26 }}>{money(d.self_transfers.pay_amt)}</strong><small style={{ color: '#aeb2b9' }}>не входят в обороты</small></div>}
          </section>
          <section className="account-cards">
            <article className="account-card primary"><div className="account-card-top"><span className="account-icon"><Icon name="building" /></span></div><p>Выручка за 2025 год</p>
              <strong>{d.revenue != null ? money(d.revenue) : 'нет данных'}</strong><small>по данным банка, в рублях за отчётный год</small></article>
            <article className="account-card"><div className="account-card-top"><span className="account-icon"><Icon name="users" /></span></div><p>Сотрудники (ФНС)</p>
              <strong style={{ fontSize: 20 }}>{d.workers ?? 'нет данных'}</strong><small>{d.group_size && d.group_size > 1 ? `в группе компаний: ${d.group_size}` : 'вне группы компаний'}</small></article>
            <article className="account-card"><div className="account-card-top"><span className="account-icon"><Icon name="trend" /></span></div><p>Внешняя торговля (ФТС)</p>
              <strong style={{ fontSize: 20 }}>{d.countries.length ? d.countries.join(', ') : 'нет данных'}</strong><small>страны в данных таможни</small></article>
          </section>
          <section className="card"><h2>Продукты в Альфа-Банке</h2><p className="sub">По данным банка о клиенте — от них зависит, какие события важны компании</p>
            <div className="product-chips">{d.products.map((p: J) => <span key={p.code} className={`chip ${p.active ? "ok" : "off"}`} title={p.active ? "Подключено" : "Не подключено"}>{p.active ? <Icon name="check" size={13} /> : null}{p.title}{p.active ? "" : " — нет"}</span>)}</div></section>
          <Side title="Крупнейшие плательщики" d={d.incoming} />
          <Side title="Крупнейшие получатели платежей" d={d.outgoing} />
          <p className="disclaimer">{d.note}</p>
        </>
      )}
    </main>
  )
}

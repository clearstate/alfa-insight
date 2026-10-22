import { Icon } from '../components/Icon'

export function Accounts({ notify }: { notify: (m: string) => void }) {
  return (
    <main className="content">
      <section className="page-head"><div><p className="eyebrow"><Icon name="wallet" size={16} /> Счета и платежи</p><h1>Управление деньгами</h1>
        <p>Все счета, операции и платежи компании в одном окне.</p><span className="demo-note"><Icon name="alert" size={14} /> Демонстрационный раздел: суммы условные, к кейсу не относятся</span></div>
        <button className="btn primary" onClick={() => notify('Демо: создание платежа не подключено')}>Новый платёж <Icon name="arrow" size={18} /></button></section>
      <section className="balance-overview"><div><span>Общий доступный остаток</span><strong>12 840 560,42 ₽</strong><small><Icon name="check" size={17} /> Все счета работают</small></div>
        <div className="balance-actions"><button onClick={() => notify('Демо: перевод')}><Icon name="arrow" />Перевести</button><button onClick={() => notify('Демо: выписка')}><Icon name="file" />Выписка</button></div></section>
      <section className="account-cards">
        <article className="account-card primary"><div className="account-card-top"><span className="account-icon"><Icon name="wallet" /></span><span className="chip bank">Основной</span></div><p>Расчётный счёт</p><strong>9 418 240,42 ₽</strong><small>•• 4582 · RUB</small></article>
        <article className="account-card"><div className="account-card-top"><span className="account-icon"><Icon name="wallet" /></span><span className="chip ok">Резервный</span></div><p>Накопительный счёт</p><strong>3 240 000 ₽</strong><small>•• 9014 · RUB</small></article>
        <article className="account-card"><div className="account-card-top"><span className="account-icon"><Icon name="wallet" /></span><span className="chip">Валютный</span></div><p>Валютный счёт</p><strong>2 140,00 $</strong><small>•• 1178 · USD</small></article>
      </section>
      <section className="card"><h2>Последние операции</h2><p className="sub">Демонстрационные данные</p>
        <div className="tbl-wrap" style={{ overflowX: 'auto' }}>
          <div className="tx-row tx-head"><span>Контрагент</span><span>Назначение</span><span>Дата</span><span style={{ textAlign: 'right' }}>Сумма</span></div>
          <div className="tx-row"><b>ООО «Горизонт»</b><span>Оплата по договору №143</span><span>Сегодня, 11:42</span><strong className="positive">+840 000 ₽</strong></div>
          <div className="tx-row"><b>ООО «Вектор Снаб»</b><span>Оплата материалов</span><span>Сегодня, 09:18</span><strong>−284 500 ₽</strong></div>
          <div className="tx-row"><b>ФНС России</b><span>Налоговый платёж</span><span>Вчера, 16:05</span><strong>−168 200 ₽</strong></div>
        </div></section>
    </main>
  )
}

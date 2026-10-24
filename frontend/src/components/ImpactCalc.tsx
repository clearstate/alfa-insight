import { useState } from 'react'
import type { J } from '../api'

const rub = (mln: number) => `${mln.toLocaleString('ru-RU', { maximumFractionDigits: mln < 10 ? 2 : 1 })} млн ₽`
const pctTxt = (v: number) => `${v.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`

/** «Влияние в рублях»: пользователь вводит свою сумму, расчёт — по прогнозу ключевой ставки банка из разбора.
 *  Ориентир: плавающая ставка = ключевая + маржа банка (маржа не учитывается), доходность депозита следует за ключевой. */
export function ImpactCalc({ kind, indicators }: { kind: 'debt' | 'deposit'; indicators: J[] }) {
  const kr = (period: string) => indicators.find((x: J) => x.indicator === 'key_rate_eoy' && x.period === period)?.value as number | undefined
  const now = kr('2026'), next = kr('2027')
  const [amount, setAmount] = useState(kind === 'debt' ? 100 : 50)
  if (now == null) return null
  const v = Number.isFinite(amount) && amount > 0 ? amount : 0
  const perPoint = v * 0.01
  const delta = next != null ? now - next : null
  return (
    <div className="impact">
      <div className="impact-head"><b>Влияние в рублях</b><small>ориентир по прогнозу ключевой ставки банка</small></div>
      <label className="impact-input">
        {kind === 'debt' ? 'Долг по плавающей ставке' : 'Свободные средства на депозитах'}
        <span><input type="number" min={0} step={10} value={amount} onChange={(e) => setAmount(Number(e.target.value))} aria-label="Сумма, млн рублей" /> млн ₽</span>
      </label>
      {kind === 'debt' ? (
        <ul>
          <li>Каждый 1 п.п. ключевой ставки — <b>≈ {rub(perPoint)}</b> процентов в год.</li>
          <li>При ставке {pctTxt(now)} до конца 2026 г. (прогноз банка) проценты по ключевой части — <b>≈ {rub(v * now / 100)}</b> в год.</li>
          {delta != null && delta > 0 && <li>Если ставка снизится до {pctTxt(next!)} к концу 2027 г., расходы уменьшатся на <b>≈ {rub(v * delta / 100)}</b> в год.</li>}
        </ul>
      ) : (
        <ul>
          <li>При ставке {pctTxt(now)} доход от размещения — до <b>≈ {rub(v * now / 100)}</b> в год (ставки депозитов ниже ключевой).</li>
          {delta != null && delta > 0 && <li>При снижении ставки до {pctTxt(next!)} к концу 2027 г. доход новых размещений станет меньше на <b>≈ {rub(v * delta / 100)}</b> в год — срок стоит выбирать заранее.</li>}
        </ul>
      )}
      <small className="impact-note">{kind === 'debt' ? 'Маржа банка и фиксированная часть долга не учитываются — сверьте с договорами.' : 'Расчёт до налогов; фактическая ставка зависит от срока и суммы.'}</small>
    </div>
  )
}

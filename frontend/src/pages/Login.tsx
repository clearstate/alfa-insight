import { useEffect, useState } from 'react'
import { api, setToken, type J } from '../api'

export function Login({ onDone }: { onDone: (u: J) => void }) {
  const [accounts, setAccounts] = useState<J[]>([])
  const [login, setLogin] = useState('demo')
  const [password, setPassword] = useState('demo')
  const [err, setErr] = useState('')
  useEffect(() => { api.accounts().then((r) => setAccounts(r.accounts)).catch(() => {}) }, [])
  const go = async (l = login, p = password) => {
    setErr('')
    try { const r = await api.login(l, p); setToken(r.token); onDone(r.user) } catch (e: any) { setErr(e.message) }
  }
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={(e) => { e.preventDefault(); go() }}>
        <div className="brand-row"><span className="brand-mark" style={{ display: 'grid', placeItems: 'center', background: 'var(--red)', borderRadius: 9, transform: 'skew(-5deg)', fontStyle: 'italic', fontWeight: 900 }}>A</span> А-Бизнес</div>
        <h1>Вход в интернет-банк</h1>
        <p className="lead" style={{ fontSize: 14 }}>Демонстрационный вход. Пароль всех учётных записей — demo.</p>
        <label className="field">Логин<input value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" /></label>
        <label className="field">Пароль<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {err && <div className="err">{err}</div>}
        <button className="btn primary" type="submit">Войти</button>
        <div className="login-accounts" aria-label="Демо-учётные записи">
          <small style={{ color: 'var(--muted)' }}>Быстрый вход под ролью:</small>
          {accounts.map((a) => <button type="button" key={a.login} onClick={() => go(a.login, 'demo')}><span><b>{a.name}</b> · {a.role_title}</span><small>{a.companies} комп.</small></button>)}
        </div>
      </form>
    </div>
  )
}

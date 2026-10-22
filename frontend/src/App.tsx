import { useCallback, useEffect, useRef, useState } from 'react'
import { api, hasToken, setToken, type J } from './api'
import { Icon } from './components/Icon'
import { InsightDrawer } from './components/InsightDrawer'
import { SourceModal, type SourceRef } from './components/Source'
import { AddNews } from './components/AddNews'
import { Login } from './pages/Login'
import { Home } from './pages/Home'
import { Pulse } from './pages/Pulse'
import { Analytics } from './pages/Analytics'
import { Accounts } from './pages/Accounts'

type Page = 'home' | 'pulse' | 'analytics' | 'accounts'

export default function App() {
  const [user, setUser] = useState<J>(null)
  const [booting, setBooting] = useState(hasToken())
  const [page, setPage] = useState<Page>('home')
  const [companyId, setCompanyId] = useState('')
  const [roleCode, setRoleCode] = useState('')
  const [companyOpen, setCompanyOpen] = useState(false)
  const [roleOpen, setRoleOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const [accounts, setAccounts] = useState<J[]>([])
  const [feed, setFeed] = useState<J>(null)
  const [ctx, setCtx] = useState<J>(null)
  const [loading, setLoading] = useState(false)
  const [openItem, setOpenItem] = useState<string | null>(null)
  const [source, setSource] = useState<SourceRef | null>(null)
  const [adding, setAdding] = useState(false)
  const [notice, setNotice] = useState('')

  const notify = useCallback((m: string) => { setNotice(m); window.setTimeout(() => setNotice(''), 3200) }, [])
  const start = (u: J) => {
    setUser(u); setCompanyId(u.companies[0]?.company_id ?? ''); setRoleCode(u.role); setBooting(false)
    setPage('home'); setOpenItem(null); setSource(null); setAdding(false); setFeed(null); setCtx(null)
  }
  const closeMenus = () => { setCompanyOpen(false); setRoleOpen(false); setUserOpen(false) }
  const goPage = (p: Page) => { closeMenus(); setPage(p) }
  const switchUser = async (login: string) => {
    closeMenus()
    try { const r = await api.login(login, 'demo'); setToken(r.token); start(r.user); notify(`Вы вошли как ${r.user.name}`) } catch (e: any) { notify(e.message) }
  }
  useEffect(() => {
    const expired = () => { setUser(null); setFeed(null); setCtx(null); setOpenItem(null); setSource(null); setAdding(false); notify('Сессия истекла — войдите снова') }
    window.addEventListener('auth-expired', expired)
    return () => window.removeEventListener('auth-expired', expired)
  }, [notify])
  useEffect(() => { if (user) api.accounts().then((r) => setAccounts(r.accounts)).catch(() => {}) }, [user])
  // Escape закрывает только верхний слой: модальное окно → панель разбора → меню
  const layers = useRef({ source: false, adding: false, item: false, menu: false })
  layers.current = { source: !!source, adding, item: !!openItem, menu: companyOpen || roleOpen || userOpen }
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const l = layers.current
      if (l.source) setSource(null)
      else if (l.adding) setAdding(false)
      else if (l.menu) closeMenus()
      else if (l.item) setOpenItem(null)
    }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [])
  useEffect(() => {
    if (!user || !companyId) return
    let alive = true
    setLoading(true)
    Promise.all([api.feed(companyId, roleCode, 'all'), api.context(companyId, roleCode)])
      .then(([f, c]) => { if (alive) { setFeed(f); setCtx(c) } })
      .catch((e) => { if (e.status !== 401) notify(e.message) }).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [user, companyId, roleCode, notify])

  if (booting) return null
  if (!user) return <>{<Login onDone={start} />}{notice && <div className="toast" role="status">{notice}</div>}</>
  const company = user.companies.find((c: J) => c.company_id === companyId) ?? user.companies[0]
  const role = user.roles.find((r: J) => r.code === roleCode) ?? user.roles[0]
  const riskCount = feed?.counts?.risk ?? 0
  const initials = user.name.split(' ').map((p: string) => p[0]).join('').slice(0, 2).toUpperCase()
  const logout = () => { closeMenus(); setToken(null); setUser(null); setFeed(null); setCtx(null); setOpenItem(null) }
  const anyMenu = companyOpen || roleOpen || userOpen

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="А-Бизнес"><span className="brand-mark">A</span><span className="brand-name">Бизнес</span></div>
        <nav className="main-nav" aria-label="Основная навигация">
          <button className={`nav-item ${page === 'home' ? 'active' : ''}`} onClick={() => goPage('home')}><Icon name="grid" /><span>Главная</span></button>
          <button className={`nav-item featured ${page === 'pulse' ? 'active' : ''}`} onClick={() => goPage('pulse')}><Icon name="pulse" /><span>Новостная аналитика</span>{riskCount > 0 && <span className="nav-badge">{riskCount}</span>}</button>
          <button className={`nav-item ${page === 'analytics' ? 'active' : ''}`} onClick={() => goPage('analytics')}><Icon name="chart" /><span>Аналитика банка</span></button>
          <button className={`nav-item ${page === 'accounts' ? 'active' : ''}`} onClick={() => goPage('accounts')}><Icon name="wallet" /><span>Счета и платежи</span></button>
          <button className="nav-item" disabled><Icon name="file" /><span>Документы</span></button>
          <button className="nav-item" disabled><Icon name="users" /><span>Сотрудники</span></button>
        </nav>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={logout} title="Выйти из системы"><Icon name="logout" /><span>Выйти</span></button>
          <div className="support"><span className="support-dot" /><div><b>Поддержка бизнеса</b><small>Ответим за 2 минуты</small></div></div>
        </div>
      </aside>

      <div className="workspace">
        {anyMenu && <div className="click-away" onClick={closeMenus} />}
        <header className="topbar">
          <div className="company-switcher">
            <div className="select-wrap">
              <button className="select-button" onClick={() => { setCompanyOpen(!companyOpen); setRoleOpen(false); setUserOpen(false) }} aria-haspopup="listbox" aria-expanded={companyOpen}>
                <span className="company-logo">{company.letter}</span><span><b>{company.name}</b><small>{company.headline}</small></span><Icon name="chevron" size={18} />
              </button>
              {companyOpen && <div className="dropdown company-dropdown" role="listbox">
                <p className="dropdown-title">Выберите компанию</p>
                {user.companies.map((c: J) => (
                  <button key={c.company_id} role="option" aria-selected={c.company_id === companyId} className={`dropdown-row ${c.company_id === companyId ? 'chosen' : ''}`} onClick={() => { setCompanyId(c.company_id); setCompanyOpen(false) }}>
                    <span className="company-logo small">{c.letter}</span><span><b>{c.name}</b><small>{c.headline} · {c.region}</small></span>{c.company_id === companyId && <Icon name="check" size={18} />}
                  </button>))}
              </div>}
            </div>
            <div className="select-wrap role-wrap">
              <button className="role-button" onClick={() => { setRoleOpen(!roleOpen); setCompanyOpen(false); setUserOpen(false) }}><span>{role.title}</span><Icon name="chevron" size={18} /></button>
              {roleOpen && <div className="dropdown role-dropdown">
                <p className="dropdown-title">Роль пользователя</p>
                {user.roles.map((r: J) => (
                  <button key={r.code} className={`dropdown-row plain ${r.code === roleCode ? 'chosen' : ''}`} onClick={() => { setRoleCode(r.code); setRoleOpen(false) }}><span>{r.title}</span>{r.code === roleCode && <Icon name="check" size={18} />}</button>))}
              </div>}
            </div>
          </div>
          <div className="top-actions">
            <button className="entry-button" onClick={() => goPage('pulse')} aria-label="Новостная аналитика"><Icon name="spark" size={18} /><span>Новостная аналитика</span>{riskCount > 0 && <b>{riskCount}</b>}</button>
            <button className="icon-button notification" aria-label="Уведомления: открыть аналитику" title="Новые события в аналитике" onClick={() => goPage('pulse')}><Icon name="bell" />{riskCount > 0 && <i />}</button>
            <div className="select-wrap user-wrap">
              <button className="avatar-button" onClick={() => { setUserOpen(!userOpen); setCompanyOpen(false); setRoleOpen(false) }} aria-haspopup="menu" aria-expanded={userOpen}>
                <span className="avatar">{initials}</span><span className="avatar-copy"><b>{user.name}</b><small>{role.title}</small></span><Icon name="chevron" size={17} />
              </button>
              {userOpen && <div className="dropdown user-dropdown" role="menu">
                <p className="dropdown-title">Сменить пользователя</p>
                {accounts.map((a) => (
                  <button key={a.login} role="menuitem" className={`dropdown-row ${a.login === user.user_id ? 'chosen' : ''}`} onClick={() => a.login !== user.user_id && switchUser(a.login)}>
                    <span className="avatar small">{a.name.split(' ').map((x: string) => x[0]).join('').slice(0, 2).toUpperCase()}</span><span><b>{a.name}</b><small>{a.role_title} · компаний: {a.companies}</small></span>{a.login === user.user_id && <Icon name="check" size={18} />}
                  </button>))}
                <p className="dropdown-title">Роль</p>
                {user.roles.map((r: J) => (
                  <button key={'r' + r.code} role="menuitem" className={`dropdown-row plain ${r.code === roleCode ? 'chosen' : ''}`} onClick={() => { setRoleCode(r.code); closeMenus() }}><span>{r.title}</span>{r.code === roleCode && <Icon name="check" size={18} />}</button>))}
                <button role="menuitem" className="dropdown-row logout-row" onClick={logout}><Icon name="logout" size={20} /><span><b>Выйти</b></span></button>
              </div>}
            </div>
          </div>
        </header>

        {page === 'home' && <Home user={user} company={company} feed={feed} onOpenFeed={() => setPage('pulse')} onOpen={setOpenItem} go={(p) => setPage(p as Page)} />}
        {page === 'pulse' && <Pulse user={user} company={company} role={role} feed={feed} ctx={ctx} loading={loading} onOpen={setOpenItem} onAdd={() => setAdding(true)} onSource={setSource} />}
        {page === 'analytics' && <Analytics onSource={setSource} />}
        {page === 'accounts' && <Accounts notify={notify} />}
      </div>

      {openItem && <InsightDrawer key={openItem + companyId + roleCode} itemId={openItem} company={companyId} role={roleCode} onClose={() => setOpenItem(null)} onSource={setSource} notify={notify} />}
      {source && <SourceModal s={source} onClose={() => setSource(null)} />}
      {adding && <AddNews onClose={() => setAdding(false)} onOpen={(id) => { setAdding(false); setOpenItem(id) }} />}
      {notice && <div className="toast" role="status"><Icon name="check" size={18} />{notice}</div>}
    </div>
  )
}

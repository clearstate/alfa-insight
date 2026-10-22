// Тонкий клиент API. Токен хранится в памяти и sessionStorage (демо-вход).
export type J = any

let token: string | null = (() => { try { return sessionStorage.getItem('ai_token') } catch { return null } })()
export const setToken = (t: string | null) => {
  token = t
  try { t ? sessionStorage.setItem('ai_token', t) : sessionStorage.removeItem('ai_token') } catch { /* ignore */ }
}
export const hasToken = () => !!token

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message) }
}

async function call(path: string, init?: RequestInit): Promise<J> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
  const data = await res.json().catch(() => ({}))
  if (res.status === 401 && token && !path.startsWith('/api/auth/')) {
    setToken(null)
    window.dispatchEvent(new Event('auth-expired'))   // сессия истекла или сервер перезапущен — вернуть на экран входа
  }
  if (!res.ok) throw new ApiError(res.status, data?.error?.code ?? 'error', data?.error?.message ?? 'Ошибка запроса')
  return data
}
const qs = (o: Record<string, string | number | undefined>) =>
  Object.entries(o).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')

export const api = {
  accounts: () => call('/api/auth/accounts'),
  login: (login: string, password: string) => call('/api/auth/login', { method: 'POST', body: JSON.stringify({ login, password }) }),
  me: () => call('/api/me'),
  feed: (company: string, role: string, tab: string) => call(`/api/feed?${qs({ company, role, tab })}`),
  context: (company: string, role: string) => call(`/api/context?${qs({ company, role })}`),
  insight: (id: string, company: string, role: string) => call(`/api/insights/${id}?${qs({ company, role })}`),
  ask: (company: string, role: string, question: string, item_id?: string) =>
    call('/api/ask', { method: 'POST', body: JSON.stringify({ company, role, question, item_id }) }),
  feedback: (company: string, role: string, item_id: string, rating: 'up' | 'down', reason?: string) =>
    call('/api/feedback', { method: 'POST', body: JSON.stringify({ company, role, item_id, rating, reason }) }),
  action: (company: string, role: string, item_id: string, type: string, note?: string) =>
    call('/api/actions', { method: 'POST', body: JSON.stringify({ company, role, item_id, type, note }) }),
  macro: () => call('/api/analytics/macro'),
  source: (id: string, page?: number | null) => call(`/api/sources/${id}?${qs({ page: page ?? undefined })}`),
  ingest: (text: string, title: string) => call('/api/news/ingest', { method: 'POST', body: JSON.stringify({ text, title }) }),
  metrics: () => call('/api/metrics'),
}

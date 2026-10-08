// 统一的接口请求封装：token 存取 + JSON 请求 + 错误归一化
const TOKEN_KEY = 'scr_token'
const USER_KEY = 'scr_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function isAdmin() {
  return getUser()?.role === 'admin'
}

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  const text = await response.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }

  if (!response.ok) {
    if (response.status === 401) clearSession()
    const message = data?.detail || `请求失败（HTTP ${response.status}）`
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message))
  }
  return data
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body ?? {}),
  put: (path, body) => request('PUT', path, body ?? {}),
  del: (path) => request('DELETE', path),
}

// 轮询工具：定时拉取，组件卸载时自动停止
export function startPolling(fn, intervalMs = 3000) {
  let timer = null
  let stopped = false

  const tick = async () => {
    if (stopped) return
    try {
      await fn()
    } catch {
      // 轮询期间的错误静默处理，避免打断界面
    }
    if (!stopped) timer = setTimeout(tick, intervalMs)
  }
  tick()

  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
  }
}

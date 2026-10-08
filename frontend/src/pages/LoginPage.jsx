import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getToken, setSession } from '../api.js'

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (getToken()) navigate('/tasks', { replace: true })
  }, [navigate])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const data = await api.post('/api/system/login', { username, password })
      setSession(data.token, data.user)
      navigate('/tasks', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const initSystem = async () => {
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await api.post('/api/system/init', {})
      setNotice('初始化完成：已创建 admin / admin123 与 reviewer / reviewer123')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>合同审批审查系统</h1>
        <p className="sub">待办拉取 · 合同解析 · 规则审查 · 评论回写</p>

        {error && <div className="login-error">{error}</div>}
        {notice && (
          <div className="alert alert-success" style={{ marginBottom: 14 }}>
            {notice}
          </div>
        )}

        <div className="field">
          <label>用户名</label>
          <input
            className="input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </div>
        <div className="field">
          <label>密码</label>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>

        <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: '100%' }}>
          {busy ? '处理中…' : '登 录'}
        </button>
        <button
          className="btn"
          type="button"
          onClick={initSystem}
          disabled={busy}
          style={{ width: '100%', marginTop: 10 }}
        >
          初始化系统
        </button>

        <div className="login-hint">
          首次使用请先点击「初始化系统」创建账户。
          <br />
          <b>admin / admin123</b> —— 系统管理员：维护规则与接入配置、查看日志、重试失败任务
          <br />
          <b>reviewer / reviewer123</b> —— 法务审核人：查看合同详情、证据定位与风险判定
        </div>
      </form>
    </div>
  )
}

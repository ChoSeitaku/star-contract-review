import { useCallback, useEffect, useState } from 'react'
import { api, isAdmin } from '../api.js'
import { Badge } from '../components/Badge.jsx'

// 布尔型配置项以开关形式呈现
const BOOLEAN_KEYS = new Set(['adapter_fail_enabled', 'adapter_fail_write_enabled'])

export default function ConfigPage() {
  const [configs, setConfigs] = useState([])
  const [draft, setDraft] = useState({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const admin = isAdmin()

  const load = useCallback(async () => {
    const data = await api.get('/api/system/config')
    setConfigs(data.configs)
    setDraft(Object.fromEntries(data.configs.map((item) => [item.config_key, item.config_value])))
    setLoading(false)
  }, [])

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  const saveAll = async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const changed = Object.fromEntries(
        Object.entries(draft).filter(
          ([key, value]) => configs.find((c) => c.config_key === key)?.config_value !== value,
        ),
      )
      if (Object.keys(changed).length === 0) {
        setNotice('没有需要保存的修改')
        return
      }
      const data = await api.put('/api/system/config', { configs: changed })
      setNotice(`已保存 ${data.updated.length} 项配置：${data.updated.join('、')}`)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const toggleBool = async (key) => {
    const next = draft[key] === 'true' ? 'false' : 'true'
    setDraft({ ...draft, [key]: next })
    setBusy(true)
    setError('')
    try {
      await api.put('/api/system/config', { configs: { [key]: next } })
      setNotice(`${key} 已设为 ${next}（${next === 'true' ? '开启' : '关闭'}）`)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const resetMock = async () => {
    if (!window.confirm('确认重置模拟数据？将清空全部审查任务、命中结果与审批评论，便于重新演示。')) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await api.post('/api/system/mock-reset')
      setNotice(`已重置：当前剩余任务 ${data.approval_tasks} 条，模拟审批单 ${data.mock_approvals} 条`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!admin) return <div className="alert alert-info">该页面仅系统管理员可访问。</div>
  if (loading) return <div className="loading">加载中…</div>

  return (
    <>
      <div className="page-head">
        <div>
          <h2>系统配置</h2>
          <p className="desc">维护审批系统接入配置与审查运行参数。</p>
        </div>
        <button className="btn btn-primary" onClick={saveAll} disabled={busy}>
          保存修改
        </button>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <div className="card">
        <div className="card-head">
          <h3>配置项</h3>
          <span className="hint">修改后立即生效</span>
        </div>
        <div className="card-body">
          {configs.map((item) => (
            <div className="field" key={item.config_key}>
              <label>
                <span className="mono">{item.config_key}</span>
                {' · '}
                {item.description}
              </label>
              {BOOLEAN_KEYS.has(item.config_key) ? (
                <div className="toolbar">
                  <Badge tone={draft[item.config_key] === 'true' ? 'danger' : 'success'}>
                    {draft[item.config_key] === 'true' ? '已开启' : '已关闭'}
                  </Badge>
                  <button className="btn btn-sm" onClick={() => toggleBool(item.config_key)} disabled={busy}>
                    {draft[item.config_key] === 'true' ? '关闭开关' : '开启开关'}
                  </button>
                </div>
              ) : (
                <input
                  className="input"
                  value={draft[item.config_key] ?? ''}
                  onChange={(e) => setDraft({ ...draft, [item.config_key]: e.target.value })}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>演示辅助</h3>
          <span className="hint">重置后可重新执行完整闭环演示</span>
        </div>
        <div className="card-body">
          <p className="muted" style={{ marginTop: 0 }}>
            重置会清空全部审查任务、解析结果、规则命中、审查结果与审批评论，
            并将模拟审批单恢复为待处理状态（保留用户账户与审查规则）。
          </p>
          <button className="btn btn-danger" onClick={resetMock} disabled={busy}>
            重置模拟数据
          </button>
        </div>
      </div>
    </>
  )
}

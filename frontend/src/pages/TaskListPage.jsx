import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, startPolling } from '../api.js'
import { RiskTag, StatusBadge, WriteStatusBadge } from '../components/Badge.jsx'
import { TASK_STATUS } from '../constants.js'

// 待办列表 = 调用端「待办调用模块」：拉取待办并展示待审列表
const FILTERS = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待处理' },
  { key: 'parsing', label: '解析中' },
  { key: 'reviewing', label: '审查中' },
  { key: 'blocked', label: '已阻塞' },
  { key: 'done', label: '已完成' },
]

export default function TaskListPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState([])
  const [counts, setCounts] = useState({})
  const [filter, setFilter] = useState('')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)
  const [pulling, setPulling] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const query = new URLSearchParams()
    if (filter) query.set('task_status', filter)
    if (keyword) query.set('keyword', keyword)
    const data = await api.get(`/api/tasks?${query.toString()}`)
    setTasks(data.tasks)
    setCounts(data.status_counts || {})
    setLoading(false)
  }, [filter, keyword])

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  // 有任务处于处理中时自动轮询刷新
  useEffect(() => {
    const pending = tasks.some((t) => ['pending', 'parsing', 'reviewing'].includes(t.task_status))
    if (!pending) return undefined
    return startPolling(load, 2500)
  }, [tasks, load])

  const pull = async () => {
    setPulling(true)
    setError('')
    setMessage(null)
    try {
      const data = await api.post('/api/tasks/pull', { limit: 20 })
      setMessage(
        `拉取完成：共 ${data.fetched} 条，新增 ${data.created_count} 条，` +
          `执行中 ${data.updated_count} 条，跳过 ${data.skipped_count} 条（已完成或已阻塞）`,
      )
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setPulling(false)
    }
  }

  const total = Object.values(counts).reduce((sum, n) => sum + n, 0)

  return (
    <>
      <div className="page-head">
        <div>
          <h2>待办列表</h2>
          <p className="desc">
            从审批系统拉取待处理合同审批单，按审批编号自动去重；重复拉取只更新已有任务。
          </p>
        </div>
        <button className="btn btn-primary" onClick={pull} disabled={pulling}>
          {pulling ? '拉取中…' : '拉取待办'}
        </button>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="card">
        <div className="card-head">
          <div className="filter-chips">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                className={`chip ${filter === item.key ? 'active' : ''}`}
                onClick={() => setFilter(item.key)}
              >
                {item.label}
                {item.key && counts[item.key] ? ` (${counts[item.key]})` : ''}
                {!item.key && total ? ` (${total})` : ''}
              </button>
            ))}
          </div>
          <input
            className="input"
            style={{ width: 220 }}
            placeholder="搜索审批编号 / 标题"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </div>

        {loading ? (
          <div className="loading">加载中…</div>
        ) : tasks.length === 0 ? (
          <div className="table-empty">
            暂无任务。点击右上角「拉取待办」从审批系统获取待处理合同。
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 130 }}>审批编号</th>
                <th>合同标题</th>
                <th style={{ width: 100 }}>申请人</th>
                <th style={{ width: 100 }}>任务状态</th>
                <th style={{ width: 90 }}>风险等级</th>
                <th style={{ width: 90 }}>命中规则</th>
                <th style={{ width: 100 }}>回写状态</th>
                <th style={{ width: 170 }}>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr
                  key={task.id}
                  className="clickable"
                  onClick={() => navigate(`/tasks/${task.id}`)}
                >
                  <td className="mono">{task.approval_code}</td>
                  <td>
                    {task.approval_title}
                    {task.blocked_reason && (
                      <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 2 }}>
                        阻塞原因：{task.blocked_reason}
                      </div>
                    )}
                  </td>
                  <td>{task.applicant_name}</td>
                  <td>
                    <StatusBadge status={task.task_status} />
                  </td>
                  <td>
                    <RiskTag level={task.overall_risk_level} />
                  </td>
                  <td>{task.hit_count || 0}</td>
                  <td>
                    <WriteStatusBadge status={task.write_status} />
                  </td>
                  <td className="mono muted">{task.updated_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {!loading && tasks.length > 0 && (
        <p className="muted" style={{ fontSize: 12.5 }}>
          共 {tasks.length} 条
          {TASK_STATUS[filter] ? `（筛选：${TASK_STATUS[filter].label}）` : ''}
        </p>
      )}
    </>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, isAdmin } from '../api.js'
import { Badge, StatusBadge, WriteStatusBadge } from '../components/Badge.jsx'

const TABS = [
  { key: 'tasks', label: '全链路任务日志' },
  { key: 'comments', label: '评论回写日志' },
]

export default function LogsPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('tasks')
  const [logs, setLogs] = useState([])
  const [tasks, setTasks] = useState([])
  const [taskFilter, setTaskFilter] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const admin = isAdmin()

  const load = useCallback(async () => {
    const query = new URLSearchParams({ limit: '300' })
    if (taskFilter) query.set('task_id', taskFilter)
    if (tab === 'tasks' && levelFilter) query.set('log_level', levelFilter)
    const data = await api.get(`/api/logs/${tab}?${query.toString()}`)
    setLogs(data.logs)
    setLoading(false)
  }, [tab, taskFilter, levelFilter])

  useEffect(() => {
    if (!admin) return
    api
      .get('/api/tasks')
      .then((data) => setTasks(data.tasks))
      .catch(() => {})
  }, [admin])

  useEffect(() => {
    if (!admin) return
    load().catch((err) => setError(err.message))
  }, [load, admin])

  const retry = async (task) => {
    setError('')
    setNotice('')
    try {
      await api.post(`/api/tasks/${task.id}/retry`)
      setNotice(`任务 ${task.approval_code} 已触发重试`)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const retryComment = async (task) => {
    setError('')
    setNotice('')
    try {
      await api.post(`/api/tasks/${task.id}/retry-comment`)
      setNotice(`任务 ${task.approval_code} 已触发评论回写重试`)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  if (!admin) return <div className="alert alert-info">该页面仅系统管理员可访问。</div>

  const blockedTasks = tasks.filter((t) => t.task_status === 'blocked')
  const failedWriteTasks = tasks.filter((t) => t.write_status === 'failed')

  return (
    <>
      <div className="page-head">
        <div>
          <h2>运行日志</h2>
          <p className="desc">查看全链路运行日志与评论回写记录，并对失败任务执行重试。</p>
        </div>
        <button className="btn" onClick={() => load().catch((e) => setError(e.message))}>
          刷新
        </button>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {(blockedTasks.length > 0 || failedWriteTasks.length > 0) && (
        <div className="card">
          <div className="card-head">
            <h3>待人工处理</h3>
            <span className="hint">
              阻塞任务 {blockedTasks.length} 个 · 回写失败 {failedWriteTasks.length} 个
            </span>
          </div>
          <div className="card-body">
            {blockedTasks.length === 0 && failedWriteTasks.length === 0 ? (
              <div className="muted">当前没有需要人工干预的任务。</div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 130 }}>审批编号</th>
                    <th>合同标题</th>
                    <th style={{ width: 100 }}>任务状态</th>
                    <th style={{ width: 100 }}>回写状态</th>
                    <th>阻塞原因</th>
                    <th style={{ width: 90 }}>重试次数</th>
                    <th style={{ width: 200 }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {[...blockedTasks, ...failedWriteTasks].map((task) => (
                    <tr key={task.id}>
                      <td className="mono">{task.approval_code}</td>
                      <td>{task.approval_title}</td>
                      <td>
                        <StatusBadge status={task.task_status} />
                      </td>
                      <td>
                        <WriteStatusBadge status={task.write_status} />
                      </td>
                      <td className="muted">{task.blocked_reason || '—'}</td>
                      <td>{task.retry_count}</td>
                      <td>
                        {task.task_status === 'blocked' && (
                          <button className="btn btn-sm btn-danger" onClick={() => retry(task)}>
                            重试任务
                          </button>
                        )}{' '}
                        {task.write_status === 'failed' && (
                          <button className="btn btn-sm" onClick={() => retryComment(task)}>
                            重试回写
                          </button>
                        )}{' '}
                        <button className="btn btn-sm" onClick={() => navigate(`/tasks/${task.id}`)}>
                          详情
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <div className="filter-chips">
            {TABS.map((item) => (
              <button
                key={item.key}
                className={`chip ${tab === item.key ? 'active' : ''}`}
                onClick={() => setTab(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="toolbar">
            <select
              className="select"
              style={{ width: 220 }}
              value={taskFilter}
              onChange={(e) => setTaskFilter(e.target.value)}
            >
              <option value="">全部任务</option>
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.approval_code} · {task.approval_title}
                </option>
              ))}
            </select>
            {tab === 'tasks' && (
              <select
                className="select"
                style={{ width: 130 }}
                value={levelFilter}
                onChange={(e) => setLevelFilter(e.target.value)}
              >
                <option value="">全部级别</option>
                <option value="ERROR">ERROR</option>
                <option value="WARN">WARN</option>
                <option value="INFO">INFO</option>
                <option value="DEBUG">DEBUG</option>
              </select>
            )}
          </div>
        </div>

        <div className="card-body">
          {loading ? (
            <div className="loading">加载中…</div>
          ) : logs.length === 0 ? (
            <div className="muted">暂无日志记录。</div>
          ) : tab === 'tasks' ? (
            <table className="log-table">
              <thead>
                <tr>
                  <th style={{ width: 160 }}>时间</th>
                  <th style={{ width: 140 }}>审批编号</th>
                  <th style={{ width: 70 }}>级别</th>
                  <th style={{ width: 130 }}>类型</th>
                  <th>内容</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="mono muted">{log.created_at}</td>
                    <td className="mono">{log.approval_code || log.task_id}</td>
                    <td className={`log-level-${log.log_level}`}>{log.log_level}</td>
                    <td className="mono">{log.log_type}</td>
                    <td>{log.log_content}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="log-table">
              <thead>
                <tr>
                  <th style={{ width: 160 }}>时间</th>
                  <th style={{ width: 140 }}>审批编号</th>
                  <th style={{ width: 70 }}>尝试</th>
                  <th style={{ width: 90 }}>状态</th>
                  <th>回写响应</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="mono muted">{log.created_at}</td>
                    <td className="mono">{log.approval_code || log.task_id}</td>
                    <td>#{log.attempt_no}</td>
                    <td>
                      <Badge tone={log.write_status === 'success' ? 'success' : 'danger'}>
                        {log.write_status === 'success' ? '成功' : '失败'}
                      </Badge>
                    </td>
                    <td>{log.write_response_text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  )
}

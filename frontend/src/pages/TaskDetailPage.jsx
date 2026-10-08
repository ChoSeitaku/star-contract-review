import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, isAdmin, startPolling } from '../api.js'
import { Badge, RiskTag, StatusBadge, WriteStatusBadge } from '../components/Badge.jsx'
import ClauseCard from '../components/ClauseCard.jsx'
import FieldGrid from '../components/FieldGrid.jsx'
import HitCard from '../components/HitCard.jsx'
import { CLAUSE_ORDER, FAILURE_STAGE, FIELD_ORDER } from '../constants.js'

export default function TaskDetailPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const admin = isAdmin()

  const load = useCallback(async () => {
    const data = await api.get(`/api/tasks/${taskId}`)
    setDetail(data)
    return data
  }, [taskId])

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  // 处理中的任务自动轮询
  useEffect(() => {
    const status = detail?.task?.task_status
    if (!status || !['pending', 'parsing', 'reviewing'].includes(status)) return undefined
    return startPolling(load, 2000)
  }, [detail, load])

  const act = async (fn, successMessage) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await fn()
      setNotice(successMessage)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const retry = () =>
    act(() => api.post(`/api/tasks/${taskId}/retry`), '已触发重试，任务将回到对应阶段重新执行')

  const retryComment = () =>
    act(() => api.post(`/api/tasks/${taskId}/retry-comment`), '已触发评论回写重试')

  const toggleHit = (hit, nextStatus) =>
    act(
      () => api.put(`/api/tasks/${taskId}/hits/${hit.id}`, { hit_status: nextStatus }),
      nextStatus === 'dismissed' ? '已标记为误报，总风险等级已重算' : '已恢复为有效命中',
    )

  if (error && !detail) return <div className="alert alert-danger">{error}</div>
  if (!detail) return <div className="loading">加载中…</div>

  const { task, approval, attachments, parse, hits, result, comment_logs: commentLogs, logs } = detail
  const blocked = task.task_status === 'blocked'
  const activeHits = hits.filter((h) => h.hit_status !== 'dismissed')

  return (
    <>
      <div className="page-head">
        <div>
          <h2>
            <button className="btn btn-sm" onClick={() => navigate('/tasks')} style={{ marginRight: 10 }}>
              ← 返回
            </button>
            {task.approval_title}
          </h2>
          <p className="desc">
            审批编号 <span className="mono">{task.approval_code}</span> · 申请人 {task.applicant_name} ·
            实例 <span className="mono">{task.instance_id}</span>
          </p>
        </div>
        <div className="tag-list">
          <StatusBadge status={task.task_status} />
          <WriteStatusBadge status={task.write_status} />
          <RiskTag level={result?.overall_risk_level} />
        </div>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {blocked && (
        <div className="alert alert-danger">
          <div className="alert-body">
            <b>任务已阻塞：{task.blocked_reason}</b>
            <div style={{ marginTop: 4 }}>
              失败阶段：{FAILURE_STAGE[task.failure_stage] || task.failure_stage || '—'}
              {task.retry_count > 0 && ` · 已重试 ${task.retry_count} 次`}
              {' · '}
              {task.failure_stage === 'review'
                ? '重试将从「规则审查」阶段继续执行。'
                : '重试将从「附件下载与解析」阶段重新执行。'}
            </div>
          </div>
          {admin && (
            <button className="btn btn-danger" onClick={retry} disabled={busy}>
              重试任务
            </button>
          )}
        </div>
      )}

      {detail.adapter_error && (
        <div className="alert alert-info">
          审批系统接口暂时不可用，以下审批信息可能不完整：{detail.adapter_error}
        </div>
      )}

      {/* ---------------- 详情查看模块 ---------------- */}
      <div className="card">
        <div className="card-head">
          <h3>审批信息与附件</h3>
          <span className="hint">来自审批系统的表单数据与合同附件</span>
        </div>
        <div className="card-body">
          <div className="kv-grid">
            <div className="kv">
              <div className="k">审批编号</div>
              <div className="v mono">{task.approval_code}</div>
            </div>
            <div className="kv">
              <div className="k">申请人 / 部门</div>
              <div className="v">
                {task.applicant_name}
                {approval?.department ? ` · ${approval.department}` : ''}
              </div>
            </div>
            <div className="kv">
              <div className="k">申请时间</div>
              <div className="v mono">{task.applied_at || '—'}</div>
            </div>
            <div className="kv">
              <div className="k">审批状态 / 当前节点</div>
              <div className="v">
                {approval ? `${approval.approval_status} · ${approval.current_node}` : '—'}
              </div>
            </div>
          </div>

          {approval?.form_data && Object.keys(approval.form_data).length > 0 && (
            <>
              <div className="section-title">表单数据</div>
              <div className="kv-grid">
                {Object.entries(approval.form_data).map(([key, value]) => (
                  <div className="kv" key={key}>
                    <div className="k">{key}</div>
                    <div className="v">{String(value)}</div>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="section-title">合同附件</div>
          {attachments.length === 0 ? (
            <div className="muted">该审批单未提供合同附件</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>文件名</th>
                  <th style={{ width: 90 }}>类型</th>
                  <th style={{ width: 100 }}>下载状态</th>
                  <th style={{ width: 110 }}>大小</th>
                  <th style={{ width: 240 }}>sha256 校验</th>
                  <th>本地路径</th>
                </tr>
              </thead>
              <tbody>
                {attachments.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">{item.file_name}</td>
                    <td>{item.file_type}</td>
                    <td>
                      <Badge tone={item.download_status === 'success' ? 'success' : 'danger'}>
                        {item.download_status === 'success' ? '成功' : '失败'}
                      </Badge>
                    </td>
                    <td className="mono">{item.file_size} B</td>
                    <td className="mono muted">{item.sha256 ? `${item.sha256.slice(0, 24)}…` : '—'}</td>
                    <td className="mono muted" style={{ fontSize: 11.5 }}>
                      {item.file_path || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ---------------- 解析结果模块 ---------------- */}
      <div className="card">
        <div className="card-head">
          <h3>合同解析结果</h3>
          {parse && (
            <span className="hint">
              解析方式：
              {parse.parse_type === 'pdf_ocr'
                ? '扫描件 OCR 识别'
                : parse.parse_type === 'pdf_text'
                  ? 'PDF 文本提取'
                  : parse.parse_type === 'docx'
                    ? 'DOCX 文本提取'
                    : '—'}
              {parse.page_count ? ` · ${parse.page_count} 页` : ''} · 文档编号{' '}
              <span className="mono">{parse.document_id}</span>
            </span>
          )}
        </div>
        <div className="card-body">
          {!parse ? (
            <div className="muted">尚未生成解析结果（任务可能在解析阶段被阻塞）。</div>
          ) : parse.parse_status === 'failed' ? (
            <div className="alert alert-danger" style={{ marginBottom: 0 }}>
              <div className="alert-body">
                <b>解析失败，未产出可用字段</b>
                <div style={{ marginTop: 4 }}>{parse.parse_error}</div>
              </div>
            </div>
          ) : (
            <>
              <div className="section-title">合同基本信息</div>
              <FieldGrid fields={parse.basic_info} order={FIELD_ORDER} />
              <div className="section-title">条款信息</div>
              <ClauseCard clauses={parse.clause_info} order={CLAUSE_ORDER} />
            </>
          )}
        </div>
      </div>

      {/* ---------------- 规则命中模块 ---------------- */}
      <div className="card">
        <div className="card-head">
          <h3>规则命中</h3>
          <span className="hint">
            共命中 {hits.length} 条，其中有效 {activeHits.length} 条
            {!admin && ' · 法务审核人可将误报标记为无效'}
          </span>
        </div>
        <div className="card-body">
          {hits.length === 0 ? (
            <div className="muted">
              {task.task_status === 'done' ? '未命中任何风险规则。' : '尚未执行规则审查。'}
            </div>
          ) : (
            hits.map((hit) => (
              <HitCard key={hit.id} hit={hit} onToggle={toggleHit} canReview />
            ))
          )}
        </div>
      </div>

      {/* ---------------- 结果处理模块 ---------------- */}
      <div className="card">
        <div className="card-head">
          <h3>审查结果与评论回写</h3>
          <span className="hint">总风险等级、审批关注点与写回审批评论区的内容</span>
        </div>
        <div className="card-body">
          {!result ? (
            <div className="muted">尚未生成审查结果。</div>
          ) : (
            <>
              <div className={`risk-hero level-${result.overall_risk_level}`}>
                <div className="level">{result.overall_risk_level}</div>
                <div>
                  <div style={{ fontWeight: 600 }}>总风险等级</div>
                  <div className="desc">
                    按有效命中规则的最高等级评定
                    {detail.recomputed_risk_level !== result.overall_risk_level &&
                      ` · 按当前有效命中重算为「${detail.recomputed_risk_level}」`}
                  </div>
                </div>
              </div>

              <div className="section-title">中文摘要</div>
              <div className="summary-text">{result.summary_text}</div>

              <div className="section-title">审批关注点（{result.focus_points.length} 项）</div>
              {result.focus_points.length === 0 ? (
                <div className="muted">无</div>
              ) : (
                <ul className="focus-list">
                  {result.focus_points.map((point, index) => (
                    <li key={`${point.rule_code}-${index}`}>
                      <RiskTag level={point.risk_level} withWord={false} />
                      <div>
                        <div style={{ fontWeight: 600 }}>{point.point}</div>
                        {point.detail && <div className="muted">{point.detail}</div>}
                        {point.evidence_position && (
                          <div className="mono muted" style={{ fontSize: 11.5 }}>
                            位置：{point.evidence_position}
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              <div className="section-title">回写内容（写入审批评论区）</div>
              <div className="comment-box">{result.comment_text}</div>

              <div className="section-title">回写状态</div>
              <div className="toolbar">
                <WriteStatusBadge status={task.write_status} />
                {task.write_status === 'failed' && admin && (
                  <button className="btn btn-danger btn-sm" onClick={retryComment} disabled={busy}>
                    重试回写
                  </button>
                )}
                {task.write_status === 'success' && (
                  <span className="muted">审查意见已写入审批单 {task.instance_id} 的评论区</span>
                )}
              </div>

              {commentLogs.length > 0 && (
                <table className="log-table" style={{ marginTop: 12 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 70 }}>尝试</th>
                      <th style={{ width: 90 }}>状态</th>
                      <th style={{ width: 160 }}>时间</th>
                      <th>回写响应</th>
                    </tr>
                  </thead>
                  <tbody>
                    {commentLogs.map((log) => (
                      <tr key={log.id}>
                        <td>#{log.attempt_no}</td>
                        <td>
                          <Badge tone={log.write_status === 'success' ? 'success' : 'danger'}>
                            {log.write_status === 'success' ? '成功' : '失败'}
                          </Badge>
                        </td>
                        <td className="mono muted">{log.created_at}</td>
                        <td>{log.write_response_text}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      </div>

      {/* ---------------- 全链路日志 ---------------- */}
      <div className="card">
        <div className="card-head">
          <h3>任务日志</h3>
          <span className="hint">最近 {logs.length} 条</span>
        </div>
        <div className="card-body">
          {logs.length === 0 ? (
            <div className="muted">暂无日志</div>
          ) : (
            <table className="log-table">
              <thead>
                <tr>
                  <th style={{ width: 160 }}>时间</th>
                  <th style={{ width: 70 }}>级别</th>
                  <th style={{ width: 120 }}>类型</th>
                  <th>内容</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="mono muted">{log.created_at}</td>
                    <td className={`log-level-${log.log_level}`}>{log.log_level}</td>
                    <td className="mono">{log.log_type}</td>
                    <td>{log.log_content}</td>
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

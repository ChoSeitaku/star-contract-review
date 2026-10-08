import { RISK_LEVEL, TASK_STATUS, WRITE_STATUS } from '../constants.js'

export function Badge({ tone = 'muted', children }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

// 任务状态徽章（pending / parsing / reviewing / blocked / done）
export function StatusBadge({ status }) {
  const meta = TASK_STATUS[status] || { label: status, tone: 'muted' }
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

// 回写状态徽章（not_written / writing / success / failed）
export function WriteStatusBadge({ status }) {
  const meta = WRITE_STATUS[status] || { label: status, tone: 'muted' }
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

// 风险等级徽章（低 / 中 / 高）
export function RiskTag({ level, withWord = true }) {
  if (!level) return <span className="muted">—</span>
  const meta = RISK_LEVEL[level] || { label: level, tone: 'muted' }
  return <Badge tone={meta.tone}>{withWord ? meta.label : level}</Badge>
}

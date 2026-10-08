import { useState } from 'react'
import { Badge } from './Badge.jsx'

// 单类条款：标题 + 提取状态 + 位置，展开后显示条款原文
function ClauseItem({ clause }) {
  const [open, setOpen] = useState(false)
  const found = clause.status === 'found'

  return (
    <div className="clause-item">
      <div className="clause-head" onClick={() => setOpen(!open)}>
        <span className="title">
          {open ? '▾' : '▸'} {clause.clause_name}
        </span>
        <span className="meta">
          {found && clause.position && <span className="muted mono">{clause.position}</span>}
          <Badge tone={found ? 'success' : 'warning'}>{found ? '已约定' : '未提取到'}</Badge>
        </span>
      </div>
      {open && (
        <div className="clause-body">
          {found ? clause.value : `未在合同中定位到${clause.clause_name}（检索关键词：${clause.keywords || '—'}）`}
        </div>
      )}
    </div>
  )
}

export default function ClauseCard({ clauses, order }) {
  const items = order ? order.map((key) => clauses[key]).filter(Boolean) : Object.values(clauses)
  if (!items.length) return <div className="muted">暂无条款信息</div>
  return (
    <div>
      {items.map((clause) => (
        <ClauseItem key={clause.clause_key} clause={clause} />
      ))}
    </div>
  )
}

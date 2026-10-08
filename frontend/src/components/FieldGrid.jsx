import { Badge } from './Badge.jsx'

// 单个解析字段：值 + 提取状态 + 原文片段 + 位置标识（§1.3.5）
export function FieldCard({ field }) {
  const found = field.status === 'found'
  return (
    <div className={`field-card ${found ? '' : 'is-missing'}`}>
      <div className="top">
        <span className="name">{field.field_name}</span>
        <Badge tone={found ? 'success' : 'muted'}>{found ? '已提取' : '未提取'}</Badge>
      </div>
      <div className={`value ${found ? '' : 'empty'}`}>{found ? field.value : '未在合同中提取到'}</div>
      {found && field.evidence && (
        <div className="evidence">
          <span className="pos">{field.position}</span>
          {field.evidence}
        </div>
      )}
    </div>
  )
}

export default function FieldGrid({ fields, order }) {
  const items = order ? order.map((key) => fields[key]).filter(Boolean) : Object.values(fields)
  if (!items.length) return <div className="muted">暂无解析字段</div>
  return (
    <div className="field-grid">
      {items.map((field) => (
        <FieldCard key={field.field_key} field={field} />
      ))}
    </div>
  )
}

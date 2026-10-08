// 状态与风险等级的中文标签与配色（与后端枚举保持一致）

export const TASK_STATUS = {
  pending: { label: '待处理', tone: 'muted' },
  parsing: { label: '解析中', tone: 'info' },
  reviewing: { label: '审查中', tone: 'info' },
  blocked: { label: '已阻塞', tone: 'danger' },
  done: { label: '已完成', tone: 'success' },
}

export const WRITE_STATUS = {
  not_written: { label: '未回写', tone: 'muted' },
  writing: { label: '回写中', tone: 'info' },
  success: { label: '回写成功', tone: 'success' },
  failed: { label: '回写失败', tone: 'danger' },
}

export const RISK_LEVEL = {
  高: { label: '高风险', tone: 'danger' },
  中: { label: '中风险', tone: 'warning' },
  低: { label: '低风险', tone: 'success' },
}

export const FAILURE_STAGE = {
  download: '附件下载阶段',
  parse: '文档解析阶段',
  review: '规则审查阶段',
}

export const FIELD_ORDER = [
  'contract_title',
  'contract_no',
  'party_a',
  'party_b',
  'amount',
  'currency',
  'effective_date',
  'expire_date',
]

export const CLAUSE_ORDER = [
  'payment',
  'delivery',
  'acceptance',
  'breach',
  'confidentiality',
  'data',
  'ip',
  'dispute',
]

export const MATCH_MODE_LABEL = {
  regex: '正则匹配',
  contains: '包含匹配',
  missing: '缺失匹配',
}

export const MATCH_TARGET_LABEL = (target) => {
  if (!target || target === 'full_text') return '全文'
  const [kind, key] = target.split(':')
  if (kind === 'clause') return `条款：${key}`
  if (kind === 'field') return `字段:${key}`
  return target
}

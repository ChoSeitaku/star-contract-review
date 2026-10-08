import { RiskTag } from './Badge.jsx'

// 单条规则命中：规则名称 + 风险等级 + 命中证据 + 证据位置 + 建议说明（§1.3.6）
export default function HitCard({ hit, onToggle, canReview }) {
  const dismissed = hit.hit_status === 'dismissed'

  return (
    <div className={`hit-card level-${hit.risk_level} ${dismissed ? 'is-dismissed' : ''}`}>
      <div className="top">
        <div>
          <span className="rule-name">{hit.rule_name}</span>
          <span className="rule-code mono">{hit.rule_code}</span>
        </div>
        <div className="tag-list">
          <RiskTag level={hit.risk_level} />
          {dismissed && <span className="badge badge-muted">已判定误报</span>}
          {canReview && (
            <button
              className="btn btn-sm"
              onClick={() => onToggle(hit, dismissed ? 'hit' : 'dismissed')}
            >
              {dismissed ? '恢复为有效' : '标记误报'}
            </button>
          )}
        </div>
      </div>

      <div className="row">
        <span className="label">命中证据</span>
        <span>{hit.evidence_text}</span>
      </div>
      <div className="row">
        <span className="label">证据位置</span>
        <span className="mono">{hit.evidence_position || '—'}</span>
      </div>
      <div className="suggestion">处理建议：{hit.suggestion_text}</div>
    </div>
  )
}

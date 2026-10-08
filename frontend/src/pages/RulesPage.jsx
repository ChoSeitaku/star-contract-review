import { useCallback, useEffect, useState } from 'react'
import { api, isAdmin } from '../api.js'
import { Badge, RiskTag } from '../components/Badge.jsx'
import { MATCH_MODE_LABEL, MATCH_TARGET_LABEL, RISK_LEVEL } from '../constants.js'

const EMPTY_RULE = {
  rule_code: '',
  rule_name: '',
  risk_level: '中',
  rule_status: 'enabled',
  match_mode: 'contains',
  match_text: '',
  suggestion_text: '',
  match_target: 'full_text',
}

function RuleModal({ rule, onClose, onSaved }) {
  const [form, setForm] = useState(rule || EMPTY_RULE)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const isEdit = Boolean(rule?.id)

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value })

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      if (isEdit) {
        await api.put(`/api/rules/${rule.id}`, form)
      } else {
        await api.post('/api/rules', form)
      }
      onSaved(isEdit ? '规则已更新' : '规则已新增')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{isEdit ? `编辑规则 ${rule.rule_code}` : '新增规则'}</h3>
          <button className="btn btn-sm" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="modal-body">
          {error && <div className="alert alert-danger">{error}</div>}
          <div className="form-row">
            <div className="field">
              <label>规则编码</label>
              <input className="input" value={form.rule_code} onChange={set('rule_code')} />
            </div>
            <div className="field">
              <label>规则名称</label>
              <input className="input" value={form.rule_name} onChange={set('rule_name')} />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>风险等级</label>
              <select className="select" value={form.risk_level} onChange={set('risk_level')}>
                {Object.keys(RISK_LEVEL).map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>规则状态</label>
              <select className="select" value={form.rule_status} onChange={set('rule_status')}>
                <option value="enabled">启用</option>
                <option value="disabled">停用</option>
              </select>
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>匹配模式</label>
              <select className="select" value={form.match_mode} onChange={set('match_mode')}>
                <option value="contains">包含匹配（contains）</option>
                <option value="regex">正则匹配（regex）</option>
                <option value="missing">缺失匹配（missing）</option>
              </select>
            </div>
            <div className="field">
              <label>匹配目标</label>
              <input
                className="input"
                value={form.match_target}
                onChange={set('match_target')}
                placeholder="full_text / clause:payment / field:amount"
              />
            </div>
          </div>
          <div className="field">
            <label>匹配文本（包含模式用 | 分隔多个候选词）</label>
            <textarea className="textarea" value={form.match_text} onChange={set('match_text')} />
          </div>
          <div className="field">
            <label>处理建议</label>
            <textarea
              className="textarea"
              value={form.suggestion_text}
              onChange={set('suggestion_text')}
            />
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>
            {busy ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function RulesPage() {
  const [rules, setRules] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(null)
  const admin = isAdmin()

  const load = useCallback(async () => {
    const data = await api.get('/api/rules')
    setRules(data.rules)
    setLoading(false)
  }, [])

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  const toggle = async (rule) => {
    setError('')
    try {
      await api.post(`/api/rules/${rule.id}/toggle`)
      setNotice(`规则 ${rule.rule_code} 已${rule.rule_status === 'enabled' ? '停用' : '启用'}`)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const remove = async (rule) => {
    if (!window.confirm(`确认删除规则 ${rule.rule_code}「${rule.rule_name}」？`)) return
    setError('')
    try {
      await api.del(`/api/rules/${rule.id}`)
      setNotice(`规则 ${rule.rule_code} 已删除`)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const saved = async (message) => {
    setEditing(null)
    setNotice(message)
    await load()
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>规则管理</h2>
          <p className="desc">
            维护合同审查规则。规则至少包含编码、名称、风险等级、状态、匹配模式、匹配文本与处理建议。
          </p>
        </div>
        {admin && (
          <button className="btn btn-primary" onClick={() => setEditing({})}>
            新增规则
          </button>
        )}
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <div className="card">
        <div className="card-head">
          <h3>规则列表</h3>
          <span className="hint">共 {rules.length} 条</span>
        </div>
        {loading ? (
          <div className="loading">加载中…</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 96 }}>编码</th>
                <th style={{ width: 170 }}>规则名称</th>
                <th style={{ width: 80 }}>风险等级</th>
                <th style={{ width: 90 }}>匹配模式</th>
                <th style={{ width: 140 }}>匹配目标</th>
                <th>匹配文本</th>
                <th style={{ width: 80 }}>状态</th>
                {admin && <th style={{ width: 150 }}>操作</th>}
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id}>
                  <td className="mono">{rule.rule_code}</td>
                  <td>{rule.rule_name}</td>
                  <td>
                    <RiskTag level={rule.risk_level} />
                  </td>
                  <td>{MATCH_MODE_LABEL[rule.match_mode] || rule.match_mode}</td>
                  <td className="mono muted" style={{ fontSize: 12 }}>
                    {MATCH_TARGET_LABEL(rule.match_target)}
                  </td>
                  <td className="mono" style={{ fontSize: 12, wordBreak: 'break-all' }}>
                    {rule.match_text}
                  </td>
                  <td>
                    <Badge tone={rule.rule_status === 'enabled' ? 'success' : 'muted'}>
                      {rule.rule_status === 'enabled' ? '启用' : '停用'}
                    </Badge>
                  </td>
                  {admin && (
                    <td>
                      <button className="btn btn-sm" onClick={() => setEditing(rule)}>
                        编辑
                      </button>{' '}
                      <button className="btn btn-sm" onClick={() => toggle(rule)}>
                        {rule.rule_status === 'enabled' ? '停用' : '启用'}
                      </button>{' '}
                      <button className="btn btn-sm btn-danger" onClick={() => remove(rule)}>
                        删除
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing && (
        <RuleModal
          rule={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={saved}
        />
      )}
    </>
  )
}

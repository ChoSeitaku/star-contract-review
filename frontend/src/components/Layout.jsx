import { NavLink, useNavigate } from 'react-router-dom'
import { api, clearSession, getUser, isAdmin } from '../api.js'

const ROLE_LABEL = { admin: '系统管理员', reviewer: '法务审核人' }

export default function Layout({ children }) {
  const navigate = useNavigate()
  const user = getUser()

  const logout = async () => {
    try {
      await api.post('/api/system/logout')
    } catch {
      // 忽略退出接口异常，本地会话照常清理
    }
    clearSession()
    navigate('/login', { replace: true })
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>合同审批审查系统</h1>
          <p>自动审查 · 风险识别 · 评论回写</p>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/tasks" className={({ isActive }) => (isActive ? 'active' : '')}>
            待办列表
          </NavLink>
          {isAdmin() && (
            <>
              <NavLink to="/rules" className={({ isActive }) => (isActive ? 'active' : '')}>
                规则管理
              </NavLink>
              <NavLink to="/logs" className={({ isActive }) => (isActive ? 'active' : '')}>
                运行日志
              </NavLink>
              <NavLink to="/config" className={({ isActive }) => (isActive ? 'active' : '')}>
                系统配置
              </NavLink>
            </>
          )}
        </nav>
        <div className="sidebar-user">
          <div className="name">{user?.display_name || user?.username || '未登录'}</div>
          <div className="role">{ROLE_LABEL[user?.role] || user?.role || ''}</div>
          <button className="btn btn-sm" onClick={logout} style={{ width: '100%' }}>
            退出登录
          </button>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  )
}

import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { getToken } from './api.js'
import Layout from './components/Layout.jsx'
import LoginPage from './pages/LoginPage.jsx'
import TaskListPage from './pages/TaskListPage.jsx'
import TaskDetailPage from './pages/TaskDetailPage.jsx'
import RulesPage from './pages/RulesPage.jsx'
import ConfigPage from './pages/ConfigPage.jsx'
import LogsPage from './pages/LogsPage.jsx'

function RequireAuth({ children }) {
  const location = useLocation()
  if (!getToken()) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  return children
}

const guard = (element) => <RequireAuth>{element}</RequireAuth>

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/tasks"
        element={guard(
          <Layout>
            <TaskListPage />
          </Layout>,
        )}
      />
      <Route
        path="/tasks/:taskId"
        element={guard(
          <Layout>
            <TaskDetailPage />
          </Layout>,
        )}
      />
      <Route
        path="/rules"
        element={guard(
          <Layout>
            <RulesPage />
          </Layout>,
        )}
      />
      <Route
        path="/logs"
        element={guard(
          <Layout>
            <LogsPage />
          </Layout>,
        )}
      />
      <Route
        path="/config"
        element={guard(
          <Layout>
            <ConfigPage />
          </Layout>,
        )}
      />
      <Route path="*" element={<Navigate to="/tasks" replace />} />
    </Routes>
  )
}

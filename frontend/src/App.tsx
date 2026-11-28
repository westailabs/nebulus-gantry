import { useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useAuthStore } from './stores/authStore';
import { useConfigStore } from './stores/configStore';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { DemoAdminRoute } from './components/DemoAdminRoute';
import { ToastContainer } from './components/Toast';
import { Login } from './pages/Login';
import { Chat } from './pages/Chat';
import { Admin } from './pages/Admin';
import { Settings } from './pages/Settings';
import { Overlord } from './pages/Overlord';
import { Personas } from './pages/Personas';
import { Orchestrator } from './pages/Orchestrator';

function App() {
  const checkAuth = useAuthStore((state) => state.checkAuth);
  const loadConfig = useConfigStore((state) => state.load);

  useEffect(() => {
    checkAuth();
    loadConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <BrowserRouter>
      <ToastContainer />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<Chat />} />
                  <Route path="/admin" element={<Admin />} />
                  <Route path="/overlord" element={<Overlord />} />
                  <Route path="/orchestrator" element={<DemoAdminRoute><Orchestrator /></DemoAdminRoute>} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="/personas" element={<Personas />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;

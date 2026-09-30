import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './routes/ProtectedRoute';
import Login from './pages/Login';
import ChangePassword from './pages/user/ChangePassword';
import AdminLayout from './pages/admin/AdminLayout';
import UserList from './pages/admin/UserList';
import CreateUser from './pages/admin/CreateUser';
import UserDetail from './pages/admin/UserDetail';
import FutureInstrumentMargins from './pages/admin/FutureInstrumentMargins';
import BrokerageSettings from './pages/admin/BrokerageSettings';
import AdminDashboard from './pages/admin/AdminDashboard';
import Dashboard from './pages/user/Dashboard';

// Smart root redirect based on auth status and role
const RootRedirect = () => {
  const { isAuthenticated, role, forcePasswordChange, loading } = useAuth();

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#090d16',
      }}>
        <div className="spinner" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (role === 'user' && forcePasswordChange) {
    return <Navigate to="/user/change-password" replace />;
  }

  return <Navigate to={role === 'admin' ? '/admin/users' : '/user/dashboard'} replace />;
};

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public Authentication Route */}
          <Route path="/login" element={<Login />} />

          {/* Protected Admin Routes */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRole="admin">
                <AdminLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/admin/dashboard" replace />} />
            <Route path="dashboard" element={<AdminDashboard />} />
            <Route path="users" element={<UserList />} />
            <Route path="users/:userId" element={<UserDetail />} />
            <Route path="brokerage-settings" element={<BrokerageSettings />} />
            <Route path="future-instruments" element={<FutureInstrumentMargins />} />
            <Route path="create-user" element={<CreateUser />} />
            <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />
          </Route>

          {/* Protected User Routes */}
          <Route
            path="/user/change-password"
            element={
              <ProtectedRoute allowedRole="user" allowWhileForceChange={true}>
                <ChangePassword />
              </ProtectedRoute>
            }
          />

          <Route
            path="/user/dashboard"
            element={
              <ProtectedRoute allowedRole="user">
                <Dashboard />
              </ProtectedRoute>
            }
          />

          <Route
            path="/user/*"
            element={
              <ProtectedRoute allowedRole="user">
                <Navigate to="/user/dashboard" replace />
              </ProtectedRoute>
            }
          />

          {/* Root and Fallback */}
          <Route path="/" element={<RootRedirect />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;

import React from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { ShieldCheck, Users, UserPlus, LogOut, TrendingUp } from 'lucide-react';

const AdminLayout = () => {
  const { userId, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--bg-main)' }}>
      {/* Sidebar Navigation */}
      <aside style={{
        width: '260px',
        background: 'rgba(15, 21, 35, 0.95)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        padding: '24px 16px',
        position: 'sticky',
        top: 0,
        height: '100vh',
        zIndex: 50,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '0 8px 24px 8px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #2563eb, #06b6d4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 15px rgba(59, 130, 246, 0.4)',
          }}>
            <ShieldCheck size={20} color="#fff" />
          </div>
          <div>
            <h2 style={{ fontSize: '1rem', fontWeight: 700, color: '#fff', letterSpacing: '-0.3px' }}>Simulation Admin</h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Trading Control Base</span>
          </div>
        </div>

        <nav style={{ marginTop: '24px', display: 'flex', flexDirection: 'column', gap: '6px', flex: 1 }}>
          <NavLink
            to="/admin/dashboard"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 14px',
              borderRadius: '10px',
              fontSize: '0.9rem',
              fontWeight: 500,
              textDecoration: 'none',
              color: isActive ? '#fff' : 'var(--text-secondary)',
              background: isActive ? 'linear-gradient(135deg, rgba(37, 99, 235, 0.3), rgba(6, 182, 212, 0.15))' : 'transparent',
              border: isActive ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent',
              transition: 'all 0.2s',
            })}
          >
            <ShieldCheck size={18} />
            <span>Dashboard Overview</span>
          </NavLink>

          <NavLink
            to="/admin/users"
            end
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 14px',
              borderRadius: '10px',
              fontSize: '0.9rem',
              fontWeight: 500,
              textDecoration: 'none',
              color: isActive ? '#fff' : 'var(--text-secondary)',
              background: isActive ? 'linear-gradient(135deg, rgba(37, 99, 235, 0.3), rgba(6, 182, 212, 0.15))' : 'transparent',
              border: isActive ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent',
              transition: 'all 0.2s',
            })}
          >
            <Users size={18} />
            <span>Trader Accounts</span>
          </NavLink>

          <NavLink
            to="/admin/brokerage-settings"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 14px',
              borderRadius: '10px',
              fontSize: '0.9rem',
              fontWeight: 500,
              textDecoration: 'none',
              color: isActive ? '#fff' : 'var(--text-secondary)',
              background: isActive ? 'linear-gradient(135deg, rgba(37, 99, 235, 0.3), rgba(6, 182, 212, 0.15))' : 'transparent',
              border: isActive ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent',
              transition: 'all 0.2s',
            })}
          >
            <TrendingUp size={18} />
            <span>Brokerage Settings</span>
          </NavLink>

          <NavLink
            to="/admin/future-instruments"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 14px',
              borderRadius: '10px',
              fontSize: '0.9rem',
              fontWeight: 500,
              textDecoration: 'none',
              color: isActive ? '#fff' : 'var(--text-secondary)',
              background: isActive ? 'linear-gradient(135deg, rgba(37, 99, 235, 0.3), rgba(6, 182, 212, 0.15))' : 'transparent',
              border: isActive ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent',
              transition: 'all 0.2s',
            })}
          >
            <TrendingUp size={18} />
            <span>Future Instruments & Margin</span>
          </NavLink>

          <NavLink
            to="/admin/create-user"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 14px',
              borderRadius: '10px',
              fontSize: '0.9rem',
              fontWeight: 500,
              textDecoration: 'none',
              color: isActive ? '#fff' : 'var(--text-secondary)',
              background: isActive ? 'linear-gradient(135deg, rgba(37, 99, 235, 0.3), rgba(6, 182, 212, 0.15))' : 'transparent',
              border: isActive ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent',
              transition: 'all 0.2s',
            })}
          >
            <UserPlus size={18} />
            <span>Create New User</span>
          </NavLink>
        </nav>

        {/* User Profile & Logout */}
        <div style={{
          paddingTop: '16px',
          borderTop: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '0 8px' }}>
            <div style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              background: 'rgba(255, 255, 255, 0.08)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.85rem',
              fontWeight: 600,
              color: '#38bdf8',
            }}>
              {userId ? userId.charAt(0).toUpperCase() : 'A'}
            </div>
            <div style={{ overflow: 'hidden' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#fff' }}>{userId}</div>
              <div style={{ fontSize: '0.72rem', color: '#10b981', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }} />
                Super Admin
              </div>
            </div>
          </div>

          <button
            onClick={handleLogout}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              padding: '10px',
              borderRadius: '9px',
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.25)',
              color: '#f87171',
              fontSize: '0.85rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            <LogOut size={16} />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <Outlet />
      </div>
    </div>
  );
};

export default AdminLayout;

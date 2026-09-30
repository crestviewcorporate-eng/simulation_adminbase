import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api/api';
import { 
  Users, 
  Search, 
  AlertTriangle, 
  ChevronRight, 
  CheckCircle2, 
  XCircle, 
  RefreshCw,
  Plus,
  ShieldAlert,
  Trash2,
} from 'lucide-react';

const UserList = () => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [lowBalanceOnly, setLowBalanceOnly] = useState(false);

  const navigate = useNavigate();
  const [quickDeleteUser, setQuickDeleteUser] = useState(null);   // {user_id, name}
  const [quickDeleteConfirm, setQuickDeleteConfirm] = useState('');
  const [quickDeleting, setQuickDeleting] = useState(false);

  const fetchUsers = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (lowBalanceOnly) {
        params.append('low_balance_threshold', '70');
      }
      const qs = params.toString();
      const url = qs ? `/admin/users?${qs}` : '/admin/users';
      const res = await api.get(url);
      setUsers(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load trader accounts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [lowBalanceOnly]);

  const filteredUsers = users.filter((u) => {
    const term = searchTerm.toLowerCase();
    return (
      u.user_id.toLowerCase().includes(term) ||
      (u.name && u.name.toLowerCase().includes(term))
    );
  });


  const handleQuickDelete = async () => {
    if (quickDeleteConfirm !== quickDeleteUser?.user_id) return;
    setQuickDeleting(true);
    try {
      await api.delete(`/admin/users/${quickDeleteUser.user_id}`);
      setQuickDeleteUser(null);
      setQuickDeleteConfirm('');
      fetchUsers();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to delete user.');
      setQuickDeleteUser(null);
    } finally {
      setQuickDeleting(false);
    }
  };


  return (
    <>
    <div style={{ padding: '32px', maxWidth: '1400px', width: '100%', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '28px', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff', letterSpacing: '-0.5px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Users size={26} color="#3b82f6" />
            <span>Trader Accounts</span>
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '4px' }}>
            Monitor trading balances, risk exposure, and real-time execution activity across all users.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={fetchUsers}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '10px 14px',
              borderRadius: '10px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            <RefreshCw size={15} />
            <span>Refresh</span>
          </button>
          <button
            onClick={() => navigate('/admin/create-user')}
            className="submit-btn"
            style={{ margin: 0, padding: '10px 18px', width: 'auto', fontSize: '0.88rem' }}
          >
            <Plus size={16} />
            <span>New User</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px',
        marginBottom: '20px',
        flexWrap: 'wrap',
      }}>
        {/* Search */}
        <div style={{ position: 'relative', width: '320px', maxWidth: '100%' }}>
          <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
          <input
            type="text"
            placeholder="Search by User ID or Name..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 12px 10px 36px',
              background: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              borderRadius: '10px',
              color: '#fff',
              fontSize: '0.88rem',
              outline: 'none',
            }}
          />
        </div>

        {/* Filter Toggle: Low Balance Only (>=70% loss) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            padding: '8px 14px',
            borderRadius: '10px',
            background: lowBalanceOnly ? 'rgba(245, 158, 11, 0.15)' : 'var(--bg-card)',
            border: lowBalanceOnly ? '1px solid rgba(245, 158, 11, 0.4)' : '1px solid var(--border-color)',
            transition: 'all 0.2s',
          }}>
            <input
              type="checkbox"
              checked={lowBalanceOnly}
              onChange={(e) => setLowBalanceOnly(e.target.checked)}
              style={{ accentColor: '#f59e0b', width: '16px', height: '16px', cursor: 'pointer' }}
            />
            <ShieldAlert size={15} color={lowBalanceOnly ? '#fbbf24' : 'var(--text-secondary)'} />
            <span style={{ fontSize: '0.84rem', fontWeight: 500, color: lowBalanceOnly ? '#fde68a' : 'var(--text-secondary)' }}>
              Low Balance Only (≥70% loss)
            </span>
          </label>
        </div>
      </div>

      {error && (
        <div className="alert-error" style={{ marginBottom: '20px' }}>
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Users Table */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        overflow: 'hidden',
        boxShadow: '0 8px 30px rgba(0, 0, 0, 0.3)',
      }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', minWidth: '900px' }}>
            <thead>
              <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                <th style={{ padding: '14px 18px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>User ID / Name</th>
                <th style={{ padding: '14px 18px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Allowed Segments</th>
                <th style={{ padding: '14px 18px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Balance & Risk</th>
                <th style={{ padding: '14px 18px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Status</th>
                <th style={{ padding: '14px 18px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    <div className="spinner" style={{ margin: '0 auto 12px auto' }} />
                    <span>Loading trader directory...</span>
                  </td>
                </tr>
              ) : filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    <Users size={32} style={{ margin: '0 auto 8px auto', opacity: 0.4 }} />
                    <p>No matching trader accounts found.</p>
                  </td>
                </tr>
              ) : (
                filteredUsers.map((user) => {
                  const isFunded = user.balance && user.balance > 0;
                  const lossPct = user.loss_pct !== undefined ? user.loss_pct : 0;
                  const riskLevel = user.risk_level || 'normal';
                  const isCritical = riskLevel === 'critical';

                  return (
                    <tr
                      key={user.user_id}
                      onClick={() => navigate(`/admin/users/${user.user_id}`)}
                      style={{
                        borderBottom: '1px solid var(--border-color)',
                        cursor: 'pointer',
                        transition: 'background 0.15s',
                        background: isCritical ? 'rgba(239, 68, 68, 0.05)' : 'transparent',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = isCritical ? 'rgba(239, 68, 68, 0.1)' : 'rgba(255, 255, 255, 0.03)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = isCritical ? 'rgba(239, 68, 68, 0.05)' : 'transparent')}
                    >
                      {/* User ID & Name */}
                      <td style={{ padding: '16px 18px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            width: '36px',
                            height: '36px',
                            borderRadius: '9px',
                            background: isCritical ? 'rgba(239, 68, 68, 0.2)' : 'rgba(59, 130, 246, 0.15)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: isCritical ? '#f87171' : '#60a5fa',
                            fontWeight: 700,
                            fontSize: '0.85rem',
                          }}>
                            {user.user_id.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <div style={{ fontWeight: 600, color: '#fff', fontSize: '0.92rem' }}>
                              <span>{user.user_id}</span>
                            </div>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{user.name}</div>
                          </div>
                        </div>
                      </td>

                      {/* Segments */}
                      <td style={{ padding: '16px 18px' }}>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          {['option', 'future', 'cash'].map((seg) => {
                            const isAllowed = user.allowed_segments?.includes(seg);
                            return (
                              <span
                                key={seg}
                                style={{
                                  padding: '3px 8px',
                                  borderRadius: '6px',
                                  fontSize: '0.75rem',
                                  fontWeight: 600,
                                  textTransform: 'uppercase',
                                  background: isAllowed ? 'rgba(59, 130, 246, 0.12)' : 'rgba(255, 255, 255, 0.03)',
                                  color: isAllowed ? '#60a5fa' : 'var(--text-muted)',
                                  border: isAllowed ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid rgba(255, 255, 255, 0.05)',
                                }}
                              >
                                {seg}
                              </span>
                            );
                          })}
                        </div>
                      </td>

                      {/* Balance & Risk (All-Segment Scope) */}
                      <td style={{ padding: '16px 18px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '180px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Balance:</span>
                            <span style={{ fontWeight: 600, color: '#fff' }}>
                              ₹{(user.balance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Available:</span>
                            <span style={{ fontWeight: 600, color: '#93c5fd' }}>
                              ₹{(user.available_balance !== undefined ? user.available_balance : (user.balance || 0)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.82rem', marginTop: '2px' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Loss:</span>
                            <span style={{ fontWeight: 600, color: lossPct >= 70 ? '#f87171' : lossPct >= 50 ? '#fbbf24' : 'var(--text-secondary)' }}>
                              {lossPct.toFixed(1)}%
                            </span>
                          </div>

                          {/* Risk Badge / Not Funded */}
                          <div style={{ marginTop: '4px' }}>
                            {!isFunded ? (
                              <span style={{
                                display: 'inline-block',
                                padding: '2px 8px',
                                borderRadius: '6px',
                                fontSize: '0.72rem',
                                fontWeight: 500,
                                background: 'rgba(255, 255, 255, 0.05)',
                                color: 'var(--text-muted)',
                                border: '1px solid rgba(255, 255, 255, 0.08)',
                              }}>
                                Not funded
                              </span>
                            ) : riskLevel === 'critical' ? (
                              <span style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px',
                                padding: '2px 8px',
                                borderRadius: '6px',
                                fontSize: '0.72rem',
                                fontWeight: 700,
                                background: 'rgba(239, 68, 68, 0.2)',
                                color: '#f87171',
                                border: '1px solid rgba(239, 68, 68, 0.4)',
                              }}>
                                <AlertTriangle size={11} /> CRITICAL ({lossPct.toFixed(0)}%)
                              </span>
                            ) : riskLevel === 'warning' ? (
                              <span style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px',
                                padding: '2px 8px',
                                borderRadius: '6px',
                                fontSize: '0.72rem',
                                fontWeight: 600,
                                background: 'rgba(245, 158, 11, 0.18)',
                                color: '#fbbf24',
                                border: '1px solid rgba(245, 158, 11, 0.35)',
                              }}>
                                <AlertTriangle size={11} /> Warning
                              </span>
                            ) : (
                              <span style={{
                                display: 'inline-block',
                                padding: '2px 8px',
                                borderRadius: '6px',
                                fontSize: '0.72rem',
                                fontWeight: 600,
                                background: 'rgba(16, 185, 129, 0.12)',
                                color: '#34d399',
                                border: '1px solid rgba(16, 185, 129, 0.25)',
                              }}>
                                Normal
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Active Status */}
                      <td style={{ padding: '16px 18px' }}>
                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '5px',
                          padding: '4px 10px',
                          borderRadius: '20px',
                          fontSize: '0.78rem',
                          fontWeight: 600,
                          background: user.is_active ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                          color: user.is_active ? '#34d399' : '#f87171',
                          border: user.is_active ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
                        }}>
                          {user.is_active ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                          <span>{user.is_active ? 'Active' : 'Disabled'}</span>
                        </span>
                      </td>

                      {/* Action */}
                      <td style={{ padding: '16px 18px', textAlign: 'right' }}
                          onClick={e => e.stopPropagation()}
                      >
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                          <div
                            onClick={() => navigate(`/admin/users/${user.user_id}`)}
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#60a5fa', fontSize: '0.85rem', fontWeight: 500, cursor: 'pointer' }}
                          >
                            <span>Inspect</span>
                            <ChevronRight size={16} />
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); setQuickDeleteConfirm(''); setQuickDeleteUser({ user_id: user.user_id, name: user.name }); }}
                            title="Delete user"
                            style={{
                              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                              width: '32px', height: '32px', borderRadius: '8px',
                              background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)',
                              color: '#f87171', cursor: 'pointer', transition: 'all 0.2s',
                            }}
                            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.25)'; }}
                            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.12)'; }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>

      {/* ────────── QUICK DELETE MODAL ────────── */}
      {quickDeleteUser && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0,0,0,0.78)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px',
        }}>
          <div style={{
            background: '#1a1f2e', borderRadius: '16px', padding: '32px',
            maxWidth: '440px', width: '100%',
            border: '1.5px solid rgba(239,68,68,0.45)',
            boxShadow: '0 0 60px rgba(239,68,68,0.25)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', background: 'rgba(239,68,68,0.18)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Trash2 size={20} color="#f87171" />
              </div>
              <div>
                <h3 style={{ margin: 0, color: '#f87171', fontSize: '1.1rem', fontWeight: 700 }}>Delete Trader Account</h3>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.82rem' }}>This is permanent. All trades and data will be erased.</p>
              </div>
            </div>

            <div style={{ background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '10px', padding: '12px', marginBottom: '18px' }}>
              <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.87rem' }}>
                Deleting: <strong style={{ color: '#fff' }}>{quickDeleteUser.user_id}</strong>
                {quickDeleteUser.name && <span style={{ color: 'var(--text-muted)' }}> ({quickDeleteUser.name})</span>}
              </p>
            </div>

            <label style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.84rem', marginBottom: '7px' }}>
              Type <strong style={{ color: '#f87171' }}>{quickDeleteUser.user_id}</strong> to confirm:
            </label>
            <input
              autoFocus
              value={quickDeleteConfirm}
              onChange={e => setQuickDeleteConfirm(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleQuickDelete(); if (e.key === 'Escape') setQuickDeleteUser(null); }}
              placeholder={quickDeleteUser.user_id}
              style={{
                width: '100%', boxSizing: 'border-box', padding: '10px 14px', borderRadius: '8px',
                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(239,68,68,0.35)',
                color: '#fff', fontSize: '0.95rem', outline: 'none', marginBottom: '20px',
              }}
            />

            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                onClick={() => setQuickDeleteUser(null)}
                style={{ flex: 1, padding: '11px', borderRadius: '10px', background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', fontWeight: 600, cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleQuickDelete}
                disabled={quickDeleteConfirm !== quickDeleteUser.user_id || quickDeleting}
                style={{
                  flex: 1, padding: '11px', borderRadius: '10px', fontWeight: 700, cursor: 'pointer',
                  background: quickDeleteConfirm === quickDeleteUser.user_id ? '#dc2626' : 'rgba(239,68,68,0.15)',
                  border: '1px solid rgba(239,68,68,0.4)', color: '#fff',
                  opacity: quickDeleteConfirm === quickDeleteUser.user_id ? 1 : 0.5,
                  transition: 'all 0.2s',
                }}
              >
                {quickDeleting ? 'Deleting...' : '🗑 Delete Forever'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default UserList;

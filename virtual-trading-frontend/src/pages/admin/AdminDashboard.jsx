import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ShieldCheck,
  TrendingUp,
  AlertCircle,
  Coins,
  Clock,
  Activity,
  Users,
  AlertTriangle,
  Layers,
  ArrowRight,
} from 'lucide-react';
import api from '../../api/api';

const AdminDashboard = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({
    brokerageToday: 0,
    brokerageTotal: 0,
    usersAwaitingSettlement: 0,
    usersWithStaleMtm: 0,
    totalUsers: 0,
    activeUsers: 0,
    criticalUsers: 0,
  });

  const fetchDashboardData = async () => {
    try {
      const [sumRes, usersRes] = await Promise.all([
        api.get('/admin/brokerage/summary').catch(() => ({ data: {} })),
        api.get('/admin/users').catch(() => ({ data: [] })),
      ]);

      const users = usersRes.data || [];
      const brokData = sumRes.data || {};

      let staleCount = 0;
      let settlementCount = 0;
      let criticalCount = 0;
      let activeCount = 0;

      users.forEach((u) => {
        if (u.is_active) activeCount++;
        if (u.mtm_stale) staleCount++;
        if (u.needs_settlement || u.has_expiring_trades) settlementCount++;
        if (u.risk_level === 'critical' || u.loss_pct >= 80) criticalCount++;
      });

      setStats({
        brokerageToday: brokData.total_brokerage_today || 0,
        brokerageTotal: brokData.total_brokerage_collected || 0,
        usersAwaitingSettlement: settlementCount,
        usersWithStaleMtm: staleCount,
        totalUsers: users.length,
        activeUsers: activeCount,
        criticalUsers: criticalCount,
      });
    } catch (err) {
      console.error('Failed to load admin dashboard stats:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ padding: '28px', maxWidth: '1280px', margin: '0 auto' }}>
      {/* Page Title */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: '#fff', margin: 0, letterSpacing: '-0.02em' }}>
          Simulation Control Desk
        </h1>
        <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          System-wide risk, settlement pipeline, and brokerage collection monitoring
        </span>
      </div>

      {/* Row 1: Key Prompt 7 Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        gap: '16px',
        marginBottom: '28px',
      }}>
        {/* Card 1: Brokerage Collected Today */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '20px 22px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Brokerage Today
              </span>
              <div style={{
                padding: '6px',
                borderRadius: '8px',
                background: 'rgba(16, 185, 129, 0.15)',
                color: '#10b981',
              }}>
                <Coins size={18} />
              </div>
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#10b981', marginBottom: '4px' }}>
              ₹{Number(stats.brokerageToday).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Total all-time: ₹{Number(stats.brokerageTotal).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
        </div>

        {/* Card 2: Brokerage Total Collected */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '20px 22px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Total Brokerage Collected
              </span>
              <div style={{
                padding: '6px',
                borderRadius: '8px',
                background: 'rgba(59, 130, 246, 0.15)',
                color: '#60a5fa',
              }}>
                <TrendingUp size={18} />
              </div>
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#60a5fa', marginBottom: '4px' }}>
              ₹{Number(stats.brokerageTotal).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Realized fees credited across all user trades
          </span>
        </div>

        {/* Card 3: Users Awaiting Settlement */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '20px 22px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Awaiting Settlement
              </span>
              <div style={{
                padding: '6px',
                borderRadius: '8px',
                background: stats.usersAwaitingSettlement > 0 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255, 255, 255, 0.05)',
                color: stats.usersAwaitingSettlement > 0 ? '#fbbf24' : 'var(--text-muted)',
              }}>
                <Clock size={18} />
              </div>
            </div>
            <div style={{
              fontSize: '1.8rem',
              fontWeight: 800,
              color: stats.usersAwaitingSettlement > 0 ? '#fbbf24' : '#fff',
              marginBottom: '4px',
            }}>
              {stats.usersAwaitingSettlement} <span style={{ fontSize: '1rem', fontWeight: 500 }}>users</span>
            </div>
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Contracts expired; engine retries every 60s
          </span>
        </div>

        {/* Card 4: Users with Stale MTM */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '20px 22px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Stale MTM Quotes
              </span>
              <div style={{
                padding: '6px',
                borderRadius: '8px',
                background: stats.usersWithStaleMtm > 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                color: stats.usersWithStaleMtm > 0 ? '#f87171' : '#34d399',
              }}>
                <Activity size={18} />
              </div>
            </div>
            <div style={{
              fontSize: '1.8rem',
              fontWeight: 800,
              color: stats.usersWithStaleMtm > 0 ? '#ef4444' : '#34d399',
              marginBottom: '4px',
            }}>
              {stats.usersWithStaleMtm} <span style={{ fontSize: '1rem', fontWeight: 500 }}>users</span>
            </div>
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Square-off automatically suspended when feed stale
          </span>
        </div>
      </div>

      {/* Row 2: Secondary Quick Actions & Links */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: '20px',
      }}>
        <div
          onClick={() => navigate('/admin/users')}
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '14px',
            padding: '20px 24px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            transition: 'border-color 0.2s',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <Users size={18} color="#06b6d4" />
              <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', margin: 0 }}>
                Trader Accounts ({stats.totalUsers})
              </h3>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
              {stats.activeUsers} active accounts | {stats.criticalUsers} critical risk
            </p>
          </div>
          <ArrowRight size={18} color="var(--text-muted)" />
        </div>

        <div
          onClick={() => navigate('/admin/brokerage-settings')}
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '14px',
            padding: '20px 24px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            transition: 'border-color 0.2s',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <Coins size={18} color="#f59e0b" />
              <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', margin: 0 }}>
                Brokerage Settings
              </h3>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
              Configure global rates for Index & MCX options, futures, and cash
            </p>
          </div>
          <ArrowRight size={18} color="var(--text-muted)" />
        </div>

        <div
          onClick={() => navigate('/admin/future-instruments')}
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '14px',
            padding: '20px 24px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            transition: 'border-color 0.2s',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <Layers size={18} color="#3b82f6" />
              <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', margin: 0 }}>
                Future Instruments & Margin
              </h3>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
              Set per-lot margin requirements for Index and MCX contracts
            </p>
          </div>
          <ArrowRight size={18} color="var(--text-muted)" />
        </div>
      </div>
    </div>
  );
};

export default AdminDashboard;

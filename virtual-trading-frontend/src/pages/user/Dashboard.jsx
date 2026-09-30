import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  TrendingUp,
  Activity,
  AlertCircle,
  LogOut,
  KeyRound,
  ShieldCheck,
  Wallet,
  Clock,
  Coins,
  CheckCircle,
  X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/api';
import TradeForm from './TradeForm';
import TradeHistory from './TradeHistory';

const Dashboard = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [limitStatus, setLimitStatus] = useState(null);
  const [instruments, setInstruments] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState('NIFTY');

  // Live LTP State
  const [ltpData, setLtpData] = useState(null);
  const [ltpLoading, setLtpLoading] = useState(false);
  const [ltpError, setLtpError] = useState(null);

  // Trigger to reload trades
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Toasts state
  const [toasts, setToasts] = useState([]);
  const prevPendingOrdersRef = useRef({});

  const addToast = (message, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 6000);
  };

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // 1. Fetch Limit Status & Risk Profile with Polling
  useEffect(() => {
    let isMounted = true;
    let timerId = null;

    const pollLimitStatus = async () => {
      try {
        const res = await api.get('/user/limit-status');
        if (isMounted) {
          setLimitStatus(res.data);
        }
      } catch (err) {
        console.error('Failed to load user limit status:', err);
      }
    };

    pollLimitStatus();
    timerId = setInterval(pollLimitStatus, 8000);

    return () => {
      isMounted = false;
      if (timerId) clearInterval(timerId);
    };
  }, [refreshTrigger]);

  // Track pending orders status changes to show toasts
  useEffect(() => {
    let isMounted = true;
    const pollOrdersForToasts = async () => {
      try {
        const res = await api.get('/user/orders');
        const orders = res.data.orders || [];
        const currentMap = {};
        orders.forEach((o) => {
          currentMap[o.order_id] = o.status;
          const prevStatus = prevPendingOrdersRef.current[o.order_id];
          if (prevStatus === 'PENDING' || prevStatus === 'MODIFYING') {
            if (o.status === 'EXECUTED') {
              addToast(`Order ${o.order_id} filled @ ₹${o.executed_price} (${o.tradingsymbol})`, 'success');
              setRefreshTrigger((prev) => prev + 1);
            } else if (o.status === 'REJECTED') {
              addToast(`Order ${o.order_id} REJECTED: ${o.reject_reason || 'Insufficient funds'}`, 'error');
              setRefreshTrigger((prev) => prev + 1);
            } else if (o.status === 'CANCELLED') {
              addToast(`Order ${o.order_id} cancelled (${o.tradingsymbol})`, 'info');
              setRefreshTrigger((prev) => prev + 1);
            }
          }
        });
        if (isMounted) {
          prevPendingOrdersRef.current = currentMap;
        }
      } catch (err) {
        console.debug('Failed to poll order status for toasts:', err);
      }
    };

    pollOrdersForToasts();
    const interval = setInterval(pollOrdersForToasts, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // 2. Fetch Allowed Instruments on load
  const fetchInstruments = async () => {
    try {
      const res = await api.get('/user/instruments');
      setInstruments(res.data.instruments || []);
    } catch (err) {
      console.error('Failed to load instruments:', err);
    }
  };

  useEffect(() => {
    fetchInstruments();
  }, []);

  // 3. LTP Polling for selected symbol
  useEffect(() => {
    let isMounted = true;
    let timerId = null;

    const pollLtp = async () => {
      if (!selectedSymbol) return;
      try {
        setLtpLoading((prev) => (ltpData ? false : true));
        const isMcx = ['GOLD', 'SILVER', 'CRUDEOIL', 'NATURALGAS', 'GOLDM', 'SILVERM', 'ZINC', 'COPPER', 'ALUMINIUM', 'LEAD'].includes(selectedSymbol.toUpperCase());
        const res = await api.get('/user/ltp', {
          params: { 
            symbol: selectedSymbol,
            segment: isMcx ? 'future' : 'cash',
          },
        });
        if (isMounted) {
          setLtpData(res.data);
          setLtpError(null);
        }
      } catch (err) {
        if (isMounted) {
          setLtpError(err.response?.data?.detail || 'Live quote feed unavailable');
          setLtpData(null);
        }
      } finally {
        if (isMounted) setLtpLoading(false);
      }
    };

    pollLtp();
    timerId = setInterval(pollLtp, 3000);

    return () => {
      isMounted = false;
      if (timerId) clearInterval(timerId);
    };
  }, [selectedSymbol]);

  const handleTradeSuccess = (trade) => {
    setRefreshTrigger((prev) => prev + 1);
    addToast(
      trade?.status === 'executed' || trade?.status === 'OPEN'
        ? `Order successfully executed: ${trade?.tradingsymbol || trade?.trade_id}`
        : `Limit order queued: ${trade?.tradingsymbol || trade?.order_id}`,
      'success'
    );
  };

  const handleTradeClosed = () => {
    setRefreshTrigger((prev) => prev + 1);
    addToast('Position squared off successfully', 'info');
  };

  const handleOrderUpdated = ({ orderId, status }) => {
    setRefreshTrigger((prev) => prev + 1);
    if (status === 'CANCELLED') {
      addToast(`Order ${orderId} cancelled`, 'info');
    } else if (status === 'MODIFIED') {
      addToast(`Order ${orderId} modified successfully`, 'success');
    }
  };

  const allowedSegments = limitStatus?.allowed_segments || user?.allowed_segments || ['option', 'future', 'cash'];
  const name = limitStatus?.name || user?.name || user?.user_id || 'Trader';

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-main)' }}>
      {/* Floating Toast Notification Container */}
      <div style={{
        position: 'fixed',
        top: '20px',
        right: '20px',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        maxWidth: '380px',
      }}>
        {toasts.map((toast) => (
          <div
            key={toast.id}
            style={{
              padding: '12px 16px',
              borderRadius: '10px',
              background: toast.type === 'success'
                ? 'rgba(16, 185, 129, 0.95)'
                : toast.type === 'error'
                ? 'rgba(239, 68, 68, 0.95)'
                : 'rgba(59, 130, 246, 0.95)',
              color: '#fff',
              fontSize: '0.85rem',
              fontWeight: 600,
              boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '10px',
              animation: 'fadeIn 0.2s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {toast.type === 'success' ? (
                <CheckCircle size={16} />
              ) : toast.type === 'error' ? (
                <AlertCircle size={16} />
              ) : (
                <Clock size={16} />
              )}
              <span>{toast.message}</span>
            </div>
            <button
              type="button"
              onClick={() => removeToast(toast.id)}
              style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', padding: 0 }}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>

      {/* Top Navigation */}
      <nav className="admin-nav">
        <div className="nav-brand">
          <div className="brand-logo">
            <TrendingUp size={20} color="#3b82f6" />
          </div>
          <span className="brand-title">Virtual Trading Simulation Desk</span>
        </div>

        <div className="nav-user">
          <div className="user-tag">
            <span>Trader: <strong style={{ color: '#fff' }}>{name}</strong></span>
          </div>

          <button
            onClick={() => navigate('/user/change-password')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              borderRadius: '8px',
              background: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
              fontSize: '0.82rem',
              cursor: 'pointer',
            }}
          >
            <KeyRound size={14} />
            <span>Security</span>
          </button>

          <button onClick={logout} className="logout-btn">
            <LogOut size={15} />
            <span>Sign Out</span>
          </button>
        </div>
      </nav>

      {/* Main Content Area */}
      <main style={{ flex: 1, padding: '28px', maxWidth: '1440px', width: '100%', margin: '0 auto' }}>
        {/* Row 1: Unified Trading Account Header & Metrics */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '22px 24px',
          marginBottom: '24px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '18px', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                background: 'rgba(59, 130, 246, 0.15)',
                color: '#60a5fa',
              }}>
                <Wallet size={18} />
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h2 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', letterSpacing: '-0.01em', margin: 0 }}>
                    Trading Account
                  </h2>
                </div>
                <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                  Real-time margin pool, brokerage monitor, and MTM risk status
                </span>
              </div>
            </div>

            {/* Risk Badge */}
            <div>
              {limitStatus?.risk_level === 'critical' ? (
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '5px 12px',
                  borderRadius: '20px',
                  fontSize: '0.78rem',
                  fontWeight: 700,
                  background: 'rgba(239, 68, 68, 0.2)',
                  color: '#f87171',
                  border: '1px solid rgba(239, 68, 68, 0.4)',
                }}>
                  <AlertCircle size={14} />
                  HIGH RISK — auto square-off imminent ({Number(limitStatus?.loss_pct || 0).toFixed(1)}% loss)
                </span>
              ) : limitStatus?.risk_level === 'warning' ? (
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '5px 12px',
                  borderRadius: '20px',
                  fontSize: '0.78rem',
                  fontWeight: 700,
                  background: 'rgba(245, 158, 11, 0.2)',
                  color: '#fbbf24',
                  border: '1px solid rgba(245, 158, 11, 0.4)',
                }}>
                  <AlertCircle size={14} />
                  Elevated Risk ({Number(limitStatus?.loss_pct || 0).toFixed(1)}% loss)
                </span>
              ) : (
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '5px 12px',
                  borderRadius: '20px',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  background: 'rgba(16, 185, 129, 0.15)',
                  color: '#34d399',
                  border: '1px solid rgba(16, 185, 129, 0.3)',
                }}>
                  <ShieldCheck size={14} />
                  Healthy
                </span>
              )}
            </div>
          </div>

          {/* 7 Stat Cards Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px' }}>
            {/* 1. Balance */}
            <div
              style={{
                background: 'var(--bg-input)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '16px 18px',
              }}
            >
              <div style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                Balance
              </div>
              <div style={{ fontSize: '1.3rem', fontWeight: 700, color: '#fff', marginBottom: '3px' }}>
                ₹{Number(limitStatus?.balance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                Allocated capital
              </div>
            </div>

            {/* 2. Available Balance */}
            <div
              style={{
                background: 'var(--bg-input)',
                border: Number(limitStatus?.available_balance || 0) <= 0 ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(59, 130, 246, 0.3)',
                borderRadius: '12px',
                padding: '16px 18px',
              }}
            >
              <div style={{ fontSize: '0.74rem', fontWeight: 600, color: '#60a5fa', textTransform: 'uppercase', marginBottom: '6px' }}>
                Available Balance
              </div>
              <div style={{
                fontSize: '1.3rem',
                fontWeight: 700,
                color: Number(limitStatus?.available_balance || 0) <= 0 ? '#ef4444' : '#60a5fa',
                marginBottom: '3px',
              }}>
                ₹{Number(limitStatus?.available_balance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                Free for new trades
              </div>
            </div>

            {/* 3. Margin Blocked */}
            <div
              style={{
                background: 'var(--bg-input)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '16px 18px',
              }}
            >
              <div style={{ fontSize: '0.74rem', fontWeight: 600, color: '#c084fc', textTransform: 'uppercase', marginBottom: '6px' }}>
                Margin Blocked
              </div>
              <div style={{ fontSize: '1.3rem', fontWeight: 700, color: '#e2e8f0', marginBottom: '3px' }}>
                ₹{Number(limitStatus?.margin_blocked || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                In open positions
              </div>
            </div>

            {/* 4. Blocked in Pending Orders */}
            <div
              style={{
                background: 'var(--bg-input)',
                border: '1px solid rgba(245, 158, 11, 0.3)',
                borderRadius: '12px',
                padding: '16px 18px',
              }}
            >
              <div style={{ fontSize: '0.74rem', fontWeight: 600, color: '#fbbf24', textTransform: 'uppercase', marginBottom: '6px' }}>
                Blocked in Pending
              </div>
              <div style={{ fontSize: '1.3rem', fontWeight: 700, color: '#fbbf24', marginBottom: '3px' }}>
                ₹{Number(limitStatus?.pending_reserved || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                {limitStatus?.pending_orders_count || 0} active limit orders
              </div>
            </div>

            {/* 5. Total Brokerage Paid */}
            <div
              style={{
                background: 'var(--bg-input)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '16px 18px',
              }}
            >
              <div style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                Total Brokerage
              </div>
              <div style={{ fontSize: '1.3rem', fontWeight: 700, color: '#cbd5e1', marginBottom: '3px' }}>
                ₹{Number(limitStatus?.total_brokerage_paid || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                Cumulative fees paid
              </div>
            </div>

            {/* 6. Live P&L (Unrealized) */}
            <div
              style={{
                background: 'var(--bg-input)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '16px 18px',
              }}
            >
              <div style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                Live P&L
              </div>
              <div style={{
                fontSize: '1.3rem',
                fontWeight: 700,
                color: Number(limitStatus?.unrealized_pnl || 0) > 0 ? '#10b981' : Number(limitStatus?.unrealized_pnl || 0) < 0 ? '#ef4444' : '#94a3b8',
                marginBottom: '3px',
              }}>
                {Number(limitStatus?.unrealized_pnl || 0) > 0 ? '+' : ''}₹{Number(limitStatus?.unrealized_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                Open positions
              </div>
            </div>

            {/* 7. Realized P&L */}
            <div
              style={{
                background: 'var(--bg-input)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '16px 18px',
              }}
            >
              <div style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                Realized P&L
              </div>
              <div style={{
                fontSize: '1.3rem',
                fontWeight: 700,
                color: Number(limitStatus?.realized_pnl || 0) > 0 ? '#10b981' : Number(limitStatus?.realized_pnl || 0) < 0 ? '#ef4444' : '#94a3b8',
                marginBottom: '3px',
              }}>
                {Number(limitStatus?.realized_pnl || 0) > 0 ? '+' : ''}₹{Number(limitStatus?.realized_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                Closed trades
              </div>
            </div>
          </div>
        </div>

        {/* Row 2: Live Market Ticker & Instrument Selector */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '20px 24px',
          marginBottom: '24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '16px',
        }}>
          {/* Instrument Selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-secondary)' }}>Watchlist:</span>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {(limitStatus?.allowed_instrument_types || []).includes('MCX')
                ? ['NIFTY', 'BANKNIFTY', 'SENSEX', 'GOLD', 'CRUDEOIL', 'SILVER', 'NATURALGAS'].map((sym) => (
                    <button
                      key={sym}
                      type="button"
                      onClick={() => setSelectedSymbol(sym)}
                      style={{
                        padding: '8px 16px',
                        borderRadius: '8px',
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        border: selectedSymbol === sym ? '1px solid #3b82f6' : '1px solid var(--border-color)',
                        background: selectedSymbol === sym ? 'rgba(59, 130, 246, 0.2)' : 'var(--bg-input)',
                        color: selectedSymbol === sym ? '#60a5fa' : 'var(--text-secondary)',
                        cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      {sym}
                    </button>
                  ))
                : ['NIFTY', 'BANKNIFTY', 'SENSEX'].map((sym) => (
                    <button
                      key={sym}
                      type="button"
                      onClick={() => setSelectedSymbol(sym)}
                      style={{
                        padding: '8px 16px',
                        borderRadius: '8px',
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        border: selectedSymbol === sym ? '1px solid #3b82f6' : '1px solid var(--border-color)',
                        background: selectedSymbol === sym ? 'rgba(59, 130, 246, 0.2)' : 'var(--bg-input)',
                        color: selectedSymbol === sym ? '#60a5fa' : 'var(--text-secondary)',
                        cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      {sym}
                    </button>
                  ))}
            </div>
          </div>

          {/* Live LTP Indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            {ltpLoading ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '0.88rem' }}>
                <div className="spinner" style={{ width: '16px', height: '16px' }} />
                <span>Polling quote...</span>
              </div>
            ) : ltpError ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '0.85rem' }}>
                <AlertCircle size={16} />
                <span>{ltpError}</span>
              </div>
            ) : ltpData ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    {ltpData.tradingsymbol} ({ltpData.exchange})
                  </div>
                  <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#10b981' }}>
                    ₹{ltpData.ltp?.toFixed(2)}
                  </div>
                </div>
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '3px 8px',
                  borderRadius: '12px',
                  background: 'rgba(16, 185, 129, 0.15)',
                  color: '#34d399',
                  fontSize: '0.72rem',
                  fontWeight: 600,
                }}>
                  <Activity size={12} />
                  LIVE
                </span>
              </div>
            ) : null}
          </div>
        </div>

        {/* Row 3: Trade Order Form & Position Book */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '24px' }}>
          <TradeForm
            allowedSegments={allowedSegments}
            limitStatus={limitStatus}
            allowedInstruments={instruments}
            selectedInstrument={selectedSymbol}
            currentLtp={ltpData?.ltp}
            onTradeSuccess={handleTradeSuccess}
          />

          <TradeHistory
            refreshTrigger={refreshTrigger}
            onTradeClosed={handleTradeClosed}
            onOrderUpdated={handleOrderUpdated}
          />
        </div>
      </main>
    </div>
  );
};

export default Dashboard;

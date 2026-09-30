import React, { useState, useEffect } from 'react';
import {
  Clock,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  ExternalLink,
  ChevronRight,
  TrendingDown,
  TrendingUp,
  Edit2,
  Trash2,
  X,
  AlertCircle,
} from 'lucide-react';
import api from '../../api/api';

const TradeHistory = ({ refreshTrigger, onTradeClosed, onOrderUpdated }) => {
  // Main view: 'positions' | 'pending' | 'history'
  const [mainTab, setMainTab] = useState('positions');

  // Segment subtab for positions
  const [positionSegment, setPositionSegment] = useState('option');

  // Data states
  const [trades, setTrades] = useState([]);
  const [pendingOrders, setPendingOrders] = useState([]);
  const [historyOrders, setHistoryOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Position closing state
  const [closingTradeId, setClosingTradeId] = useState(null);

  // Modify modal state
  const [modifyingOrder, setModifyingOrder] = useState(null);
  const [modifyPrice, setModifyPrice] = useState('');
  const [modifyLots, setModifyLots] = useState(1);
  const [modifyLoading, setModifyLoading] = useState(false);
  const [modifyError, setModifyError] = useState(null);

  // Metrics
  const [metrics, setMetrics] = useState({
    total_unrealized_pnl: 0,
    total_realized_pnl: 0,
    total_net_pnl: 0,
  });

  // 1. Fetch Open Positions
  const fetchTrades = async () => {
    try {
      const res = await api.get(`/user/trades/${positionSegment}`);
      setTrades(res.data.trades || []);
      setMetrics({
        total_unrealized_pnl: res.data.total_unrealized_pnl || 0,
        total_realized_pnl: res.data.total_realized_pnl || 0,
        total_net_pnl: res.data.total_net_pnl || 0,
      });
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch positions');
    }
  };

  // 2. Fetch Pending Orders (every 5 seconds)
  const fetchPendingOrders = async () => {
    try {
      const res = await api.get('/user/orders', { params: { status: 'PENDING' } });
      setPendingOrders(res.data.orders || []);
    } catch (err) {
      console.debug('Failed to fetch pending orders:', err);
    }
  };

  // 3. Fetch Order History
  const fetchOrderHistory = async () => {
    try {
      const res = await api.get('/user/orders');
      const all = res.data.orders || [];
      const historyOnly = all.filter(o => o.status !== 'PENDING' && o.status !== 'MODIFYING');
      setHistoryOrders(historyOnly);
    } catch (err) {
      console.debug('Failed to fetch order history:', err);
    }
  };

  useEffect(() => {
    if (mainTab === 'positions') {
      fetchTrades();
    } else if (mainTab === 'pending') {
      fetchPendingOrders();
    } else if (mainTab === 'history') {
      fetchOrderHistory();
    }
  }, [mainTab, positionSegment, refreshTrigger]);

  // Polling for Pending Orders every 5 seconds
  useEffect(() => {
    if (mainTab !== 'pending') return;
    fetchPendingOrders();
    const interval = setInterval(fetchPendingOrders, 5000);
    return () => clearInterval(interval);
  }, [mainTab]);

  // Polling for Positions live LTP every 3 seconds
  useEffect(() => {
    if (mainTab !== 'positions') return;
    const hasOpenTrades = trades.some(t => t.status === 'OPEN');
    if (!hasOpenTrades) return;

    const interval = setInterval(fetchTrades, 3000);
    return () => clearInterval(interval);
  }, [mainTab, trades, positionSegment]);

  // Handle Square Off / Close Position
  const handleCloseTrade = async (trade) => {
    if (!window.confirm(`Are you sure you want to square off ${trade.tradingsymbol || trade.instrument}?`)) {
      return;
    }

    setClosingTradeId(trade.trade_id);
    try {
      await api.post(`/user/trade/${positionSegment}/${trade.trade_id}/close`);
      await fetchTrades();
      if (onTradeClosed) onTradeClosed();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to square off position.');
    } finally {
      setClosingTradeId(null);
    }
  };

  // Handle Cancel Pending Order
  const handleCancelOrder = async (orderId) => {
    if (!window.confirm('Cancel this pending limit order?')) return;
    try {
      await api.delete(`/user/order/${orderId}`);
      await fetchPendingOrders();
      if (onOrderUpdated) onOrderUpdated({ orderId, status: 'CANCELLED' });
    } catch (err) {
      if (err.response?.status === 409) {
        alert('Order was already executed or cancelled by the market engine.');
        await fetchPendingOrders();
      } else {
        alert(err.response?.data?.detail || 'Failed to cancel order.');
      }
    }
  };

  // Open Modify Modal
  const openModifyModal = (order) => {
    setModifyingOrder(order);
    setModifyPrice(String(order.limit_price || ''));
    setModifyLots(order.lots || 1);
    setModifyError(null);
  };

  // Submit Modify
  const handleModifySubmit = async (e) => {
    e.preventDefault();
    if (!modifyingOrder) return;
    setModifyLoading(true);
    setModifyError(null);

    try {
      await api.put(`/user/order/${modifyingOrder.order_id}`, {
        limit_price: parseFloat(modifyPrice),
        lots: parseInt(modifyLots, 10),
      });
      setModifyingOrder(null);
      await fetchPendingOrders();
      if (onOrderUpdated) onOrderUpdated({ orderId: modifyingOrder.order_id, status: 'MODIFIED' });
    } catch (err) {
      if (err.response?.status === 409) {
        setModifyError('Order was already executed or cancelled.');
        setTimeout(() => {
          setModifyingOrder(null);
          fetchPendingOrders();
        }, 1500);
      } else {
        setModifyError(err.response?.data?.detail || 'Failed to modify order.');
      }
    } finally {
      setModifyLoading(false);
    }
  };

  // Helper for expiry countdown
  const getExpiryDetails = (expiryStr) => {
    if (!expiryStr) return null;
    const expDate = new Date(expiryStr);
    const now = new Date();
    const diffTime = expDate.setHours(15, 30, 0, 0) - now.getTime();
    const daysLeft = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return {
      date: expiryStr,
      daysLeft,
      isExpiringToday: daysLeft <= 0,
    };
  };

  // Total brokerage paid on visible trades
  const totalBrokeragePaid = trades.reduce((sum, t) => sum + (t.brokerage_total || (t.entry_brokerage || 0) + (t.exit_brokerage || 0)), 0);

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Top Header & Main 3 Tabs */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '14px',
          marginBottom: '20px',
        }}
      >
        <div>
          <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', margin: 0 }}>Position Book & Orders</h2>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Real-time positions, pending limits, and complete order history
          </span>
        </div>

        {/* Main 3 Tabs: Positions | Pending Orders | Order History */}
        <div style={{ display: 'flex', gap: '6px', background: 'var(--bg-input)', padding: '4px', borderRadius: '10px' }}>
          <button
            type="button"
            onClick={() => setMainTab('positions')}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '0.82rem',
              fontWeight: 700,
              border: 'none',
              background: mainTab === 'positions' ? '#3b82f6' : 'transparent',
              color: mainTab === 'positions' ? '#fff' : 'var(--text-muted)',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            Positions
          </button>

          <button
            type="button"
            onClick={() => setMainTab('pending')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '0.82rem',
              fontWeight: 700,
              border: 'none',
              background: mainTab === 'pending' ? '#10b981' : 'transparent',
              color: mainTab === 'pending' ? '#fff' : 'var(--text-muted)',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            <span>Pending Orders</span>
            {pendingOrders.length > 0 && (
              <span style={{
                background: mainTab === 'pending' ? '#fff' : '#10b981',
                color: mainTab === 'pending' ? '#10b981' : '#fff',
                fontSize: '0.7rem',
                borderRadius: '10px',
                padding: '1px 6px',
                fontWeight: 800,
              }}>
                {pendingOrders.length}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setMainTab('history')}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '0.82rem',
              fontWeight: 700,
              border: 'none',
              background: mainTab === 'history' ? '#8b5cf6' : 'transparent',
              color: mainTab === 'history' ? '#fff' : 'var(--text-muted)',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            Order History
          </button>
        </div>
      </div>

      {/* --- TAB 1: POSITIONS --- */}
      {mainTab === 'positions' && (
        <>
          {/* Segment subtab switchers */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
            <div style={{ display: 'flex', gap: '6px' }}>
              {['option', 'future', 'cash'].map((seg) => (
                <button
                  key={seg}
                  type="button"
                  onClick={() => setPositionSegment(seg)}
                  style={{
                    padding: '5px 12px',
                    borderRadius: '6px',
                    fontSize: '0.78rem',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    border: positionSegment === seg ? '1px solid #3b82f6' : '1px solid var(--border-color)',
                    background: positionSegment === seg ? 'rgba(59, 130, 246, 0.15)' : 'var(--bg-input)',
                    color: positionSegment === seg ? '#60a5fa' : 'var(--text-muted)',
                    cursor: 'pointer',
                  }}
                >
                  {seg}
                </button>
              ))}
            </div>

            {/* P&L Snapshot */}
            <div style={{ display: 'flex', gap: '16px', fontSize: '0.82rem' }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Unrealized: </span>
                <strong style={{ color: metrics.total_unrealized_pnl >= 0 ? '#10b981' : '#ef4444' }}>
                  {metrics.total_unrealized_pnl >= 0 ? '+' : ''}₹{metrics.total_unrealized_pnl.toFixed(2)}
                </strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Realized: </span>
                <strong style={{ color: metrics.total_realized_pnl >= 0 ? '#10b981' : '#ef4444' }}>
                  {metrics.total_realized_pnl >= 0 ? '+' : ''}₹{metrics.total_realized_pnl.toFixed(2)}
                </strong>
              </div>
            </div>
          </div>

          {/* Positions Table */}
          <div style={{ overflowX: 'auto', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                  <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Contract / Expiry</th>
                  <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Action & Qty</th>
                  <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Margin Locked</th>
                  <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Entry / LTP</th>
                  <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Brokerage</th>
                  <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Net P&L</th>
                  <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.88rem' }}>
                      No open {positionSegment} positions found.
                    </td>
                  </tr>
                ) : (
                  trades.map((t) => {
                    const isOpen = t.status === 'OPEN';
                    const isBuy = t.action === 'BUY';
                    const expInfo = getExpiryDetails(t.expiry);
                    const brok = t.brokerage_total !== undefined ? t.brokerage_total : (t.entry_brokerage || 0) + (t.exit_brokerage || 0);
                    const netPnl = t.net_pnl !== undefined ? t.net_pnl : (t.pnl || 0) - brok;

                    return (
                      <tr
                        key={t.trade_id}
                        style={{
                          borderBottom: '1px solid var(--border-color)',
                          background: isOpen ? 'transparent' : 'rgba(255, 255, 255, 0.01)',
                        }}
                      >
                        {/* Contract & CF / Expiry badges */}
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <strong style={{ color: '#fff', fontSize: '0.88rem' }}>{t.tradingsymbol || t.instrument}</strong>
                            {t.segment === 'option' && (
                              <span style={{
                                padding: '1px 5px',
                                borderRadius: '4px',
                                fontSize: '0.68rem',
                                fontWeight: 800,
                                background: 'rgba(6, 182, 212, 0.2)',
                                color: '#06b6d4',
                                border: '1px solid rgba(6, 182, 212, 0.4)',
                              }}>
                                CF
                              </span>
                            )}
                          </div>

                          {expInfo && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px' }}>
                              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                Exp: {expInfo.date} ({expInfo.daysLeft}d left)
                              </span>
                              {expInfo.isExpiringToday && (
                                <span style={{
                                  padding: '1px 5px',
                                  borderRadius: '4px',
                                  fontSize: '0.65rem',
                                  fontWeight: 700,
                                  background: 'rgba(245, 158, 11, 0.2)',
                                  color: '#fbbf24',
                                  border: '1px solid rgba(245, 158, 11, 0.4)',
                                }}>
                                  Expiring today
                                </span>
                              )}
                            </div>
                          )}
                        </td>

                        {/* Action & Qty */}
                        <td style={{ padding: '12px 14px' }}>
                          <span
                            style={{
                              padding: '2px 7px',
                              borderRadius: '4px',
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              background: isBuy ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                              color: isBuy ? '#34d399' : '#f87171',
                              marginRight: '6px',
                            }}
                          >
                            {t.action}
                          </span>
                          <span style={{ fontSize: '0.85rem', color: '#e2e8f0' }}>
                            {t.qty} qty {t.lots ? `(${t.lots} lots)` : ''}
                          </span>
                        </td>

                        {/* Margin Locked */}
                        <td style={{ padding: '12px 14px', fontSize: '0.85rem', color: '#cbd5e1' }}>
                          ₹{Number(t.margin_blocked_amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>

                        {/* Entry / LTP */}
                        <td style={{ padding: '12px 14px', fontSize: '0.85rem' }}>
                          <div>
                            <span style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>Entry: </span>
                            <span style={{ color: '#fff' }}>₹{Number(t.entry_price || 0).toFixed(2)}</span>
                          </div>
                          <div>
                            <span style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>{isOpen ? 'LTP: ' : 'Exit: '}</span>
                            <span style={{ color: isOpen ? '#60a5fa' : '#94a3b8' }}>
                              ₹{Number(isOpen ? (t.current_ltp ?? t.current_price ?? t.entry_price ?? 0) : (t.exit_price || 0)).toFixed(2)}
                            </span>
                          </div>
                        </td>

                        {/* Brokerage */}
                        <td style={{ padding: '12px 14px', fontSize: '0.82rem', color: '#fbbf24' }}>
                          ₹{Number(brok).toFixed(2)}
                        </td>

                        {/* Net P&L */}
                        <td style={{ padding: '12px 14px' }}>
                          <strong
                            style={{
                              fontSize: '0.95rem',
                              color: netPnl > 0 ? '#10b981' : netPnl < 0 ? '#ef4444' : '#94a3b8',
                            }}
                          >
                            {netPnl > 0 ? '+' : ''}₹{Number(netPnl).toFixed(2)}
                          </strong>
                          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                            Gross: {t.pnl >= 0 ? '+' : ''}₹{Number(t.pnl || 0).toFixed(2)}
                          </div>
                        </td>

                        {/* Action / Square off */}
                        <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                          {isOpen ? (
                            <button
                              type="button"
                              onClick={() => handleCloseTrade(t)}
                              disabled={closingTradeId === t.trade_id}
                              style={{
                                padding: '5px 12px',
                                borderRadius: '6px',
                                fontSize: '0.75rem',
                                fontWeight: 700,
                                border: 'none',
                                background: 'rgba(239, 68, 68, 0.2)',
                                color: '#f87171',
                                border: '1px solid rgba(239, 68, 68, 0.4)',
                                cursor: 'pointer',
                              }}
                            >
                              {closingTradeId === t.trade_id ? 'Closing...' : 'Square Off'}
                            </button>
                          ) : (
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                              {t.closed_by || 'CLOSED'}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Footer Total Brokerage Paid */}
          {trades.length > 0 && (
            <div style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: '16px',
              padding: '12px 16px',
              marginTop: '10px',
              background: 'var(--bg-input)',
              borderRadius: '8px',
              fontSize: '0.82rem',
            }}>
              <span style={{ color: 'var(--text-muted)' }}>Total Brokerage Paid (Visible):</span>
              <strong style={{ color: '#fbbf24' }}>₹{totalBrokeragePaid.toFixed(2)}</strong>
            </div>
          )}
        </>
      )}

      {/* --- TAB 2: PENDING ORDERS --- */}
      {mainTab === 'pending' && (
        <div style={{ overflowX: 'auto', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Order ID / Contract</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Action & Qty</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Limit Price</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Current LTP</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Distance</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Reserved Total</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Placed At</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pendingOrders.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.88rem' }}>
                    No pending limit orders currently waiting in queue.
                  </td>
                </tr>
              ) : (
                pendingOrders.map((ord) => {
                  const isBuy = ord.action === 'BUY';
                  const ltp = ord.current_ltp || ord.limit_price;
                  const distance = ltp > 0 ? (((ord.limit_price - ltp) / ltp) * 100).toFixed(2) : '0.00';

                  return (
                    <tr key={ord.order_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '12px 14px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <strong style={{ color: '#fff', fontSize: '0.88rem' }}>{ord.tradingsymbol || ord.instrument}</strong>
                          <span style={{
                            padding: '1px 5px',
                            borderRadius: '4px',
                            fontSize: '0.65rem',
                            fontWeight: 700,
                            background: 'rgba(59, 130, 246, 0.2)',
                            color: '#60a5fa',
                          }}>
                            {ord.segment?.toUpperCase()}
                          </span>
                        </div>
                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          ID: {ord.order_id}
                        </span>
                      </td>

                      <td style={{ padding: '12px 14px' }}>
                        <span
                          style={{
                            padding: '2px 7px',
                            borderRadius: '4px',
                            fontSize: '0.72rem',
                            fontWeight: 700,
                            background: isBuy ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                            color: isBuy ? '#34d399' : '#f87171',
                            marginRight: '6px',
                          }}
                        >
                          {ord.action}
                        </span>
                        <span style={{ fontSize: '0.85rem', color: '#e2e8f0' }}>
                          {ord.qty} qty ({ord.lots} lots)
                        </span>
                      </td>

                      <td style={{ padding: '12px 14px', fontSize: '0.9rem', fontWeight: 700, color: '#34d399' }}>
                        ₹{Number(ord.limit_price || 0).toFixed(2)}
                      </td>

                      <td style={{ padding: '12px 14px', fontSize: '0.88rem', color: '#60a5fa' }}>
                        ₹{Number(ltp).toFixed(2)}
                      </td>

                      <td style={{ padding: '12px 14px', fontSize: '0.82rem', color: Number(distance) >= 0 ? '#10b981' : '#f87171' }}>
                        {Number(distance) >= 0 ? '+' : ''}{distance}%
                      </td>

                      <td style={{ padding: '12px 14px', fontSize: '0.85rem', color: '#fbbf24' }}>
                        ₹{Number(ord.reserved_total || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>

                      <td style={{ padding: '12px 14px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {ord.created_at ? new Date(ord.created_at).toLocaleTimeString() : '—'}
                      </td>

                      <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px' }}>
                          <button
                            type="button"
                            onClick={() => openModifyModal(ord)}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '5px 10px',
                              borderRadius: '6px',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              background: 'rgba(59, 130, 246, 0.15)',
                              color: '#60a5fa',
                              border: '1px solid rgba(59, 130, 246, 0.3)',
                              cursor: 'pointer',
                            }}
                          >
                            <Edit2 size={12} />
                            <span>Modify</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => handleCancelOrder(ord.order_id)}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '5px 10px',
                              borderRadius: '6px',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              background: 'rgba(239, 68, 68, 0.15)',
                              color: '#f87171',
                              border: '1px solid rgba(239, 68, 68, 0.3)',
                              cursor: 'pointer',
                            }}
                          >
                            <Trash2 size={12} />
                            <span>Cancel</span>
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
      )}

      {/* --- TAB 3: ORDER HISTORY --- */}
      {mainTab === 'history' && (
        <div style={{ overflowX: 'auto', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Order ID / Time</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Contract</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Type & Action</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Limit / Executed Price</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Qty</th>
                <th style={{ padding: '10px 14px', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {historyOrders.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.88rem' }}>
                    No terminal orders recorded in history.
                  </td>
                </tr>
              ) : (
                historyOrders.map((ord) => (
                  <tr key={ord.order_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '12px 14px' }}>
                      <div style={{ fontSize: '0.8rem', color: '#fff', fontWeight: 600 }}>{ord.order_id}</div>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        {ord.created_at ? new Date(ord.created_at).toLocaleString() : '—'}
                      </span>
                    </td>

                    <td style={{ padding: '12px 14px' }}>
                      <strong style={{ color: '#fff', fontSize: '0.85rem' }}>{ord.tradingsymbol || ord.instrument}</strong>
                      <span style={{ marginLeft: '6px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        ({ord.segment})
                      </span>
                    </td>

                    <td style={{ padding: '12px 14px' }}>
                      <span style={{
                        padding: '2px 6px',
                        borderRadius: '4px',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        background: ord.action === 'BUY' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                        color: ord.action === 'BUY' ? '#34d399' : '#f87171',
                        marginRight: '6px',
                      }}>
                        {ord.action}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>LIMIT</span>
                    </td>

                    <td style={{ padding: '12px 14px', fontSize: '0.85rem', color: '#e2e8f0' }}>
                      <div>Limit: ₹{Number(ord.limit_price || 0).toFixed(2)}</div>
                      {ord.executed_price && (
                        <div style={{ color: '#34d399', fontSize: '0.75rem' }}>
                          Filled @ ₹{Number(ord.executed_price).toFixed(2)}
                        </div>
                      )}
                    </td>

                    <td style={{ padding: '12px 14px', fontSize: '0.85rem', color: '#e2e8f0' }}>
                      {ord.qty} qty
                    </td>

                    <td style={{ padding: '12px 14px' }}>
                      <span
                        style={{
                          padding: '3px 8px',
                          borderRadius: '12px',
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          background:
                            ord.status === 'EXECUTED'
                              ? 'rgba(16, 185, 129, 0.15)'
                              : ord.status === 'CANCELLED'
                              ? 'rgba(148, 163, 184, 0.15)'
                              : 'rgba(239, 68, 68, 0.15)',
                          color:
                            ord.status === 'EXECUTED'
                              ? '#34d399'
                              : ord.status === 'CANCELLED'
                              ? '#94a3b8'
                              : '#f87171',
                        }}
                      >
                        {ord.status}
                      </span>
                      {ord.reject_reason && (
                        <div style={{ fontSize: '0.7rem', color: '#f87171', marginTop: '2px' }}>
                          {ord.reject_reason}
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* --- MODIFY PENDING ORDER MODAL --- */}
      {modifyingOrder && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 999,
          padding: '16px',
        }}>
          <div style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '16px',
            width: '100%',
            maxWidth: '440px',
            padding: '24px',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', margin: 0 }}>
                  Modify Pending Order
                </h3>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  {modifyingOrder.tradingsymbol} ({modifyingOrder.action})
                </span>
              </div>
              <button
                type="button"
                onClick={() => setModifyingOrder(null)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleModifySubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  New Limit Price (₹)
                </label>
                <input
                  type="number"
                  step="0.05"
                  min="0.05"
                  value={modifyPrice}
                  onChange={(e) => setModifyPrice(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    color: '#fff',
                    fontSize: '1rem',
                    fontWeight: 700,
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Lots (Lot Size: {modifyingOrder.lot_size})
                </label>
                <input
                  type="number"
                  min="1"
                  max="500"
                  value={modifyLots}
                  onChange={(e) => setModifyLots(Math.max(1, parseInt(e.target.value, 10) || 1))}
                  required
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    color: '#fff',
                    fontSize: '0.95rem',
                    fontWeight: 600,
                  }}
                />
              </div>

              {modifyError && (
                <div style={{
                  padding: '8px 12px',
                  borderRadius: '6px',
                  background: 'rgba(239, 68, 68, 0.15)',
                  color: '#f87171',
                  fontSize: '0.78rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}>
                  <AlertCircle size={14} />
                  <span>{modifyError}</span>
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '6px' }}>
                <button
                  type="button"
                  onClick={() => setModifyingOrder(null)}
                  style={{
                    padding: '10px',
                    borderRadius: '8px',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-secondary)',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={modifyLoading}
                  style={{
                    padding: '10px',
                    borderRadius: '8px',
                    background: '#3b82f6',
                    border: 'none',
                    color: '#fff',
                    fontWeight: 700,
                    cursor: modifyLoading ? 'not-allowed' : 'pointer',
                  }}
                >
                  {modifyLoading ? 'Updating...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default TradeHistory;

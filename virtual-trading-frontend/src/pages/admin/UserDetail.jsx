import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../../api/api';
import {
  ArrowLeft,
  KeyRound,
  Layers,
  AlertOctagon,
  Copy,
  Check,
  CheckCircle2,
  AlertCircle,
  Wallet,
  PlusCircle,
  Sliders,
  AlertTriangle,
  Trash2,
  RefreshCcw,
  Percent,
  Clock,
  XCircle,
  Shield,
  FileText,
} from 'lucide-react';

const UserDetail = () => {
  const { userId } = useParams();
  const navigate = useNavigate();

  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionMessage, setActionMessage] = useState({ type: '', text: '' });

  // Segments & Instrument Types Editing
  const [selectedSegments, setSelectedSegments] = useState([]);
  const [savingSegments, setSavingSegments] = useState(false);
  const [selectedInstrumentTypes, setSelectedInstrumentTypes] = useState(['INDEX']);
  const [savingInstrumentTypes, setSavingInstrumentTypes] = useState(false);

  // Brokerage Overrides & Global Configs
  const [userBrokerageConfigs, setUserBrokerageConfigs] = useState([]);
  const [globalBrokerageConfigs, setGlobalBrokerageConfigs] = useState([]);
  const [loadingBrokerage, setLoadingBrokerage] = useState(false);
  const [overrideForm, setOverrideForm] = useState({
    segment: 'option',
    instrument_type: 'any',
    mode: 'PER_LOT',
    value: '',
  });
  const [savingOverride, setSavingOverride] = useState(false);

  // Balance Modification Forms
  const [setBalanceInput, setSetBalanceInput] = useState('');
  const [settingBalance, setSettingBalance] = useState(false);
  const [setBalanceFeedback, setSetBalanceFeedback] = useState(null);

  const [addFundsInput, setAddFundsInput] = useState('');
  const [addingFunds, setAddingFunds] = useState(false);
  const [addFundsFeedback, setAddFundsFeedback] = useState(null);

  // Password Reset Modal / State
  const [tempPassword, setTempPassword] = useState('');
  const [copied, setCopied] = useState(false);
  const [resettingPassword, setResettingPassword] = useState(false);

  // Force Close Modal
  const [showForceCloseModal, setShowForceCloseModal] = useState(false);
  const [forceClosing, setForceClosing] = useState(false);

  // Delete User Modal
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');

  // Reset Account Modal
  const [showResetModal, setShowResetModal] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetBalance, setResetBalance] = useState('100000');
  const [resetConfirmText, setResetConfirmText] = useState('');

  // Trade History & Pending Orders Tabs
  const [activeTab, setActiveTab] = useState('option'); // 'option' | 'future' | 'cash' | 'pending'
  const [trades, setTrades] = useState([]);
  const [loadingTrades, setLoadingTrades] = useState(false);
  const [pendingOrders, setPendingOrders] = useState([]);
  const [loadingOrders, setLoadingOrders] = useState(false);
  const [cancellingOrderId, setCancellingOrderId] = useState(null);

  const fetchUser = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/admin/users/${userId}`);
      setUser(res.data);
      setSelectedSegments(res.data.allowed_segments || []);
      setSelectedInstrumentTypes(res.data.allowed_instrument_types || ['INDEX']);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load user profile');
    } finally {
      setLoading(false);
    }
  };

  const fetchBrokerage = async () => {
    setLoadingBrokerage(true);
    try {
      const [uRes, gRes] = await Promise.all([
        api.get(`/admin/brokerage?scope=user&user_id=${userId}`),
        api.get(`/admin/brokerage?scope=global`),
      ]);
      setUserBrokerageConfigs(uRes.data?.configs || []);
      setGlobalBrokerageConfigs(gRes.data?.configs || []);
    } catch (err) {
      console.error('Error fetching brokerage configs:', err);
    } finally {
      setLoadingBrokerage(false);
    }
  };

  const fetchTrades = async (seg) => {
    setLoadingTrades(true);
    try {
      const res = await api.get(`/admin/users/${userId}/trades?segment=${seg}`);
      setTrades(res.data?.trades || []);
    } catch (err) {
      console.error('Error fetching trades:', err);
      setTrades([]);
    } finally {
      setLoadingTrades(false);
    }
  };

  const fetchPendingOrders = async () => {
    setLoadingOrders(true);
    try {
      const res = await api.get(`/admin/users/${userId}/orders?status=PENDING`);
      setPendingOrders(res.data?.orders || []);
    } catch (err) {
      console.error('Error fetching pending orders:', err);
      setPendingOrders([]);
    } finally {
      setLoadingOrders(false);
    }
  };

  useEffect(() => {
    fetchUser();
    fetchBrokerage();
  }, [userId]);

  useEffect(() => {
    if (user) {
      if (activeTab === 'pending') {
        fetchPendingOrders();
      } else {
        fetchTrades(activeTab);
      }
    }
  }, [activeTab, user?.user_id]);

  // Handle Save Allowed Segments
  const handleSaveSegments = async () => {
    setSavingSegments(true);
    setActionMessage({ type: '', text: '' });
    try {
      await api.put(`/admin/users/${userId}/segments`, {
        allowed_segments: selectedSegments,
      });
      setActionMessage({ type: 'success', text: 'Allowed segments updated successfully.' });
      fetchUser();
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to update segments.' });
    } finally {
      setSavingSegments(false);
    }
  };

  // Handle Save Allowed Instrument Types
  const handleSaveInstrumentTypes = async () => {
    setSavingInstrumentTypes(true);
    setActionMessage({ type: '', text: '' });
    try {
      await api.put(`/admin/users/${userId}/instrument-types`, {
        allowed_instrument_types: selectedInstrumentTypes,
      });
      setActionMessage({ type: 'success', text: 'Allowed instrument types updated successfully.' });
      fetchUser();
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to update instrument types.' });
    } finally {
      setSavingInstrumentTypes(false);
    }
  };

  // Handle Add/Update User Brokerage Override
  const handleSaveOverride = async (e) => {
    e.preventDefault();
    if (!overrideForm.value || isNaN(overrideForm.value)) {
      setActionMessage({ type: 'error', text: 'Please enter a valid numeric brokerage rate.' });
      return;
    }
    setSavingOverride(true);
    setActionMessage({ type: '', text: '' });
    try {
      await api.put(`/admin/users/${userId}/brokerage`, {
        segment: overrideForm.segment,
        instrument_type: overrideForm.instrument_type,
        mode: overrideForm.mode,
        value: parseFloat(overrideForm.value),
        enabled: true,
      });
      setActionMessage({
        type: 'success',
        text: `Brokerage override for ${overrideForm.segment.toUpperCase()} (${overrideForm.instrument_type}) saved successfully.`,
      });
      setOverrideForm({ segment: 'option', instrument_type: 'any', mode: 'PER_LOT', value: '' });
      fetchBrokerage();
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to save brokerage override.' });
    } finally {
      setSavingOverride(false);
    }
  };

  // Handle Delete Brokerage Override
  const handleDeleteOverride = async (segment, instrumentType) => {
    if (!window.confirm(`Delete override for ${segment.toUpperCase()} (${instrumentType})? It will revert to global default.`)) return;
    setActionMessage({ type: '', text: '' });
    try {
      await api.delete(`/admin/users/${userId}/brokerage?segment=${segment}&instrument_type=${instrumentType}`);
      setActionMessage({ type: 'success', text: `Brokerage override for ${segment.toUpperCase()} removed.` });
      fetchBrokerage();
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to remove override.' });
    }
  };

  // Handle Admin Cancel Pending Order
  const handleCancelOrder = async (orderId) => {
    if (!window.confirm(`Cancel pending order ${orderId}? This will immediately unlock reserved margin and brokerage for ${userId}.`)) return;
    setCancellingOrderId(orderId);
    setActionMessage({ type: '', text: '' });
    try {
      await api.post(`/admin/users/${userId}/orders/${orderId}/cancel`);
      setActionMessage({ type: 'success', text: `Order ${orderId} cancelled by Admin. Reserved funds unlocked.` });
      fetchPendingOrders();
      fetchUser();
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to cancel order.' });
    } finally {
      setCancellingOrderId(null);
    }
  };

  // Handle Set Balance
  const handleSetBalance = async (e) => {
    e.preventDefault();
    if (!setBalanceInput || isNaN(setBalanceInput)) return;

    setSettingBalance(true);
    setSetBalanceFeedback(null);
    setActionMessage({ type: '', text: '' });

    const prevBalance = user.balance || 0;
    const targetBalance = parseFloat(setBalanceInput);

    try {
      const res = await api.put(`/admin/users/${userId}/balance/set`, {
        balance: targetBalance,
      });
      
      const newBal = res.data?.balance ?? targetBalance;
      const newAvail = res.data?.available_balance ?? targetBalance;
      
      setSetBalanceFeedback({
        oldBalance: prevBalance,
        newBalance: newBal,
        available: newAvail,
      });
      
      setActionMessage({
        type: 'success',
        text: `Balance for ${userId} updated: ₹${prevBalance.toLocaleString('en-IN')} → ₹${newBal.toLocaleString('en-IN')} (Available: ₹${newAvail.toLocaleString('en-IN')})`,
      });
      
      setSetBalanceInput('');
      fetchUser();
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to set balance.' });
    } finally {
      setSettingBalance(false);
    }
  };

  // Handle Add Funds
  const handleAddFunds = async (e) => {
    e.preventDefault();
    if (!addFundsInput || isNaN(addFundsInput)) return;

    setAddingFunds(true);
    setAddFundsFeedback(null);
    setActionMessage({ type: '', text: '' });

    const prevBalance = user.balance || 0;
    const amountToAdd = parseFloat(addFundsInput);

    try {
      const res = await api.put(`/admin/users/${userId}/balance/add`, {
        amount: amountToAdd,
      });
      
      const newBal = res.data?.balance ?? (prevBalance + amountToAdd);
      const newAvail = res.data?.available_balance ?? (user.available_balance + amountToAdd);

      setAddFundsFeedback({
        amount: amountToAdd,
        oldBalance: prevBalance,
        newBalance: newBal,
        available: newAvail,
      });

      setActionMessage({
        type: 'success',
        text: `Successfully ${amountToAdd >= 0 ? 'added' : 'deducted'} ₹${Math.abs(amountToAdd).toLocaleString('en-IN')} to ${userId}. New balance: ₹${newBal.toLocaleString('en-IN')}`,
      });

      setAddFundsInput('');
      fetchUser();
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to add funds.' });
    } finally {
      setAddingFunds(false);
    }
  };

  // Handle Password Reset
  const handleResetPassword = async () => {
    setResettingPassword(true);
    setTempPassword('');
    setActionMessage({ type: '', text: '' });
    try {
      const res = await api.put(`/admin/users/${userId}/reset-password`);
      setTempPassword(res.data?.temp_password || 'VTrade@NewPass123');
      setActionMessage({
        type: 'success',
        text: `Password reset successfully for ${userId}. Temporary password generated below.`,
      });
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to reset password.' });
    } finally {
      setResettingPassword(false);
    }
  };

  const copyToClipboard = () => {
    if (tempPassword) {
      navigator.clipboard.writeText(tempPassword);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // Handle Force Close All
  const handleConfirmForceClose = async () => {
    setForceClosing(true);
    try {
      const res = await api.post(`/admin/users/${userId}/force-close-all`);
      setShowForceCloseModal(false);
      setActionMessage({
        type: 'success',
        text: res.data?.message || 'All open positions have been forcefully closed.',
      });
      fetchUser();
      if (activeTab === 'pending') {
        fetchPendingOrders();
      } else {
        fetchTrades(activeTab);
      }
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to force close trades.' });
      setShowForceCloseModal(false);
    } finally {
      setForceClosing(false);
    }
  };

  // Handle Delete User
  const handleDeleteUser = async () => {
    if (deleteConfirmText !== userId) return;
    setDeleting(true);
    try {
      await api.delete(`/admin/users/${userId}`);
      setShowDeleteModal(false);
      navigate('/admin/users', { replace: true });
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to delete user.' });
      setShowDeleteModal(false);
    } finally {
      setDeleting(false);
    }
  };

  // Handle Reset Account
  const handleResetAccount = async () => {
    if (resetConfirmText !== 'RESET') return;
    setResetting(true);
    try {
      const res = await api.post(`/admin/users/${userId}/reset-account`, {
        new_balance: parseFloat(resetBalance) || 100000,
      });
      setShowResetModal(false);
      setResetConfirmText('');
      setActionMessage({
        type: 'success',
        text: res.data?.message || 'Account reset successfully.',
      });
      fetchUser();
      fetchBrokerage();
      if (activeTab === 'pending') {
        fetchPendingOrders();
      } else {
        fetchTrades(activeTab);
      }
    } catch (err) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to reset account.' });
      setShowResetModal(false);
    } finally {
      setResetting(false);
    }
  };

  // Brokerage Resolution Helper
  const resolveEffectiveRate = (seg, itype) => {
    const s = seg.toLowerCase();
    const t = (itype || 'any').toUpperCase();

    // 1. User + segment + itype
    const uSpecific = userBrokerageConfigs.find((c) => c.segment === s && (c.instrument_type || 'ANY').toUpperCase() === t && c.enabled !== false);
    if (uSpecific) return { config: uSpecific, source: 'User Override (Specific)' };

    // 2. User + segment + ANY
    const uAny = userBrokerageConfigs.find((c) => c.segment === s && (c.instrument_type || 'ANY').toUpperCase() === 'ANY' && c.enabled !== false);
    if (uAny) return { config: uAny, source: 'User Override (Segment Default)' };

    // 3. Global + segment + itype
    const gSpecific = globalBrokerageConfigs.find((c) => c.segment === s && (c.instrument_type || 'ANY').toUpperCase() === t && c.enabled !== false);
    if (gSpecific) return { config: gSpecific, source: 'Global (Specific)' };

    // 4. Global + segment + ANY
    const gAny = globalBrokerageConfigs.find((c) => c.segment === s && (c.instrument_type || 'ANY').toUpperCase() === 'ANY' && c.enabled !== false);
    if (gAny) return { config: gAny, source: 'Global Default' };

    return { config: null, source: 'Zero (No Config)' };
  };

  if (loading) {
    return (
      <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
        <div className="spinner" style={{ margin: '0 auto 16px auto' }} />
        <p>Loading trader details for {userId}...</p>
      </div>
    );
  }

  if (error || !user) {
    return (
      <div style={{ padding: '32px', maxWidth: '800px', margin: '0 auto' }}>
        <button onClick={() => navigate('/admin/users')} style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'transparent', border: 'none', color: '#60a5fa', cursor: 'pointer', marginBottom: '16px' }}>
          <ArrowLeft size={16} /> Back to Trader Accounts
        </button>
        <div className="alert-error">
          <AlertCircle size={18} />
          <span>{error || 'Trader profile not found.'}</span>
        </div>
      </div>
    );
  }

  const isFunded = user.balance && user.balance > 0;
  const lossPct = user.loss_pct !== undefined ? user.loss_pct : 0;
  const riskLevel = user.risk_level || 'normal';

  return (
    <>
    <div style={{ padding: '32px', maxWidth: '1400px', width: '100%', margin: '0 auto' }}>
      {/* Top Breadcrumb & Actions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', flexWrap: 'wrap', gap: '16px' }}>
        <button
          onClick={() => navigate('/admin/users')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            background: 'transparent',
            border: 'none',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            fontSize: '0.88rem',
          }}
        >
          <ArrowLeft size={16} />
          <span>Back to Trader Accounts</span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Force Close All Button */}
          <button
            onClick={() => setShowForceCloseModal(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 16px',
              borderRadius: '10px',
              background: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              color: '#f87171',
              fontSize: '0.88rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            <AlertOctagon size={16} />
            <span>Force Close All Trades</span>
          </button>

          {/* Reset Password Button */}
          <button
            onClick={handleResetPassword}
            disabled={resettingPassword}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 16px',
              borderRadius: '10px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              color: '#fff',
              fontSize: '0.88rem',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            <KeyRound size={16} color="#fbbf24" />
            <span>{resettingPassword ? 'Resetting...' : 'Reset Password'}</span>
          </button>

          {/* Reset Account Button */}
          <button
            onClick={() => { setResetConfirmText(''); setShowResetModal(true); }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 16px',
              borderRadius: '10px',
              background: 'rgba(245, 158, 11, 0.12)',
              border: '1px solid rgba(245, 158, 11, 0.4)',
              color: '#fbbf24',
              fontSize: '0.88rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            <RefreshCcw size={16} />
            <span>Reset Account</span>
          </button>

          {/* Delete User Button */}
          <button
            onClick={() => { setDeleteConfirmText(''); setShowDeleteModal(true); }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 16px',
              borderRadius: '10px',
              background: 'rgba(239, 68, 68, 0.18)',
              border: '1px solid rgba(239, 68, 68, 0.5)',
              color: '#f87171',
              fontSize: '0.88rem',
              fontWeight: 700,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            <Trash2 size={16} />
            <span>Delete User</span>
          </button>
        </div>
      </div>

      {/* Action Notification Alert */}
      {actionMessage.text && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '12px 16px',
            borderRadius: '10px',
            marginBottom: '20px',
            background: actionMessage.type === 'success' ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
            border: actionMessage.type === 'success' ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
            color: actionMessage.type === 'success' ? '#6ee7b7' : '#fca5a5',
            fontSize: '0.88rem',
          }}
        >
          {actionMessage.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
          <span>{actionMessage.text}</span>
        </div>
      )}

      {/* Generated Temp Password Banner */}
      {tempPassword && (
        <div style={{
          padding: '16px 20px',
          background: 'rgba(245, 158, 11, 0.12)',
          border: '1px solid rgba(245, 158, 11, 0.35)',
          borderRadius: '12px',
          marginBottom: '24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
        }}>
          <div>
            <div style={{ fontSize: '0.8rem', color: '#fbbf24', textTransform: 'uppercase', fontWeight: 600 }}>Temporary Password Generated</div>
            <div style={{ fontSize: '1.2rem', fontFamily: 'monospace', fontWeight: 700, color: '#fff', marginTop: '2px' }}>
              {tempPassword}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
              Share this password with the trader. They will be forced to change it upon login.
            </div>
          </div>
          <button
            onClick={copyToClipboard}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              borderRadius: '8px',
              background: copied ? '#10b981' : '#f59e0b',
              border: 'none',
              color: '#000',
              fontWeight: 600,
              fontSize: '0.82rem',
              cursor: 'pointer',
            }}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            <span>{copied ? 'Copied!' : 'Copy Password'}</span>
          </button>
        </div>
      )}

      {/* Profile Overview Header Card */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '24px 28px',
        marginBottom: '24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '20px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '54px',
            height: '54px',
            borderRadius: '14px',
            background: 'linear-gradient(135deg, #2563eb, #06b6d4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1.4rem',
            fontWeight: 700,
            color: '#fff',
            boxShadow: '0 4px 20px rgba(37, 99, 235, 0.4)',
          }}>
            {user.user_id.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#fff' }}>{user.user_id}</h1>
              <span style={{
                padding: '3px 10px',
                borderRadius: '20px',
                fontSize: '0.75rem',
                fontWeight: 600,
                background: user.is_active ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                color: user.is_active ? '#34d399' : '#f87171',
                border: user.is_active ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
              }}>
                {user.is_active ? 'Active Account' : 'Deactivated'}
              </span>
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '2px' }}>
              Full Name: <strong style={{ color: '#fff' }}>{user.name}</strong> • Created on {new Date(user.created_at).toLocaleDateString()}
            </div>
          </div>
        </div>
      </div>

      {/* Trading Account (All Segments) */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '24px 28px',
        marginBottom: '28px',
        boxShadow: '0 8px 30px rgba(0, 0, 0, 0.3)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Wallet size={22} color="#3b82f6" />
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', margin: 0 }}>Trading Account</h2>
              
              {/* Risk Badge */}
              {!isFunded ? (
                <span style={{
                  padding: '3px 10px',
                  borderRadius: '20px',
                  fontSize: '0.75rem',
                  fontWeight: 500,
                  background: 'rgba(255, 255, 255, 0.05)',
                  color: 'var(--text-muted)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                }}>
                  Not Funded
                </span>
              ) : riskLevel === 'critical' ? (
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '3px 10px',
                  borderRadius: '20px',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  background: 'rgba(239, 68, 68, 0.2)',
                  color: '#f87171',
                  border: '1px solid rgba(239, 68, 68, 0.4)',
                }}>
                  <AlertTriangle size={12} /> CRITICAL RISK ({lossPct.toFixed(1)}% Loss)
                </span>
              ) : riskLevel === 'warning' ? (
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '3px 10px',
                  borderRadius: '20px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  background: 'rgba(245, 158, 11, 0.18)',
                  color: '#fbbf24',
                  border: '1px solid rgba(245, 158, 11, 0.35)',
                }}>
                  <AlertTriangle size={12} /> Warning ({lossPct.toFixed(1)}% Loss)
                </span>
              ) : (
                <span style={{
                  padding: '3px 10px',
                  borderRadius: '20px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  background: 'rgba(16, 185, 129, 0.12)',
                  color: '#34d399',
                  border: '1px solid rgba(16, 185, 129, 0.25)',
                }}>
                  Healthy Account
                </span>
              )}
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', marginTop: '4px' }}>
              Capital allocation, active margin locks, live portfolio equity, and fund management across all segments.
            </p>
          </div>
        </div>

        {/* Auto Square-Off Notice */}
        {user.last_auto_square_off_at && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '12px 16px',
            borderRadius: '10px',
            background: 'rgba(239, 68, 68, 0.12)',
            border: '1px solid rgba(239, 68, 68, 0.35)',
            color: '#fca5a5',
            fontSize: '0.85rem',
            marginBottom: '20px',
          }}>
            <AlertOctagon size={18} color="#f87171" />
            <span>
              <strong>System Notice:</strong> Auto square-off triggered on {new Date(user.last_auto_square_off_at).toLocaleString()}
            </span>
          </div>
        )}

        {/* 6 Margin & Brokerage Stat Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px', marginBottom: '24px' }}>
          {/* Card 1: Balance */}
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Allocated Balance</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#fff', marginTop: '4px' }}>
              ₹{(user.balance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Card 2: Available Margin */}
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Available Margin</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#60a5fa', marginTop: '4px' }}>
              ₹{(user.available_balance !== undefined ? user.available_balance : (user.balance || 0)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Card 3: Margin Blocked */}
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Margin Blocked</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#fbbf24', marginTop: '4px' }}>
              ₹{(user.margin_blocked || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Card 4: Equity */}
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Portfolio Equity</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#fff', marginTop: '4px' }}>
              ₹{(user.equity !== undefined ? user.equity : (user.balance || 0)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Card 5: Loss % */}
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Loss Percentage</div>
            <div style={{
              fontSize: '1.35rem',
              fontWeight: 700,
              color: lossPct >= 70 ? '#ef4444' : lossPct >= 50 ? '#f59e0b' : '#34d399',
              marginTop: '4px'
            }}>
              {lossPct.toFixed(1)}%
            </div>
          </div>

          {/* Card 6: Total Brokerage Paid */}
          <div style={{ background: 'var(--bg-input)', border: '1px solid rgba(139, 92, 246, 0.3)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontSize: '0.75rem', color: '#c4b5fd', textTransform: 'uppercase', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Percent size={13} color="#a78bfa" /> Brokerage Paid
            </div>
            <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#a78bfa', marginTop: '4px' }}>
              ₹{(user.total_brokerage_paid || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>

        {/* Balance Management Action Panels */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
          {/* Panel A: Set Balance Form */}
          <div style={{
            background: 'var(--bg-input)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
          }}>
            <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#fff', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sliders size={16} color="#3b82f6" />
              <span>Set Exact Balance</span>
            </h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '14px' }}>
              Directly set a new total capital balance for this user account.
            </p>

            <form onSubmit={handleSetBalance}>
              <div style={{ display: 'flex', gap: '10px' }}>
                <div style={{ flex: 1 }}>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    placeholder="e.g. 100000"
                    className="form-input"
                    value={setBalanceInput}
                    onChange={(e) => setSetBalanceInput(e.target.value)}
                    style={{ padding: '9px 12px', fontSize: '0.88rem' }}
                    required
                  />
                </div>
                <button
                  type="submit"
                  disabled={settingBalance}
                  className="submit-btn"
                  style={{ margin: 0, padding: '9px 16px', width: 'auto', fontSize: '0.85rem' }}
                >
                  {settingBalance ? 'Updating...' : 'Set Balance'}
                </button>
              </div>
            </form>

            {setBalanceFeedback && (
              <div style={{
                marginTop: '12px',
                padding: '10px 12px',
                borderRadius: '8px',
                background: 'rgba(59, 130, 246, 0.1)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                fontSize: '0.8rem',
                color: '#93c5fd',
              }}>
                <div><strong>Previous Balance:</strong> ₹{setBalanceFeedback.oldBalance.toLocaleString('en-IN')}</div>
                <div><strong>New Balance:</strong> ₹{setBalanceFeedback.newBalance.toLocaleString('en-IN')}</div>
                <div><strong>New Available:</strong> ₹{setBalanceFeedback.available.toLocaleString('en-IN')}</div>
              </div>
            )}
          </div>

          {/* Panel B: Add / Deduct Funds Form */}
          <div style={{
            background: 'var(--bg-input)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
          }}>
            <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#fff', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <PlusCircle size={16} color="#10b981" />
              <span>Add / Top-Up Funds</span>
            </h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '14px' }}>
              Add extra funds to current balance (or enter negative value to deduct).
            </p>

            <form onSubmit={handleAddFunds}>
              <div style={{ display: 'flex', gap: '10px' }}>
                <div style={{ flex: 1 }}>
                  <input
                    type="number"
                    step="any"
                    placeholder="e.g. 50000 or -10000"
                    className="form-input"
                    value={addFundsInput}
                    onChange={(e) => setAddFundsInput(e.target.value)}
                    style={{ padding: '9px 12px', fontSize: '0.88rem' }}
                    required
                  />
                </div>
                <button
                  type="submit"
                  disabled={addingFunds}
                  className="submit-btn"
                  style={{
                    margin: 0,
                    padding: '9px 16px',
                    width: 'auto',
                    fontSize: '0.85rem',
                    background: 'linear-gradient(135deg, #10b981, #059669)',
                  }}
                >
                  {addingFunds ? 'Processing...' : 'Add Funds'}
                </button>
              </div>
            </form>

            {addFundsFeedback && (
              <div style={{
                marginTop: '12px',
                padding: '10px 12px',
                borderRadius: '8px',
                background: 'rgba(16, 185, 129, 0.1)',
                border: '1px solid rgba(16, 185, 129, 0.25)',
                fontSize: '0.8rem',
                color: '#6ee7b7',
              }}>
                <div><strong>Amount Changed:</strong> {addFundsFeedback.amount >= 0 ? '+' : ''}₹{addFundsFeedback.amount.toLocaleString('en-IN')}</div>
                <div><strong>Previous Balance:</strong> ₹{addFundsFeedback.oldBalance.toLocaleString('en-IN')}</div>
                <div><strong>Updated Balance:</strong> ₹{addFundsFeedback.newBalance.toLocaleString('en-IN')}</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Permissions Grid: Segments & Instrument Types */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '24px', marginBottom: '28px' }}>
        {/* Permitted Segments */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '24px',
        }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 600, color: '#fff', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Layers size={18} color="#60a5fa" />
            <span>Permitted Segments</span>
          </h3>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
            Toggle segment trading authorization for this account.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '18px' }}>
            {[
              { id: 'option', label: 'Options (NIFTY / BANKNIFTY / SENSEX)' },
              { id: 'future', label: 'Futures (Derivatives)' },
              { id: 'cash', label: 'Cash (Equities)' },
            ].map(({ id, label }) => (
              <label
                key={id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: selectedSegments.includes(id) ? 'rgba(59, 130, 246, 0.1)' : 'var(--bg-input)',
                  border: selectedSegments.includes(id) ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid var(--border-color)',
                  cursor: 'pointer',
                  fontSize: '0.88rem',
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedSegments.includes(id)}
                  onChange={() => {
                    if (selectedSegments.includes(id)) {
                      setSelectedSegments(selectedSegments.filter((s) => s !== id));
                    } else {
                      setSelectedSegments([...selectedSegments, id]);
                    }
                  }}
                  style={{ accentColor: '#3b82f6', width: '16px', height: '16px' }}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>

          <button
            onClick={handleSaveSegments}
            disabled={savingSegments}
            className="submit-btn"
            style={{ margin: 0, padding: '10px 20px', width: 'auto', fontSize: '0.88rem' }}
          >
            {savingSegments ? 'Updating...' : 'Save Permitted Segments'}
          </button>
        </div>

        {/* Permitted Instrument Types */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '24px',
        }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 600, color: '#fff', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Shield size={18} color="#a78bfa" />
            <span>Permitted Instrument Types</span>
          </h3>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
            Authorize trading on Index contracts (NSE/BSE) and/or MCX Commodity derivatives.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '18px' }}>
            {[
              { id: 'INDEX', label: 'Index Instruments (NIFTY, BANKNIFTY, SENSEX)', badge: 'NSE / BSE' },
              { id: 'MCX', label: 'Commodity Instruments (GOLD, SILVER, CRUDEOIL, etc.)', badge: 'MCX' },
            ].map(({ id, label, badge }) => (
              <label
                key={id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '10px',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: selectedInstrumentTypes.includes(id) ? 'rgba(167, 139, 250, 0.12)' : 'var(--bg-input)',
                  border: selectedInstrumentTypes.includes(id) ? '1px solid rgba(167, 139, 250, 0.35)' : '1px solid var(--border-color)',
                  cursor: 'pointer',
                  fontSize: '0.88rem',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <input
                    type="checkbox"
                    checked={selectedInstrumentTypes.includes(id)}
                    onChange={() => {
                      if (selectedInstrumentTypes.includes(id)) {
                        setSelectedInstrumentTypes(selectedInstrumentTypes.filter((t) => t !== id));
                      } else {
                        setSelectedInstrumentTypes([...selectedInstrumentTypes, id]);
                      }
                    }}
                    style={{ accentColor: '#a78bfa', width: '16px', height: '16px' }}
                  />
                  <span>{label}</span>
                </div>
                <span style={{
                  padding: '2px 8px',
                  borderRadius: '4px',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  background: 'rgba(255,255,255,0.06)',
                  color: 'var(--text-muted)',
                }}>
                  {badge}
                </span>
              </label>
            ))}
          </div>

          <button
            onClick={handleSaveInstrumentTypes}
            disabled={savingInstrumentTypes}
            className="submit-btn"
            style={{
              margin: 0,
              padding: '10px 20px',
              width: 'auto',
              fontSize: '0.88rem',
              background: 'linear-gradient(135deg, #8b5cf6, #6366f1)',
            }}
          >
            {savingInstrumentTypes ? 'Updating...' : 'Save Instrument Types'}
          </button>
        </div>
      </div>

      {/* Per-User Brokerage Overrides & Effective Rates */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '24px',
        marginBottom: '32px',
        boxShadow: '0 8px 30px rgba(0, 0, 0, 0.3)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '18px', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Percent size={20} color="#34d399" />
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', margin: 0 }}>Brokerage Rates & Overrides</h3>
            </div>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Configure custom user discounts or premiums. Overrides take precedence over global matrix settings.
            </p>
          </div>
          <button
            onClick={fetchBrokerage}
            disabled={loadingBrokerage}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              borderRadius: '8px',
              background: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.82rem',
            }}
          >
            <RefreshCcw size={14} className={loadingBrokerage ? 'spin' : ''} />
            <span>Refresh Rates</span>
          </button>
        </div>

        {/* Active Overrides Table */}
        <div style={{ marginBottom: '24px' }}>
          <h4 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '10px' }}>
            Active Overrides for {userId}
          </h4>
          {userBrokerageConfigs.length === 0 ? (
            <div style={{
              padding: '16px',
              borderRadius: '10px',
              background: 'rgba(255, 255, 255, 0.02)',
              border: '1px dashed var(--border-color)',
              color: 'var(--text-muted)',
              fontSize: '0.85rem',
              textAlign: 'center',
            }}>
              No custom overrides set for this user. Global matrix rates currently apply.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                    <th style={{ padding: '10px 14px', fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Segment</th>
                    <th style={{ padding: '10px 14px', fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Instrument Type</th>
                    <th style={{ padding: '10px 14px', fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Mode</th>
                    <th style={{ padding: '10px 14px', fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Rate Value</th>
                    <th style={{ padding: '10px 14px', fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Updated</th>
                    <th style={{ padding: '10px 14px', fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {userBrokerageConfigs.map((cfg, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '12px 14px', fontWeight: 600, color: '#fff', textTransform: 'uppercase' }}>
                        {cfg.segment}
                      </td>
                      <td style={{ padding: '12px 14px' }}>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          background: 'rgba(59, 130, 246, 0.15)',
                          color: '#60a5fa',
                        }}>
                          {cfg.instrument_type || 'ANY'}
                        </span>
                      </td>
                      <td style={{ padding: '12px 14px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                        {cfg.mode === 'PER_LOT' ? 'Per Lot' : '% Turnover'}
                      </td>
                      <td style={{ padding: '12px 14px', fontWeight: 700, color: '#34d399', fontSize: '0.92rem' }}>
                        {cfg.mode === 'PER_LOT' ? `₹${cfg.value} / lot` : `${cfg.value}%`}
                      </td>
                      <td style={{ padding: '12px 14px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        {cfg.updated_at ? new Date(cfg.updated_at).toLocaleString() : '—'}
                      </td>
                      <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                        <button
                          onClick={() => handleDeleteOverride(cfg.segment, cfg.instrument_type || 'any')}
                          style={{
                            padding: '6px 12px',
                            borderRadius: '6px',
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            color: '#f87171',
                            cursor: 'pointer',
                            fontSize: '0.78rem',
                            fontWeight: 600,
                          }}
                        >
                          Remove Override
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Set / Update Override Form */}
        <div style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border-color)',
          borderRadius: '12px',
          padding: '20px',
          marginBottom: '24px',
        }}>
          <h4 style={{ fontSize: '0.9rem', color: '#fff', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <PlusCircle size={15} color="#34d399" /> Set User Override
          </h4>
          <form onSubmit={handleSaveOverride} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr)) 120px', gap: '12px', alignItems: 'flex-end' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '4px' }}>Segment</label>
              <select
                className="form-input"
                style={{ padding: '8px 10px', fontSize: '0.85rem' }}
                value={overrideForm.segment}
                onChange={(e) => setOverrideForm({ ...overrideForm, segment: e.target.value })}
              >
                <option value="option">Option</option>
                <option value="future">Future</option>
                <option value="cash">Cash</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '4px' }}>Instrument Type</label>
              <select
                className="form-input"
                style={{ padding: '8px 10px', fontSize: '0.85rem' }}
                value={overrideForm.instrument_type}
                onChange={(e) => setOverrideForm({ ...overrideForm, instrument_type: e.target.value })}
              >
                <option value="any">Any (All)</option>
                <option value="INDEX">Index</option>
                <option value="MCX">MCX Commodity</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '4px' }}>Calculation Mode</label>
              <select
                className="form-input"
                style={{ padding: '8px 10px', fontSize: '0.85rem' }}
                value={overrideForm.mode}
                onChange={(e) => setOverrideForm({ ...overrideForm, mode: e.target.value })}
              >
                <option value="PER_LOT">PER_LOT (₹ / lot)</option>
                <option value="PERCENT">PERCENT (% of turnover)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                Rate ({overrideForm.mode === 'PER_LOT' ? '₹' : '%'})
              </label>
              <input
                type="number"
                step="any"
                min="0"
                placeholder={overrideForm.mode === 'PER_LOT' ? 'e.g. 20' : 'e.g. 0.03'}
                className="form-input"
                style={{ padding: '8px 10px', fontSize: '0.85rem' }}
                value={overrideForm.value}
                onChange={(e) => setOverrideForm({ ...overrideForm, value: e.target.value })}
                required
              />
            </div>

            <button
              type="submit"
              disabled={savingOverride}
              className="submit-btn"
              style={{
                margin: 0,
                padding: '9px 16px',
                width: '100%',
                fontSize: '0.85rem',
                background: 'linear-gradient(135deg, #10b981, #059669)',
              }}
            >
              {savingOverride ? 'Saving...' : 'Apply Rate'}
            </button>
          </form>
        </div>

        {/* Effective Rate Comparison Preview */}
        <div>
          <h4 style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '10px' }}>
            Effective Rate Comparison Preview
          </h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
            {[
              { label: 'Options (Index)', seg: 'option', itype: 'INDEX' },
              { label: 'Futures (Index)', seg: 'future', itype: 'INDEX' },
              { label: 'Futures (MCX)', seg: 'future', itype: 'MCX' },
              { label: 'Cash (Equities)', seg: 'cash', itype: 'any' },
            ].map(({ label, seg, itype }) => {
              const eff = resolveEffectiveRate(seg, itype);
              const isOverride = eff.source.includes('User Override');
              return (
                <div
                  key={label}
                  style={{
                    padding: '12px 14px',
                    borderRadius: '10px',
                    background: isOverride ? 'rgba(16, 185, 129, 0.08)' : 'rgba(255, 255, 255, 0.02)',
                    border: isOverride ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid var(--border-color)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem', color: '#fff' }}>{label}</div>
                    <span style={{
                      fontSize: '0.7rem',
                      fontWeight: 600,
                      padding: '2px 6px',
                      borderRadius: '4px',
                      background: isOverride ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255, 255, 255, 0.06)',
                      color: isOverride ? '#34d399' : 'var(--text-muted)',
                    }}>
                      {eff.source}
                    </span>
                  </div>
                  <div style={{ marginTop: '8px', fontSize: '1.1rem', fontWeight: 700, color: eff.config ? '#38bdf8' : 'var(--text-muted)' }}>
                    {eff.config ? (
                      eff.config.mode === 'PER_LOT' ? `₹${eff.config.value} / lot` : `${eff.config.value}%`
                    ) : (
                      '₹0 (No Config)'
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Trade Execution History & Pending Orders Tabs */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '24px',
        boxShadow: '0 8px 30px rgba(0, 0, 0, 0.3)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h3 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', margin: 0 }}>
              {activeTab === 'pending' ? 'Active Pending (Limit) Orders' : 'Trade Execution History'}
            </h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              {activeTab === 'pending'
                ? 'Unfilled limit orders waiting for market trigger. Admin can cancel to release locked balance.'
                : 'Audit individual filled orders, brokerage deductions, expiry settlements, and net P&L performance.'}
            </p>
          </div>

          {/* Tab Selector */}
          <div style={{ display: 'flex', background: 'var(--bg-input)', padding: '4px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
            {[
              { id: 'option', label: 'Option Trades' },
              { id: 'future', label: 'Future Trades' },
              { id: 'cash', label: 'Cash Trades' },
              { id: 'pending', label: 'Pending Orders' },
            ].map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                style={{
                  padding: '6px 16px',
                  borderRadius: '8px',
                  border: 'none',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  background: activeTab === id ? (id === 'pending' ? '#f59e0b' : '#2563eb') : 'transparent',
                  color: activeTab === id ? (id === 'pending' ? '#000' : '#fff') : 'var(--text-secondary)',
                  transition: 'all 0.2s',
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab Content: Pending Orders */}
        {activeTab === 'pending' ? (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', minWidth: '900px' }}>
              <thead>
                <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                  <th style={{ padding: '12px 16px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Order ID / Symbol</th>
                  <th style={{ padding: '12px 16px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Side / Type</th>
                  <th style={{ padding: '12px 16px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Quantity / Lots</th>
                  <th style={{ padding: '12px 16px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Limit Price</th>
                  <th style={{ padding: '12px 16px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Reserved Funds</th>
                  <th style={{ padding: '12px 16px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Placed At</th>
                  <th style={{ padding: '12px 16px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loadingOrders ? (
                  <tr>
                    <td colSpan={7} style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      <div className="spinner" style={{ margin: '0 auto 8px auto' }} />
                      <span>Loading pending limit orders...</span>
                    </td>
                  </tr>
                ) : pendingOrders.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      No active pending limit orders for this user.
                    </td>
                  </tr>
                ) : (
                  pendingOrders.map((o) => (
                    <tr key={o.order_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '14px 16px' }}>
                        <div style={{ fontWeight: 600, color: '#fff', fontSize: '0.9rem' }}>{o.tradingsymbol || o.symbol}</div>
                        <div style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-muted)' }}>{o.order_id}</div>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: '4px',
                          fontWeight: 700,
                          fontSize: '0.75rem',
                          background: o.action === 'BUY' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                          color: o.action === 'BUY' ? '#34d399' : '#f87171',
                          marginRight: '6px',
                        }}>
                          {o.action}
                        </span>
                        <span style={{
                          padding: '2px 6px',
                          borderRadius: '4px',
                          fontSize: '0.72rem',
                          background: 'rgba(245, 158, 11, 0.15)',
                          color: '#fbbf24',
                          fontWeight: 600,
                        }}>
                          LIMIT
                        </span>
                      </td>
                      <td style={{ padding: '14px 16px', color: 'var(--text-secondary)', fontSize: '0.88rem' }}>
                        {o.qty} ({o.lots} {o.lots === 1 ? 'lot' : 'lots'})
                      </td>
                      <td style={{ padding: '14px 16px', fontWeight: 600, color: '#fff', fontSize: '0.92rem' }}>
                        ₹{Number(o.price || 0).toFixed(2)}
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <div style={{ fontSize: '0.88rem', fontWeight: 600, color: '#fbbf24' }}>
                          ₹{Number(o.reserved_total || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                          Margin: ₹{Number(o.reserved_margin || 0).toFixed(2)} • Brok: ₹{Number(o.reserved_brokerage || 0).toFixed(2)}
                        </div>
                      </td>
                      <td style={{ padding: '14px 16px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        {new Date(o.created_at).toLocaleTimeString()} ({new Date(o.created_at).toLocaleDateString()})
                      </td>
                      <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                        <button
                          onClick={() => handleCancelOrder(o.order_id)}
                          disabled={cancellingOrderId === o.order_id}
                          style={{
                            padding: '6px 12px',
                            borderRadius: '6px',
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.4)',
                            color: '#f87171',
                            cursor: 'pointer',
                            fontSize: '0.8rem',
                            fontWeight: 600,
                          }}
                        >
                          {cancellingOrderId === o.order_id ? 'Cancelling...' : 'Cancel Order'}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : (
          /* Tab Content: Option, Future, or Cash Trades Table */
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', minWidth: '1000px' }}>
              <thead>
                <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Trade / Symbol</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Action / Qty</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Margin Used</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Entry / Exit</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Gross P&L</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Brokerage</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Net P&L</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Status</th>
                  <th style={{ padding: '12px 14px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Timestamps</th>
                </tr>
              </thead>
              <tbody>
                {loadingTrades ? (
                  <tr>
                    <td colSpan={9} style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      <div className="spinner" style={{ margin: '0 auto 8px auto' }} />
                      <span>Loading {activeTab} trades...</span>
                    </td>
                  </tr>
                ) : trades.length === 0 ? (
                  <tr>
                    <td colSpan={9} style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      No {activeTab} trades recorded for this user.
                    </td>
                  </tr>
                ) : (
                  trades.map((t) => {
                    const totalBrok = Number(t.brokerage_total || ((t.entry_brokerage || 0) + (t.exit_brokerage || 0)) || 0);
                    const netPnl = t.net_pnl !== undefined ? Number(t.net_pnl) : (Number(t.pnl || 0) - totalBrok);
                    const isCF = t.product === 'CF' || activeTab === 'option';
                    const isSettled = t.closed_by === 'EXPIRY_SETTLEMENT' || t.is_expired_settled;

                    return (
                      <tr key={t.trade_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <td style={{ padding: '14px 14px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ fontWeight: 600, color: '#fff', fontSize: '0.9rem' }}>
                              {t.tradingsymbol || t.instrument}
                            </span>
                            {isCF && (
                              <span style={{
                                padding: '1px 6px',
                                borderRadius: '4px',
                                fontSize: '0.7rem',
                                fontWeight: 700,
                                background: 'rgba(167, 139, 250, 0.2)',
                                color: '#c4b5fd',
                                border: '1px solid rgba(167, 139, 250, 0.35)',
                              }}>
                                CF
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: '0.72rem', fontFamily: 'monospace', color: 'var(--text-muted)' }}>{t.trade_id}</div>
                          {isSettled && (
                            <div style={{ fontSize: '0.72rem', color: '#fbbf24', marginTop: '2px' }}>
                              ⚡ Expiry Settled (Underlying: ₹{t.underlying_price_at_settlement ?? '—'}, Settlement: ₹{t.settlement_price ?? t.exit_price ?? '0.00'})
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '14px 14px' }}>
                          <span style={{
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontWeight: 700,
                            fontSize: '0.75rem',
                            background: t.action === 'BUY' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                            color: t.action === 'BUY' ? '#34d399' : '#f87171',
                            marginRight: '6px',
                          }}>
                            {t.action}
                          </span>
                          <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Qty: {t.qty}</span>
                        </td>
                        <td style={{ padding: '14px 14px', color: '#e2e8f0', fontSize: '0.88rem', fontWeight: 600 }}>
                          ₹{Number(t.margin_blocked_amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                        <td style={{ padding: '14px 14px' }}>
                          <div style={{ fontSize: '0.88rem', color: '#fff' }}>Entry: ₹{t.entry_price?.toFixed(2)}</div>
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                            Exit: {t.exit_price ? `₹${t.exit_price?.toFixed(2)}` : '—'}
                          </div>
                        </td>
                        {/* Gross P&L */}
                        <td style={{ padding: '14px 14px' }}>
                          <span style={{
                            fontWeight: 600,
                            fontSize: '0.88rem',
                            color: t.pnl > 0 ? '#10b981' : t.pnl < 0 ? '#ef4444' : 'var(--text-muted)',
                          }}>
                            {t.pnl > 0 ? `+₹${t.pnl.toFixed(2)}` : t.pnl < 0 ? `-₹${Math.abs(t.pnl).toFixed(2)}` : '₹0.00'}
                          </span>
                        </td>
                        {/* Brokerage */}
                        <td style={{ padding: '14px 14px' }}>
                          <div style={{ fontSize: '0.88rem', fontWeight: 600, color: '#c4b5fd' }}>
                            -₹{totalBrok.toFixed(2)}
                          </div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                            In: ₹{(t.entry_brokerage || 0).toFixed(2)} • Out: ₹{(t.exit_brokerage || 0).toFixed(2)}
                          </div>
                        </td>
                        {/* Net P&L */}
                        <td style={{ padding: '14px 14px' }}>
                          <span style={{
                            fontWeight: 700,
                            fontSize: '0.92rem',
                            color: netPnl > 0 ? '#10b981' : netPnl < 0 ? '#ef4444' : 'var(--text-muted)',
                          }}>
                            {netPnl > 0 ? `+₹${netPnl.toFixed(2)}` : netPnl < 0 ? `-₹${Math.abs(netPnl).toFixed(2)}` : '₹0.00'}
                          </span>
                        </td>
                        <td style={{ padding: '14px 14px' }}>
                          <span style={{
                            padding: '3px 8px',
                            borderRadius: '12px',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            background: t.status === 'OPEN'
                              ? 'rgba(59, 130, 246, 0.15)'
                              : isSettled
                              ? 'rgba(245, 158, 11, 0.15)'
                              : 'rgba(255, 255, 255, 0.05)',
                            color: t.status === 'OPEN'
                              ? '#60a5fa'
                              : isSettled
                              ? '#fbbf24'
                              : 'var(--text-muted)',
                          }}>
                            {isSettled ? 'SETTLED' : t.status}
                          </span>
                        </td>
                        <td style={{ padding: '14px 14px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          <div>Entry: {new Date(t.entry_time).toLocaleTimeString()}</div>
                          {t.exit_time && <div>Exit: {new Date(t.exit_time).toLocaleTimeString()}</div>}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Confirmation Modal for Force Close All */}
      {showForceCloseModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px',
        }}>
          <div style={{
            background: 'var(--bg-card)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            borderRadius: '16px',
            padding: '32px',
            maxWidth: '480px',
            width: '100%',
            boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
              <div style={{
                width: '42px',
                height: '42px',
                borderRadius: '10px',
                background: 'rgba(239, 68, 68, 0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#f87171',
              }}>
                <AlertOctagon size={24} />
              </div>
              <div>
                <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>Confirm Force Close</h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Emergency position square-off</p>
              </div>
            </div>

            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: '1.5', marginBottom: '24px' }}>
              Are you sure you want to forcefully square off <strong>all open positions</strong> across Options, Futures, and Cash for trader <strong>{userId}</strong>?
            </p>

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => setShowForceCloseModal(false)}
                disabled={forceClosing}
                style={{
                  padding: '10px 18px',
                  borderRadius: '8px',
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmForceClose}
                disabled={forceClosing}
                style={{
                  padding: '10px 18px',
                  borderRadius: '8px',
                  background: '#ef4444',
                  border: 'none',
                  color: '#fff',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                {forceClosing ? 'Closing Trades...' : 'Yes, Square Off All'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>

      {/* ────────── DELETE USER MODAL ────────── */}
      {showDeleteModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px',
        }}>
          <div style={{
            background: '#1a1f2e', borderRadius: '16px', padding: '32px',
            maxWidth: '460px', width: '100%',
            border: '1.5px solid rgba(239,68,68,0.45)',
            boxShadow: '0 0 60px rgba(239,68,68,0.25)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', background: 'rgba(239,68,68,0.18)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Trash2 size={20} color="#f87171" />
              </div>
              <div>
                <h3 style={{ margin: 0, color: '#f87171', fontSize: '1.15rem', fontWeight: 700 }}>Delete Trader Account</h3>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.82rem' }}>This action is permanent and cannot be undone.</p>
              </div>
            </div>

            <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '10px', padding: '14px', marginBottom: '20px' }}>
              <p style={{ margin: '0 0 6px 0', color: '#fca5a5', fontWeight: 600, fontSize: '0.88rem' }}>⚠ This will permanently delete:</p>
              <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.8 }}>
                <li>User account: <strong style={{ color: '#fff' }}>{userId}</strong></li>
                <li>All option, future & cash trade history</li>
                <li>All balance & P&L records</li>
              </ul>
            </div>

            <label style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '8px' }}>
              Type <strong style={{ color: '#f87171' }}>{userId}</strong> to confirm:
            </label>
            <input
              value={deleteConfirmText}
              onChange={e => setDeleteConfirmText(e.target.value)}
              placeholder={userId}
              style={{
                width: '100%', boxSizing: 'border-box', padding: '10px 14px', borderRadius: '8px',
                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(239,68,68,0.35)',
                color: '#fff', fontSize: '0.95rem', outline: 'none', marginBottom: '20px',
              }}
            />

            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                onClick={() => setShowDeleteModal(false)}
                style={{ flex: 1, padding: '11px', borderRadius: '10px', background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', fontWeight: 600, cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteUser}
                disabled={deleteConfirmText !== userId || deleting}
                style={{
                  flex: 1, padding: '11px', borderRadius: '10px', fontWeight: 700, cursor: 'pointer',
                  background: deleteConfirmText === userId ? '#dc2626' : 'rgba(239,68,68,0.2)',
                  border: '1px solid rgba(239,68,68,0.5)', color: '#fff',
                  opacity: deleteConfirmText === userId ? 1 : 0.5,
                  transition: 'all 0.2s',
                }}
              >
                {deleting ? 'Deleting...' : '🗑 Delete Forever'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ────────── RESET ACCOUNT MODAL ────────── */}
      {showResetModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px',
        }}>
          <div style={{
            background: '#1a1f2e', borderRadius: '16px', padding: '32px',
            maxWidth: '480px', width: '100%',
            border: '1.5px solid rgba(245,158,11,0.4)',
            boxShadow: '0 0 60px rgba(245,158,11,0.2)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', background: 'rgba(245,158,11,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <RefreshCcw size={20} color="#fbbf24" />
              </div>
              <div>
                <h3 style={{ margin: 0, color: '#fbbf24', fontSize: '1.15rem', fontWeight: 700 }}>Reset Trader Account</h3>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.82rem' }}>Wipe all trades and restore to a clean slate.</p>
              </div>
            </div>

            <div style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)', borderRadius: '10px', padding: '14px', marginBottom: '20px' }}>
              <p style={{ margin: '0 0 6px 0', color: '#fde68a', fontWeight: 600, fontSize: '0.88rem' }}>This will:</p>
              <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.8 }}>
                <li>Delete <strong style={{ color: '#fff' }}>ALL</strong> option, future & cash trades</li>
                <li>Reset balance, P&L, margin to zero</li>
                <li>Restore starting capital to the amount below</li>
                <li>Keep the user account & login credentials</li>
              </ul>
            </div>

            <label style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '6px' }}>
              New Starting Balance (₹)
            </label>
            <input
              type="number"
              value={resetBalance}
              onChange={e => setResetBalance(e.target.value)}
              min="0"
              style={{
                width: '100%', boxSizing: 'border-box', padding: '10px 14px', borderRadius: '8px',
                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(245,158,11,0.3)',
                color: '#fff', fontSize: '0.95rem', outline: 'none', marginBottom: '16px',
              }}
            />

            <label style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '8px' }}>
              Type <strong style={{ color: '#fbbf24' }}>RESET</strong> to confirm:
            </label>
            <input
              value={resetConfirmText}
              onChange={e => setResetConfirmText(e.target.value)}
              placeholder="RESET"
              style={{
                width: '100%', boxSizing: 'border-box', padding: '10px 14px', borderRadius: '8px',
                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(245,158,11,0.3)',
                color: '#fff', fontSize: '0.95rem', outline: 'none', marginBottom: '20px',
              }}
            />

            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                onClick={() => setShowResetModal(false)}
                style={{ flex: 1, padding: '11px', borderRadius: '10px', background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', fontWeight: 600, cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleResetAccount}
                disabled={resetConfirmText !== 'RESET' || resetting}
                style={{
                  flex: 1, padding: '11px', borderRadius: '10px', fontWeight: 700, cursor: 'pointer',
                  background: resetConfirmText === 'RESET' ? '#d97706' : 'rgba(245,158,11,0.15)',
                  border: '1px solid rgba(245,158,11,0.4)', color: '#fff',
                  opacity: resetConfirmText === 'RESET' ? 1 : 0.5,
                  transition: 'all 0.2s',
                }}
              >
                {resetting ? 'Resetting...' : '🔄 Reset Account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default UserDetail;

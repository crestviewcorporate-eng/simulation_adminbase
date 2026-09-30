import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api/api';
import { UserPlus, User, Lock, Layers, ArrowLeft, CheckCircle2, AlertCircle, ShieldCheck } from 'lucide-react';

const CreateUser = () => {
  const [userId, setUserId] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('VTrade@2026');
  const [allowedSegments, setAllowedSegments] = useState(['option', 'future', 'cash']);
  const [allowedInstrumentTypes, setAllowedInstrumentTypes] = useState(['INDEX']);
  const [limits, setLimits] = useState({
    option: 10,
    future: 5,
    cash: 50000,
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const navigate = useNavigate();

  const handleSegmentToggle = (seg) => {
    if (allowedSegments.includes(seg)) {
      setAllowedSegments(allowedSegments.filter((s) => s !== seg));
    } else {
      setAllowedSegments([...allowedSegments, seg]);
    }
  };

  const handleInstrumentTypeToggle = (type) => {
    if (allowedInstrumentTypes.includes(type)) {
      if (allowedInstrumentTypes.length === 1) return;
      setAllowedInstrumentTypes(allowedInstrumentTypes.filter((t) => t !== type));
    }
  };

  const handleLimitChange = (seg, value) => {
    setLimits({
      ...limits,
      [seg]: Math.max(0, parseInt(value, 10) || 0),
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (allowedSegments.length === 0) {
      setError('Please select at least one allowed trading segment.');
      return;
    }

    setLoading(true);

    try {
      const payload = {
        user_id: userId.trim(),
        name: name.trim(),
        password: password,
        allowed_segments: allowedSegments,
        allowed_instrument_types: allowedInstrumentTypes,
        trade_limit: limits,
      };

      const res = await api.post('/admin/users', payload);
      if (res.status === 201 || res.data?.user_id) {
        setSuccess(`User '${userId}' created successfully! Redirecting to user list...`);
        setTimeout(() => {
          navigate('/admin/users');
        }, 1200);
      }
    } catch (err) {
      if (!err.response) {
        setError('Cannot connect to server. Please verify backend is running.');
      } else if (err.response.status === 409) {
        setError(`User ID '${userId}' already exists. Please choose a different User ID.`);
      } else if (err.response.data?.detail) {
        const detail = err.response.data.detail;
        setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      } else {
        setError('Failed to create user account. Please check inputs.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '32px', maxWidth: '800px', width: '100%', margin: '0 auto' }}>
      {/* Back Button */}
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
          marginBottom: '20px',
        }}
      >
        <ArrowLeft size={16} />
        <span>Back to Trader Accounts</span>
      </button>

      {/* Header */}
      <div style={{ marginBottom: '28px' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff', letterSpacing: '-0.5px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <UserPlus size={26} color="#3b82f6" />
          <span>Provision New Trader Account</span>
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '4px' }}>
          Create a simulation account, assign trading permissions, and configure atomic limits.
        </p>
      </div>

      {/* Error & Success Messages */}
      {error && (
        <div className="alert-error" style={{ marginBottom: '20px' }}>
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      {success && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '12px 14px',
          background: 'rgba(16, 185, 129, 0.12)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          borderRadius: '10px',
          color: '#6ee7b7',
          fontSize: '0.88rem',
          marginBottom: '20px',
        }}>
          <CheckCircle2 size={18} />
          <span>{success}</span>
        </div>
      )}

      {/* Form Card */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '32px',
        boxShadow: '0 10px 40px rgba(0, 0, 0, 0.3)',
      }}>
        <form onSubmit={handleSubmit}>
          {/* Identity Section */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '20px', marginBottom: '24px' }}>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">User ID (Unique identifier)</label>
              <div className="input-wrapper">
                <User size={18} className="input-icon" />
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. trader_01"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  required
                  autoFocus
                />
              </div>
            </div>

            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">Full Name</label>
              <div className="input-wrapper">
                <ShieldCheck size={18} className="input-icon" />
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. John Doe"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>
            </div>
          </div>

          <div className="form-group" style={{ marginBottom: '28px' }}>
            <label className="form-label">Initial Temporary Password</label>
            <div className="input-wrapper">
              <Lock size={18} className="input-icon" />
              <input
                type="text"
                className="form-input"
                placeholder="Temporary password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '6px', display: 'block' }}>
              The user will be required to change this temporary password upon their first login.
            </span>
          </div>

          {/* Allowed Segments Section */}
          <div style={{
            padding: '20px',
            background: 'var(--bg-input)',
            borderRadius: '12px',
            border: '1px solid var(--border-color)',
            marginBottom: '24px',
          }}>
            <label className="form-label" style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Layers size={16} color="#60a5fa" />
              <span>Permitted Trading Segments</span>
            </label>
            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
              {[
                { id: 'option', label: 'Options (NIFTY, BANKNIFTY, SENSEX)' },
                { id: 'future', label: 'Futures (Index Derivatives)' },
                { id: 'cash', label: 'Cash (Equities)' },
              ].map(({ id, label }) => (
                <label
                  key={id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    background: allowedSegments.includes(id) ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                    border: allowedSegments.includes(id) ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid var(--border-color)',
                    cursor: 'pointer',
                    fontSize: '0.88rem',
                    color: allowedSegments.includes(id) ? '#fff' : 'var(--text-secondary)',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={allowedSegments.includes(id)}
                    onChange={() => handleSegmentToggle(id)}
                    style={{ accentColor: '#3b82f6', width: '16px', height: '16px' }}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Permitted Instrument Types Section (INDEX / MCX) */}
          <div style={{
            padding: '20px',
            background: 'var(--bg-input)',
            borderRadius: '12px',
            border: '1px solid var(--border-color)',
            marginBottom: '24px',
          }}>
            <label className="form-label" style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Layers size={16} color="#f59e0b" />
              <span>Permitted Instrument Types</span>
            </label>
            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
              {[
                { id: 'INDEX', label: 'Index Instruments (NIFTY, BANKNIFTY, SENSEX, etc.)' },
                { id: 'MCX', label: 'MCX Commodities (GOLD, CRUDEOIL, SILVER, etc.)' },
              ].map(({ id, label }) => (
                <label
                  key={id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    background: allowedInstrumentTypes.includes(id) ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                    border: allowedInstrumentTypes.includes(id) ? '1px solid rgba(245, 158, 11, 0.4)' : '1px solid var(--border-color)',
                    cursor: 'pointer',
                    fontSize: '0.88rem',
                    color: allowedInstrumentTypes.includes(id) ? '#fff' : 'var(--text-secondary)',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={allowedInstrumentTypes.includes(id)}
                    onChange={() => handleInstrumentTypeToggle(id)}
                    style={{ accentColor: '#f59e0b', width: '16px', height: '16px' }}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Trade Limits Section */}
          <div style={{
            padding: '20px',
            background: 'var(--bg-input)',
            borderRadius: '12px',
            border: '1px solid var(--border-color)',
            marginBottom: '28px',
          }}>
            <label className="form-label" style={{ marginBottom: '14px' }}>Segment Trade Quotas (Max Executable Trades)</label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Options Limit</label>
                <input
                  type="number"
                  min="0"
                  className="form-input"
                  value={limits.option}
                  onChange={(e) => handleLimitChange('option', e.target.value)}
                  disabled={!allowedSegments.includes('option')}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Futures Limit</label>
                <input
                  type="number"
                  min="0"
                  className="form-input"
                  value={limits.future}
                  onChange={(e) => handleLimitChange('future', e.target.value)}
                  disabled={!allowedSegments.includes('future')}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Cash Limit</label>
                <input
                  type="number"
                  min="0"
                  className="form-input"
                  value={limits.cash}
                  onChange={(e) => handleLimitChange('cash', e.target.value)}
                  disabled={!allowedSegments.includes('cash')}
                />
              </div>
            </div>
          </div>

          {/* Submit */}
          <button type="submit" className="submit-btn" disabled={loading || !!success}>
            {loading ? (
              <div className="spinner" />
            ) : (
              <>
                <UserPlus size={18} />
                <span>Create Trader Account</span>
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
};

export default CreateUser;

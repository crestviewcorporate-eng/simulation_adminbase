import React, { useEffect, useState, useRef } from 'react';
import api from '../../api/api';
import { 
  TrendingUp, 
  RefreshCw, 
  AlertTriangle, 
  Check, 
  Save, 
  Layers, 
  DollarSign, 
  Clock,
  Sparkles
} from 'lucide-react';

const FutureInstrumentMargins = () => {
  const [instruments, setInstruments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editValues, setEditValues] = useState({});
  const [savingRows, setSavingRows] = useState({});
  const [saveSuccess, setSaveSuccess] = useState({});

  const [activeTab, setActiveTab] = useState('ALL'); // 'ALL' | 'INDEX' | 'MCX'
  const pollIntervalRef = useRef(null);

  const fetchFutureList = async (isManual = false) => {
    if (isManual) setLoading(true);
    try {
      const res = await api.get('/admin/instruments/future-list');
      const data = res.data || [];
      setInstruments(data);
      
      // Initialize edit values for any unset input
      setEditValues((prev) => {
        const next = { ...prev };
        data.forEach((inst) => {
          if (next[inst.symbol] === undefined) {
            next[inst.symbol] = inst.margin_required !== null && inst.margin_required !== undefined
              ? String(inst.margin_required)
              : '';
          }
        });
        return next;
      });
      setError('');
    } catch (err) {
      console.error('Error fetching future instruments:', err);
      if (isManual) {
        setError(err.response?.data?.detail || 'Failed to fetch future instruments');
      }
    } finally {
      if (isManual) setLoading(false);
    }
  };

  useEffect(() => {
    fetchFutureList(true);

    // 5-second polling cycle
    pollIntervalRef.current = setInterval(() => {
      fetchFutureList(false);
    }, 5000);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const handleInputChange = (symbol, value) => {
    setEditValues((prev) => ({
      ...prev,
      [symbol]: value,
    }));
  };

  const handleSaveMargin = async (symbol) => {
    const val = editValues[symbol];
    if (val === undefined || val === '' || isNaN(val) || Number(val) < 0) {
      alert('Please enter a valid non-negative margin amount.');
      return;
    }

    const marginValue = parseFloat(val);
    setSavingRows((prev) => ({ ...prev, [symbol]: true }));

    try {
      await api.put(`/admin/instruments/${symbol}/future/margin`, {
        margin_required: marginValue,
      });

      setSaveSuccess((prev) => ({ ...prev, [symbol]: true }));
      setTimeout(() => {
        setSaveSuccess((prev) => ({ ...prev, [symbol]: false }));
      }, 3000);

      // Refresh list immediately
      await fetchFutureList(false);
    } catch (err) {
      alert(err.response?.data?.detail || `Failed to save margin for ${symbol}`);
    } finally {
      setSavingRows((prev) => ({ ...prev, [symbol]: false }));
    }
  };

  const filteredInstruments = instruments.filter((inst) => {
    if (activeTab === 'INDEX') return (inst.instrument_type || 'INDEX') === 'INDEX';
    if (activeTab === 'MCX') return (inst.instrument_type || 'INDEX') === 'MCX';
    return true;
  });

  return (
    <div style={{ padding: '32px', maxWidth: '1400px', width: '100%', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff', letterSpacing: '-0.5px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <TrendingUp size={26} color="#3b82f6" />
            <span>Future Instruments & Margin Control</span>
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '4px' }}>
            Configure exact margin lock requirements per lot for active derivative futures (Index & MCX Commodity). Polled live every 5s.
          </p>
        </div>

        <button
          onClick={() => fetchFutureList(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '10px 16px',
            borderRadius: '10px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            fontSize: '0.85rem',
            fontWeight: 500,
          }}
        >
          <RefreshCw size={15} />
          <span>Refresh Prices</span>
        </button>
      </div>

      {/* Tabs Filter */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {[
          { key: 'ALL', label: `All Futures (${instruments.length})` },
          { key: 'INDEX', label: `Index Futures (${instruments.filter(i => i.instrument_type !== 'MCX').length})` },
          { key: 'MCX', label: `MCX Commodities (${instruments.filter(i => i.instrument_type === 'MCX').length})` },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              fontSize: '0.85rem',
              fontWeight: 600,
              cursor: 'pointer',
              border: activeTab === tab.key ? '1px solid #3b82f6' : '1px solid var(--border-color)',
              background: activeTab === tab.key ? 'rgba(59, 130, 246, 0.2)' : 'var(--bg-card)',
              color: activeTab === tab.key ? '#60a5fa' : 'var(--text-secondary)',
              transition: 'all 0.15s',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="alert-error" style={{ marginBottom: '20px' }}>
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Instruments Table */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        overflow: 'hidden',
        boxShadow: '0 8px 30px rgba(0, 0, 0, 0.3)',
      }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', minWidth: '950px' }}>
            <thead>
              <tr style={{ background: 'rgba(255, 255, 255, 0.02)', borderBottom: '1px solid var(--border-color)' }}>
                <th style={{ padding: '14px 20px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Symbol / Contract</th>
                <th style={{ padding: '14px 20px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Segment</th>
                <th style={{ padding: '14px 20px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Live LTP</th>
                <th style={{ padding: '14px 20px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Lot Spec & Multiplier</th>
                <th style={{ padding: '14px 20px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Current Margin Required</th>
                <th style={{ padding: '14px 20px', fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, textAlign: 'right' }}>Set Margin per Lot</th>
              </tr>
            </thead>
            <tbody>
              {loading && filteredInstruments.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    <div className="spinner" style={{ margin: '0 auto 12px auto' }} />
                    <span>Loading future contracts and market prices...</span>
                  </td>
                </tr>
              ) : filteredInstruments.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    <Layers size={32} style={{ margin: '0 auto 8px auto', opacity: 0.4 }} />
                    <p>No future instruments found in this category.</p>
                  </td>
                </tr>
              ) : (
                filteredInstruments.map((inst) => {
                  const isConfigured = inst.margin_required !== null && inst.margin_required !== undefined;
                  const isSaving = savingRows[inst.symbol] || false;
                  const isSuccess = saveSuccess[inst.symbol] || false;
                  const isMcx = inst.instrument_type === 'MCX';

                  return (
                    <tr
                      key={inst.symbol}
                      style={{
                        borderBottom: '1px solid var(--border-color)',
                        background: !isConfigured ? 'rgba(245, 158, 11, 0.05)' : 'transparent',
                        transition: 'background 0.15s',
                      }}
                    >
                      {/* Symbol & Contract */}
                      <td style={{ padding: '16px 20px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            width: '38px',
                            height: '38px',
                            borderRadius: '10px',
                            background: !isConfigured ? 'rgba(245, 158, 11, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: !isConfigured ? '#fbbf24' : '#60a5fa',
                            fontWeight: 700,
                            fontSize: '0.9rem',
                          }}>
                            {inst.symbol.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <div style={{ fontWeight: 700, color: '#fff', fontSize: '0.95rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span>{inst.symbol}</span>
                              {!isConfigured && (
                                <span style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '3px',
                                  padding: '2px 7px',
                                  borderRadius: '6px',
                                  background: 'rgba(245, 158, 11, 0.2)',
                                  color: '#fbbf24',
                                  fontSize: '0.72rem',
                                  fontWeight: 600,
                                  border: '1px solid rgba(245, 158, 11, 0.35)',
                                }}>
                                  <AlertTriangle size={11} /> Config Required
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                              {inst.tradingsymbol || `${inst.symbol} FUT`}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Exchange / Segment */}
                      <td style={{ padding: '16px 20px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <span style={{
                            display: 'inline-block',
                            padding: '3px 8px',
                            borderRadius: '6px',
                            fontSize: '0.78rem',
                            fontWeight: 700,
                            background: isMcx ? 'rgba(234, 88, 12, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                            color: isMcx ? '#fb923c' : '#60a5fa',
                            border: isMcx ? '1px solid rgba(234, 88, 12, 0.3)' : '1px solid rgba(59, 130, 246, 0.3)',
                            width: 'fit-content',
                          }}>
                            {inst.exchange} • {inst.instrument_type || 'INDEX'}
                          </span>
                          {!inst.enabled && isMcx && (
                            <span style={{ fontSize: '0.72rem', color: '#f87171' }}>Spec unverified</span>
                          )}
                        </div>
                      </td>

                      {/* Live LTP */}
                      <td style={{ padding: '16px 20px' }}>
                        <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', fontFamily: 'monospace' }}>
                          ₹{inst.ltp ? inst.ltp.toFixed(2) : '0.00'}
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                          <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#10b981' }} />
                          Live Quote ({inst.quote_unit || '₹/unit'})
                        </div>
                      </td>

                      {/* Lot Spec & Multiplier */}
                      <td style={{ padding: '16px 20px' }}>
                        <div style={{ color: '#e2e8f0', fontSize: '0.9rem', fontWeight: 600 }}>
                          {inst.lot_size} units / lot
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                          P&L Multiplier: <strong style={{ color: '#38bdf8' }}>{inst.multiplier !== null && inst.multiplier !== undefined ? `× ${inst.multiplier}` : 'Not Set'}</strong>
                        </div>
                      </td>

                      {/* Current Margin Required */}
                      <td style={{ padding: '16px 20px' }}>
                        {isConfigured ? (
                          <div>
                            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#60a5fa' }}>
                              ₹{inst.margin_required.toLocaleString('en-IN')}
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                              per lot locked
                            </div>
                          </div>
                        ) : (
                          <span style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '3px 8px',
                            borderRadius: '6px',
                            fontSize: '0.78rem',
                            fontWeight: 600,
                            background: 'rgba(239, 68, 68, 0.15)',
                            color: '#f87171',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                          }}>
                            Not Set (Default ₹100,000)
                          </span>
                        )}
                      </td>

                      {/* Inline Editable Save Action */}
                      <td style={{ padding: '16px 20px', textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                          <div style={{ position: 'relative' }}>
                            <span style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                              ₹
                            </span>
                            <input
                              type="number"
                              min="0"
                              step="any"
                              placeholder="e.g. 50000"
                              value={editValues[inst.symbol] ?? ''}
                              onChange={(e) => handleInputChange(inst.symbol, e.target.value)}
                              style={{
                                width: '130px',
                                padding: '8px 10px 8px 24px',
                                background: 'var(--bg-input)',
                                border: !isConfigured ? '1px solid rgba(245, 158, 11, 0.4)' : '1px solid var(--border-color)',
                                borderRadius: '8px',
                                color: '#fff',
                                fontSize: '0.88rem',
                                outline: 'none',
                              }}
                            />
                          </div>

                          <button
                            onClick={() => handleSaveMargin(inst.symbol)}
                            disabled={isSaving}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '5px',
                              padding: '8px 14px',
                              borderRadius: '8px',
                              background: isSuccess ? '#10b981' : '#2563eb',
                              border: 'none',
                              color: '#fff',
                              fontSize: '0.85rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                              transition: 'all 0.2s',
                            }}
                          >
                            {isSaving ? (
                              <span>Saving...</span>
                            ) : isSuccess ? (
                              <>
                                <Check size={14} />
                                <span>Saved!</span>
                              </>
                            ) : (
                              <>
                                <Save size={14} />
                                <span>Save</span>
                              </>
                            )}
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
  );
};

export default FutureInstrumentMargins;

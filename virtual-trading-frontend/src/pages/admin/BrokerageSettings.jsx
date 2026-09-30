import React, { useState, useEffect } from 'react';
import {
  Coins,
  Percent,
  CheckCircle,
  AlertCircle,
  Save,
  HelpCircle,
  TrendingUp,
  Layers,
  Calendar,
  Filter,
} from 'lucide-react';
import api from '../../api/api';

const DEFAULT_ROWS = [
  {
    segment: 'option',
    instrument_type: 'INDEX',
    label: 'Index Options (NSE/BSE)',
    mode: 'PER_LOT',
    value: 20,
    enabled: true,
  },
  {
    segment: 'future',
    instrument_type: 'INDEX',
    label: 'Index Futures (NSE/BSE)',
    mode: 'PER_LOT',
    value: 50,
    enabled: true,
  },
  {
    segment: 'future',
    instrument_type: 'MCX',
    label: 'MCX Commodity Futures',
    mode: 'PER_LOT',
    value: 100,
    enabled: true,
  },
  {
    segment: 'cash',
    instrument_type: 'INDEX',
    label: 'Cash Equities (Index)',
    mode: 'PERCENT',
    value: 0.05,
    enabled: true,
  },
];

const BrokerageSettings = () => {
  const [rows, setRows] = useState(DEFAULT_ROWS);
  const [loading, setLoading] = useState(false);
  const [savingIndex, setSavingIndex] = useState(null);
  const [statusMsg, setStatusMsg] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  // Summary Metrics
  const [summary, setSummary] = useState(null);

  // Fetch Global Brokerage Configs & Summary
  const fetchData = async () => {
    setLoading(true);
    try {
      const [cfgRes, sumRes] = await Promise.all([
        api.get('/admin/brokerage'),
        api.get('/admin/brokerage/summary'),
      ]);

      const globalRows = cfgRes.data.configs || [];
      setSummary(sumRes.data);

      // Merge with default rows
      setRows((prev) =>
        prev.map((r) => {
          const match = globalRows.find(
            (g) => g.segment === r.segment && g.instrument_type === r.instrument_type
          );
          if (match) {
            return {
              ...r,
              mode: match.mode,
              value: match.value,
              enabled: match.enabled !== false,
            };
          }
          return r;
        })
      );
    } catch (err) {
      console.debug('Failed to load brokerage configs:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleRowChange = (index, field, val) => {
    setRows((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: val };
      return next;
    });
  };

  const handleSaveRow = async (index) => {
    const row = rows[index];
    setSavingIndex(index);
    setStatusMsg(null);
    setErrorMsg(null);

    try {
      await api.put('/admin/brokerage', {
        scope: 'global',
        segment: row.segment,
        instrument_type: row.instrument_type,
        mode: row.mode,
        value: parseFloat(row.value) || 0,
        enabled: Boolean(row.enabled),
      });
      setStatusMsg(`Saved global brokerage for ${row.label}`);
      await fetchData();
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'Failed to save brokerage config.');
    } finally {
      setSavingIndex(null);
    }
  };

  // Generate a worked example text based on segment & current mode/value
  const getWorkedExample = (row) => {
    const val = parseFloat(row.value) || 0;
    if (row.segment === 'option') {
      if (row.mode === 'PER_LOT') {
        return `Example: Buying or selling 2 lots charges ₹${(val * 2).toFixed(2)} entry (₹${val}/lot × 2) + ₹${(val * 2).toFixed(2)} exit.`;
      } else {
        const samplePrem = 100;
        const sampleQty = 65; // NIFTY lot
        const calc = ((val / 100) * samplePrem * sampleQty).toFixed(2);
        return `Example: Premium ₹100 × 65 qty @ ${val}% charges ₹${calc} per order (entry and exit each).`;
      }
    } else if (row.segment === 'future' && row.instrument_type === 'INDEX') {
      if (row.mode === 'PER_LOT') {
        return `Example: Trading 2 lots of NIFTY future charges ₹${(val * 2).toFixed(2)} (₹${val}/lot × 2) per executed order.`;
      } else {
        const sampleValue = 24500 * 65;
        const calc = ((val / 100) * sampleValue).toFixed(2);
        return `Example: Full contract value ₹${sampleValue.toLocaleString()} @ ${val}% = ₹${calc} brokerage per leg.`;
      }
    } else if (row.segment === 'future' && row.instrument_type === 'MCX') {
      if (row.mode === 'PER_LOT') {
        return `Example: 1 lot GOLD future charges ₹${val.toFixed(2)} entry + ₹${val.toFixed(2)} exit.`;
      } else {
        const sampleValue = 75000 * 100; // 1 lot GOLD = ₹75,00,000 contract value
        const calc = ((val / 100) * sampleValue).toFixed(2);
        return `Example: 1 lot GOLD (₹75L contract) @ ${val}% charges ₹${calc} on entry and exit.`;
      }
    } else {
      // Cash
      if (row.mode === 'PER_LOT') {
        return `Example: Fixed charge of ₹${val.toFixed(2)} per cash equity execution.`;
      } else {
        const sampleVal = 50000;
        const calc = ((val / 100) * sampleVal).toFixed(2);
        return `Example: ₹${sampleVal.toLocaleString()} equity purchase @ ${val}% charges ₹${calc} brokerage.`;
      }
    }
  };

  return (
    <div style={{ padding: '28px', maxWidth: '1280px', margin: '0 auto' }}>
      {/* Page Header */}
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
        <div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: '#fff', margin: 0, letterSpacing: '-0.02em' }}>
            Brokerage Settings
          </h1>
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
            Admin-managed global rate schedules and collection overview (applied to entries, exits, auto square-off and settlement)
          </span>
        </div>

        {summary && (
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '10px',
              padding: '10px 16px',
            }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Brokerage Today
              </div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#10b981' }}>
                ₹{Number(summary.total_brokerage_today || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </div>
            </div>

            <div style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '10px',
              padding: '10px 16px',
            }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Total Collected
              </div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#60a5fa' }}>
                ₹{Number(summary.total_brokerage_collected || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Notifications */}
      {statusMsg && (
        <div style={{
          padding: '12px 16px',
          borderRadius: '10px',
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          color: '#34d399',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '20px',
        }}>
          <CheckCircle size={16} />
          <span>{statusMsg}</span>
        </div>
      )}

      {errorMsg && (
        <div style={{
          padding: '12px 16px',
          borderRadius: '10px',
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          color: '#f87171',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '20px',
        }}>
          <AlertCircle size={16} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Global Matrix Card */}
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '24px',
        marginBottom: '28px',
      }}>
        <div style={{ marginBottom: '16px' }}>
          <h2 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', margin: 0 }}>
            Global Tier Schedule (Option, Future, Cash × Index/MCX)
          </h2>
          <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
            Resolution hierarchy: User Override &gt; Global Segment+Type &gt; Global Segment &gt; ₹0.00
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {rows.map((row, idx) => {
            const isSaving = savingIndex === idx;

            return (
              <div
                key={`${row.segment}-${row.instrument_type}`}
                style={{
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '12px',
                  padding: '18px 20px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                  {/* Title & Segment Tag */}
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong style={{ color: '#fff', fontSize: '0.95rem' }}>{row.label}</strong>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        background: 'rgba(59, 130, 246, 0.2)',
                        color: '#60a5fa',
                      }}>
                        {row.segment.toUpperCase()}
                      </span>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        background: row.instrument_type === 'MCX' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                        color: row.instrument_type === 'MCX' ? '#fbbf24' : '#34d399',
                      }}>
                        {row.instrument_type}
                      </span>
                    </div>
                  </div>

                  {/* Mode Selector, Value Input, Enabled, and Save Button */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                    {/* Mode */}
                    <select
                      value={row.mode}
                      onChange={(e) => handleRowChange(idx, 'mode', e.target.value)}
                      style={{
                        padding: '8px 12px',
                        borderRadius: '8px',
                        background: 'var(--bg-card)',
                        border: '1px solid var(--border-color)',
                        color: '#fff',
                        fontSize: '0.85rem',
                        fontWeight: 600,
                      }}
                    >
                      <option value="PER_LOT">Per Lot (₹)</option>
                      <option value="PERCENT">% of Trade Value</option>
                    </select>

                    {/* Value */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <input
                        type="number"
                        step={row.mode === 'PERCENT' ? '0.001' : '1'}
                        min="0"
                        value={row.value}
                        onChange={(e) => handleRowChange(idx, 'value', e.target.value)}
                        style={{
                          width: '100px',
                          padding: '8px 10px',
                          borderRadius: '8px',
                          background: 'var(--bg-card)',
                          border: '1px solid var(--border-color)',
                          color: '#fff',
                          fontSize: '0.9rem',
                          fontWeight: 700,
                          textAlign: 'right',
                        }}
                      />
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem', fontWeight: 600 }}>
                        {row.mode === 'PER_LOT' ? '₹' : '%'}
                      </span>
                    </div>

                    {/* Enabled Toggle */}
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={row.enabled}
                        onChange={(e) => handleRowChange(idx, 'enabled', e.target.checked)}
                        style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                      />
                      <span>Active</span>
                    </label>

                    {/* Save Button */}
                    <button
                      type="button"
                      onClick={() => handleSaveRow(idx)}
                      disabled={isSaving}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 16px',
                        borderRadius: '8px',
                        background: '#3b82f6',
                        border: 'none',
                        color: '#fff',
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        cursor: isSaving ? 'not-allowed' : 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      {isSaving ? (
                        <div className="spinner" style={{ width: '14px', height: '14px' }} />
                      ) : (
                        <Save size={14} />
                      )}
                      <span>Save</span>
                    </button>
                  </div>
                </div>

                {/* Worked Example */}
                <div style={{
                  padding: '8px 12px',
                  borderRadius: '6px',
                  background: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  fontSize: '0.78rem',
                  color: '#94a3b8',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}>
                  <HelpCircle size={13} color="#60a5fa" style={{ flexShrink: 0 }} />
                  <span>{getWorkedExample(row)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Segment Aggregation Breakdown */}
      {summary && (
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '16px',
          padding: '24px',
        }}>
          <h2 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', marginBottom: '14px' }}>
            Brokerage Collected by Segment
          </h2>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
            {['option', 'future', 'cash'].map((seg) => {
              const segTotal = summary.by_segment?.[seg] || 0;
              return (
                <div
                  key={seg}
                  style={{
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '10px',
                    padding: '16px',
                  }}
                >
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                    {seg} Segment Total
                  </div>
                  <div style={{ fontSize: '1.3rem', fontWeight: 700, color: '#fff' }}>
                    ₹{Number(segTotal).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default BrokerageSettings;

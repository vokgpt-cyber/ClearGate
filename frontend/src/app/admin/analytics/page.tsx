'use client';

import { useState, useEffect, useCallback } from 'react';
import { useLocale } from '@/hooks/useLocale';
import { getAnalytics, type AnalyticsSummary } from '@/lib/api';

export default function AnalyticsPage() {
  const { t } = useLocale();
  const [range, setRange] = useState('30');
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAnalytics = useCallback(async () => {
    const now = new Date();
    const from = new Date(now);

    switch (range) {
      case '7':
        from.setDate(from.getDate() - 7);
        break;
      case '30':
        from.setDate(from.getDate() - 30);
        break;
      case '90':
        from.setDate(from.getDate() - 90);
        break;
    }

    const fromStr = from.toISOString().split('T')[0];
    const toStr = now.toISOString().split('T')[0];

    try {
      setLoading(true);
      const analytics = await getAnalytics(fromStr, toStr);
      setData(analytics);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  return (
    <div className="cleargate-admin-content">
      <div className="cleargate-admin-header">
        <h1>{t('admin.analytics.title')}</h1>
        <select
          value={range}
          onChange={(e) => setRange(e.target.value)}
          className="cleargate-admin-select"
        >
          <option value="7">{t('admin.analytics.range7')}</option>
          <option value="30">{t('admin.analytics.range30')}</option>
          <option value="90">{t('admin.analytics.range90')}</option>
        </select>
      </div>

      {error && <div className="cleargate-admin-error">{error}</div>}

      {loading ? (
        <div className="cleargate-admin-loading">{t('auth.checking')}</div>
      ) : data ? (
        <div className="cleargate-admin-dashboard">
          <div className="cleargate-admin-stat-card">
            <h3>{t('admin.analytics.totalSessions')}</h3>
            <div className="cleargate-admin-stat-value">{data.total_sessions}</div>
          </div>

          <div className="cleargate-admin-stat-card">
            <h3>{t('admin.analytics.latency')}</h3>
            <div className="cleargate-admin-stat-group">
              <div>
                <span>{t('admin.analytics.p50')}:</span>
                <span className="cleargate-admin-stat-value">{data.anonymize_latency.p50_ms}ms</span>
              </div>
              <div>
                <span>{t('admin.analytics.p95')}:</span>
                <span className="cleargate-admin-stat-value">{data.anonymize_latency.p95_ms}ms</span>
              </div>
              <div>
                <span>{t('admin.analytics.p99')}:</span>
                <span className="cleargate-admin-stat-value">{data.anonymize_latency.p99_ms}ms</span>
              </div>
            </div>
          </div>

          <div className="cleargate-admin-stat-card">
            <h3>{t('admin.analytics.errorRate')}</h3>
            <div className="cleargate-admin-stat-value">{data.error_rate_percent.toFixed(2)}%</div>
          </div>

          <div className="cleargate-admin-card cleargate-admin-card--wide">
            <h3>{t('admin.analytics.topEntities')}</h3>
            <div className="cleargate-admin-chart">
              {data.top_entity_types.map((type) => (
                <div key={type.type} className="cleargate-admin-chart__bar">
                  <span className="cleargate-admin-chart__label">{type.type}</span>
                  <div className="cleargate-admin-chart__bar-container">
                    <div
                      className="cleargate-admin-chart__bar-fill"
                      style={{
                        width: `${(type.count / Math.max(...data.top_entity_types.map((t) => t.count))) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="cleargate-admin-chart__value">{type.count}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="cleargate-admin-card cleargate-admin-card--wide">
            <h3>{t('admin.analytics.sessionsPerDay')}</h3>
            <div className="cleargate-admin-chart">
              {data.sessions_per_day.map((day) => (
                <div key={day.date} className="cleargate-admin-chart__bar">
                  <span className="cleargate-admin-chart__label">{day.date}</span>
                  <div className="cleargate-admin-chart__bar-container">
                    <div
                      className="cleargate-admin-chart__bar-fill"
                      style={{
                        width: `${(day.count / Math.max(...data.sessions_per_day.map((d) => d.count))) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="cleargate-admin-chart__value">{day.count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

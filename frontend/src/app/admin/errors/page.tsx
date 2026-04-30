'use client';

import { useState, useEffect, useCallback } from 'react';
import { useLocale } from '@/hooks/useLocale';
import { getErrors, type AdminError } from '@/lib/api';

export default function ErrorsPage() {
  const { t } = useLocale();
  const [items, setItems] = useState<AdminError[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [sourceFilter, setSourceFilter] = useState<string>('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadErrors = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getErrors(severityFilter || undefined, 100);
      const filtered =
        sourceFilter === ''
          ? data
          : data.filter((e: AdminError) => e.source === sourceFilter);
      setItems(filtered);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load errors');
    } finally {
      setLoading(false);
    }
  }, [severityFilter, sourceFilter]);

  useEffect(() => {
    loadErrors();
  }, [loadErrors]);

  return (
    <div className="cleargate-admin-content">
      <div className="cleargate-admin-header">
        <h1>{t('admin.errors.title')}</h1>
        <div className="cleargate-admin-filters">
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="cleargate-admin-select"
          >
            <option value="">{t('admin.errors.severity')}</option>
            <option value="error">{t('admin.errors.filterError')}</option>
            <option value="warning">{t('admin.errors.filterWarning')}</option>
            <option value="info">{t('admin.errors.filterInfo')}</option>
          </select>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="cleargate-admin-select"
          >
            <option value="">{t('admin.errors.source')}</option>
            <option value="client">{t('admin.errors.filterClient')}</option>
            <option value="server">{t('admin.errors.filterServer')}</option>
          </select>
        </div>
      </div>

      {error && <div className="cleargate-admin-error">{error}</div>}

      {loading ? (
        <div className="cleargate-admin-loading">{t('auth.checking')}</div>
      ) : items.length === 0 ? (
        <div className="cleargate-admin-empty">{t('admin.errors.title')} - {t('session.noEntities')}</div>
      ) : (
        <div className="cleargate-admin-table-wrapper">
          <table className="cleargate-admin-table">
            <thead>
              <tr>
                <th>{t('admin.errors.severity')}</th>
                <th>{t('admin.errors.source')}</th>
                <th>{t('admin.errors.message')}</th>
                <th>{t('admin.errors.timestamp')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <ErrorRow
                  key={item.id}
                  item={item}
                  isExpanded={expandedId === item.id}
                  onToggle={() =>
                    setExpandedId(expandedId === item.id ? null : item.id)
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface ErrorRowProps {
  item: AdminError;
  isExpanded: boolean;
  onToggle: () => void;
}

function ErrorRow({ item, isExpanded, onToggle }: ErrorRowProps) {
  const { t } = useLocale();

  const getSeverityClass = (severity: string) => {
    switch (severity) {
      case 'error':
        return 'cleargate-admin-badge--error';
      case 'warning':
        return 'cleargate-admin-badge--warning';
      case 'info':
        return 'cleargate-admin-badge--info';
      default:
        return '';
    }
  };

  return (
    <>
      <tr onClick={onToggle} className="cleargate-admin-table__clickable">
        <td>
          <span className={`cleargate-admin-badge ${getSeverityClass(item.severity)}`}>
            {item.severity}
          </span>
        </td>
        <td className="cleargate-admin-table__mono">{item.source}</td>
        <td className="cleargate-admin-table__ellipsis">{item.message}</td>
        <td className="cleargate-admin-table__small">
          {new Date(item.created_at).toLocaleDateString()}
        </td>
        <td style={{ textAlign: 'center' }}>
          {isExpanded ? '▼' : '▶'}
        </td>
      </tr>
      {isExpanded && (
        <tr className="cleargate-admin-table__expand">
          <td colSpan={5}>
            <div className="cleargate-admin-error-details">
              {item.url && (
                <div>
                  <strong>{t('admin.errors.url')}:</strong>
                  <code>{item.url}</code>
                </div>
              )}
              {item.user_agent && (
                <div>
                  <strong>{t('admin.errors.userAgent')}:</strong>
                  <code className="cleargate-admin-code">{item.user_agent}</code>
                </div>
              )}
              {item.stack_trace && (
                <div>
                  <strong>{t('admin.errors.stack')}:</strong>
                  <pre className="cleargate-admin-pre">{item.stack_trace}</pre>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

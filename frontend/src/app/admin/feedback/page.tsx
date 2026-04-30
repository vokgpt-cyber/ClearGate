'use client';

import { useState, useEffect, useCallback } from 'react';
import { useLocale } from '@/hooks/useLocale';
import { getFeedback, updateFeedback, type AdminFeedback, type FeedbackItem } from '@/lib/api';

// Pulled from the canonical FeedbackItem type so we never drift from it.
type FeedbackStatus = FeedbackItem['status'];
type FeedbackFilter = FeedbackStatus | 'all';

export default function FeedbackPage() {
  const { t } = useLocale();
  const [items, setItems] = useState<AdminFeedback[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FeedbackFilter>('new');

  const loadFeedback = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getFeedback(filter === 'all' ? undefined : filter, 100);
      setItems(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    loadFeedback();
  }, [loadFeedback]);

  const handleReply = async (id: string, reply: string, newStatus: FeedbackStatus) => {
    try {
      await updateFeedback(id, {
        admin_reply: reply,
        // Default 'in_progress' (underscore) to match the canonical
        // FeedbackItem['status'] union — the wire format used by both
        // backend and shared FeedbackItem type. Not 'in-progress'.
        status: newStatus || 'in_progress',
      });
      await loadFeedback();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reply');
    }
  };

  return (
    <div className="cleargate-admin-content">
      <div className="cleargate-admin-header">
        <h1>{t('admin.feedback.title')}</h1>
        <div className="cleargate-admin-filters">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as FeedbackFilter)}
            className="cleargate-admin-select"
          >
            <option value="all">All</option>
            <option value="new">{t('admin.feedback.statusNew')}</option>
            <option value="in_progress">{t('admin.feedback.statusInProgress')}</option>
            <option value="resolved">{t('admin.feedback.statusResolved')}</option>
            <option value="wontfix">{t('admin.feedback.statusWontfix')}</option>
          </select>
        </div>
      </div>

      {error && <div className="cleargate-admin-error">{error}</div>}

      {loading ? (
        <div className="cleargate-admin-loading">{t('auth.checking')}</div>
      ) : items.length === 0 ? (
        <div className="cleargate-admin-empty">{t('admin.feedback.title')} - {t('session.noEntities')}</div>
      ) : (
        <div className="cleargate-admin-feed">
          {items.map((item) => (
            <FeedbackCard
              key={item.id}
              item={item}
              onReply={(reply, status) => handleReply(item.id, reply, status)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface FeedbackCardProps {
  item: AdminFeedback;
  onReply: (reply: string, status: FeedbackStatus) => void;
}

function FeedbackCard({ item, onReply }: FeedbackCardProps) {
  const { t } = useLocale();
  const [reply, setReply] = useState('');
  const [replying, setReplying] = useState(false);
  const [status, setStatus] = useState(item.status);

  const handleSubmitReply = async () => {
    if (!reply.trim()) return;
    setReplying(true);
    try {
      await onReply(reply, status);
      setReply('');
    } finally {
      setReplying(false);
    }
  };

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'bug':
        return 'cleargate-admin-badge--error';
      case 'suggestion':
        return 'cleargate-admin-badge--info';
      case 'question':
        return 'cleargate-admin-badge--warning';
      default:
        return '';
    }
  };

  const getStatusColor = (st: string) => {
    switch (st) {
      case 'new':
        return 'cleargate-admin-pill--new';
      case 'in-progress':
        return 'cleargate-admin-pill--in-progress';
      case 'resolved':
        return 'cleargate-admin-pill--resolved';
      case 'wontfix':
        return 'cleargate-admin-pill--wontfix';
      default:
        return '';
    }
  };

  return (
    <div className="cleargate-admin-card">
      <div className="cleargate-admin-card__header">
        <div>
          <h4 className="cleargate-admin-card__user">{item.username}</h4>
          <span className={`cleargate-admin-badge ${getCategoryColor(item.category)}`}>
            {t(`admin.feedback.category${item.category.charAt(0).toUpperCase()}${item.category.slice(1)}`)}
          </span>
          <span className={`cleargate-admin-pill ${getStatusColor(status)}`}>{status}</span>
        </div>
        <time className="cleargate-admin-card__time">
          {new Date(item.created_at).toLocaleDateString()}
        </time>
      </div>

      <p className="cleargate-admin-card__text">{item.text}</p>

      {item.admin_reply && (
        <div className="cleargate-admin-card__reply">
          <strong>{t('admin.feedback.reply')}:</strong>
          <p>{item.admin_reply}</p>
        </div>
      )}

      <div className="cleargate-admin-card__actions">
        <textarea
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          placeholder={t('admin.feedback.replyPlaceholder')}
          className="cleargate-admin-card__textarea"
        />
        <div className="cleargate-admin-card__action-buttons">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as FeedbackStatus)}
            className="cleargate-admin-select cleargate-admin-select--small"
          >
            <option value="new">{t('admin.feedback.statusNew')}</option>
            <option value="in_progress">{t('admin.feedback.statusInProgress')}</option>
            <option value="resolved">{t('admin.feedback.statusResolved')}</option>
            <option value="wontfix">{t('admin.feedback.statusWontfix')}</option>
          </select>
          <button
            onClick={handleSubmitReply}
            disabled={replying || !reply.trim()}
            className="cleargate-admin-btn cleargate-admin-btn--primary cleargate-admin-btn--small"
          >
            {replying ? t('admin.feedback.sending') : t('admin.feedback.send')}
          </button>
        </div>
      </div>
    </div>
  );
}

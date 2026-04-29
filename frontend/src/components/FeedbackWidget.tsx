'use client';

/**
 * FeedbackWidget — floating feedback button & modal (bottom-right).
 *
 * Two views:
 *   1. Submit — text field, category select, optional screenshot
 *   2. History — list of user's past feedback with admin replies
 *
 * Hidden on /admin/* routes.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { submitFeedback, listMyFeedback, type FeedbackItem } from '@/lib/api';
import { useLocale } from '@/hooks/useLocale';
import { toast } from 'sonner';

type FeedbackView = 'submit' | 'history';

export function FeedbackWidget() {
  const pathname = usePathname();
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<FeedbackView>('submit');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedbackList, setFeedbackList] = useState<FeedbackItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [text, setText] = useState('');
  const [category, setCategory] = useState<'bug' | 'suggestion' | 'question'>('bug');
  const lastSeenRef = useRef<number>(0);

  // Hide on admin routes
  if (pathname?.startsWith('/admin')) {
    return null;
  }

  // Poll feedback history every 30s while modal is open
  useEffect(() => {
    if (!open || view !== 'history') return;

    const loadFeedback = async () => {
      try {
        const items = await listMyFeedback();
        setFeedbackList(items);

        // Count unread replies
        const now = Date.now();
        const unread = items.filter((item) => {
          if (!item.admin_reply_at) return false;
          const repliedAt = new Date(item.admin_reply_at).getTime();
          return repliedAt > lastSeenRef.current;
        }).length;
        setUnreadCount(unread);
      } catch (e) {
        // Silently ignore fetch errors
      }
    };

    loadFeedback();
    const interval = setInterval(loadFeedback, 30000);
    return () => clearInterval(interval);
  }, [open, view]);

  const handleSubmit = useCallback(async () => {
    if (!text.trim()) {
      toast.error(t('feedback.emptyText') || 'Please enter feedback text.');
      return;
    }

    setIsSubmitting(true);
    try {
      await submitFeedback({ text, category });
      setText('');
      toast.success(t('feedback.thanks') || 'Спасибо! Сообщение получено.');
      setView('history');
      // Refresh history immediately
      const items = await listMyFeedback();
      setFeedbackList(items);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Error submitting feedback';
      toast.error(msg);
    } finally {
      setIsSubmitting(false);
    }
  }, [text, category, t]);

  const handleOpenModal = useCallback(() => {
    setOpen(true);
    lastSeenRef.current = Date.now();
    setUnreadCount(0);
  }, []);

  const handleCloseModal = useCallback(() => {
    setOpen(false);
  }, []);

  return (
    <>
      {/* Floating button */}
      <button
        className="cleargate-feedback-button"
        onClick={handleOpenModal}
        aria-label={t('feedback.button') || 'Help'}
        title={t('feedback.button') || 'Help'}
      >
        {unreadCount > 0 && (
          <span className="cleargate-feedback-badge">{unreadCount}</span>
        )}
        <span className="cleargate-feedback-icon">?</span>
      </button>

      {/* Modal backdrop & content */}
      {open && (
        <div className="cleargate-feedback-modal-backdrop" onClick={handleCloseModal}>
          <div className="cleargate-feedback-modal" onClick={(e) => e.stopPropagation()}>
            {/* Header with tabs */}
            <div className="cleargate-feedback-header">
              <div className="cleargate-feedback-tabs">
                <button
                  className={`cleargate-feedback-tab ${view === 'submit' ? 'is-active' : ''}`}
                  onClick={() => setView('submit')}
                >
                  {t('feedback.titleSubmit') || 'Сообщить о проблеме'}
                </button>
                <button
                  className={`cleargate-feedback-tab ${view === 'history' ? 'is-active' : ''}`}
                  onClick={() => setView('history')}
                >
                  {t('feedback.titleHistory') || 'Мои сообщения'}
                </button>
              </div>
              <button
                className="cleargate-feedback-close"
                onClick={handleCloseModal}
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {/* Content */}
            <div className="cleargate-feedback-content">
              {view === 'submit' ? (
                <div className="cleargate-feedback-submit">
                  <div className="cleargate-feedback-form-group">
                    <label htmlFor="feedback-text" className="cleargate-feedback-label">
                      {t('feedback.placeholder') || 'Опишите подробно, что произошло...'}
                    </label>
                    <textarea
                      id="feedback-text"
                      className="cleargate-feedback-textarea"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      placeholder={t('feedback.placeholder') || 'Опишите подробно...'}
                      disabled={isSubmitting}
                      rows={5}
                    />
                  </div>

                  <div className="cleargate-feedback-form-group">
                    <label htmlFor="feedback-category" className="cleargate-feedback-label">
                      {t('feedback.categoryLabel') || 'Категория'}
                    </label>
                    <select
                      id="feedback-category"
                      className="cleargate-feedback-select"
                      value={category}
                      onChange={(e) =>
                        setCategory(e.target.value as 'bug' | 'suggestion' | 'question')
                      }
                      disabled={isSubmitting}
                    >
                      <option value="bug">{t('feedback.categoryBug') || 'Баг'}</option>
                      <option value="suggestion">
                        {t('feedback.categorySuggestion') || 'Предложение'}
                      </option>
                      <option value="question">
                        {t('feedback.categoryQuestion') || 'Вопрос'}
                      </option>
                    </select>
                  </div>

                  <button
                    className="cleargate-feedback-submit-btn"
                    onClick={handleSubmit}
                    disabled={isSubmitting || !text.trim()}
                  >
                    {isSubmitting ? t('feedback.submitting') || 'Отправляем...' : t('feedback.submit') || 'Отправить'}
                  </button>
                </div>
              ) : (
                <div className="cleargate-feedback-history">
                  {feedbackList.length === 0 ? (
                    <div className="cleargate-feedback-empty">
                      {t('feedback.noHistory') || 'У вас пока нет обращений'}
                    </div>
                  ) : (
                    feedbackList.map((item) => (
                      <div key={item.id} className="cleargate-feedback-thread">
                        {/* User's message */}
                        <div className="cleargate-feedback-bubble cleargate-feedback-bubble--user">
                          <div className="cleargate-feedback-bubble-text">{item.text}</div>
                          <div className="cleargate-feedback-bubble-meta">
                            <span className="cleargate-feedback-category">
                              {t(`feedback.category${item.category.charAt(0).toUpperCase() + item.category.slice(1)}`) || item.category}
                            </span>
                            <span className="cleargate-feedback-status">
                              {t(`feedback.status${item.status.charAt(0).toUpperCase() + item.status.replace('_', '').slice(1)}`) || item.status}
                            </span>
                          </div>
                        </div>

                        {/* Admin reply (if any) */}
                        {item.admin_reply && (
                          <div className="cleargate-feedback-bubble cleargate-feedback-bubble--admin">
                            <div className="cleargate-feedback-admin-label">
                              {t('feedback.adminReply') || 'Ответ администратора'}
                            </div>
                            <div className="cleargate-feedback-bubble-text">{item.admin_reply}</div>
                            {item.admin_reply_at && (
                              <div className="cleargate-feedback-bubble-meta">
                                {new Date(item.admin_reply_at).toLocaleString()}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

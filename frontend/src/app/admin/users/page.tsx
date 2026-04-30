'use client';

import { useState, useEffect, useCallback } from 'react';
import { useLocale } from '@/hooks/useLocale';
import {
  getUsers,
  createUser,
  updateUser,
  syncAD,
  type AdminUser,
  type CreateUserPayload,
} from '@/lib/api';

export default function UsersPage() {
  const { t } = useLocale();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const loadUsers = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getUsers();
      setUsers(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncAD();
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  const handleToggleActive = async (userId: string, isActive: boolean) => {
    try {
      await updateUser(userId, { is_active: !isActive });
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Update failed');
    }
  };

  return (
    <div className="cleargate-admin-content">
      <div className="cleargate-admin-header">
        <h1>{t('admin.users.title')}</h1>
        <div className="cleargate-admin-actions">
          <button onClick={handleSync} disabled={syncing} className="cleargate-admin-btn">
            {syncing ? t('admin.users.syncing') : t('admin.users.syncAD')}
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="cleargate-admin-btn cleargate-admin-btn--primary"
          >
            {t('admin.users.create')}
          </button>
        </div>
      </div>

      {error && <div className="cleargate-admin-error">{error}</div>}

      {loading ? (
        <div className="cleargate-admin-loading">{t('auth.checking')}</div>
      ) : (
        <div className="cleargate-admin-table-wrapper">
          <table className="cleargate-admin-table">
            <thead>
              <tr>
                <th>{t('admin.users.username')}</th>
                <th>{t('admin.users.email')}</th>
                <th>{t('admin.users.role')}</th>
                <th>{t('admin.users.active')}</th>
                <th>{t('admin.users.created')}</th>
                <th>{t('admin.users.lastLogin')}</th>
                <th>{t('admin.users.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.user_id}>
                  <td className="cleargate-admin-table__mono">{user.username}</td>
                  <td>{user.email || '—'}</td>
                  <td>
                    <span className="cleargate-admin-badge">{user.role}</span>
                  </td>
                  <td>
                    <span className={user.is_active ? 'cleargate-admin-pill--active' : 'cleargate-admin-pill--inactive'}>
                      {user.is_active ? t('admin.users.active') : t('admin.users.disabled')}
                    </span>
                  </td>
                  <td className="cleargate-admin-table__small">
                    {new Date(user.created_at).toLocaleDateString()}
                  </td>
                  <td className="cleargate-admin-table__small">
                    {user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : '—'}
                  </td>
                  <td>
                    <button
                      onClick={() => handleToggleActive(user.user_id, user.is_active)}
                      className="cleargate-admin-action-btn"
                    >
                      {user.is_active ? t('admin.users.disable') : t('admin.users.enable')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreateModal && (
        <CreateUserModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            loadUsers();
          }}
        />
      )}
    </div>
  );
}

interface CreateUserModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

function CreateUserModal({ onClose, onSuccess }: CreateUserModalProps) {
  const { t } = useLocale();
  const [formData, setFormData] = useState<CreateUserPayload>({
    username: '',
    password: '',
    role: 'lawyer',
    email: '',
    display_name: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData((prev: CreateUserPayload) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await createUser(formData);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="cleargate-admin-modal-overlay" onClick={onClose}>
      <div className="cleargate-admin-modal" onClick={(e) => e.stopPropagation()}>
        <h2>{t('admin.users.create')}</h2>
        {error && <div className="cleargate-admin-error">{error}</div>}
        <form onSubmit={handleSubmit} className="cleargate-admin-form">
          <div className="cleargate-admin-form-group">
            <label>{t('admin.users.username')}</label>
            <input
              type="text"
              name="username"
              value={formData.username}
              onChange={handleChange}
              required
            />
          </div>
          <div className="cleargate-admin-form-group">
            <label>{t('auth.password')}</label>
            <input
              type="password"
              name="password"
              value={formData.password}
              onChange={handleChange}
              required
            />
          </div>
          <div className="cleargate-admin-form-group">
            <label>{t('admin.users.email')}</label>
            <input
              type="email"
              name="email"
              value={formData.email || ''}
              onChange={handleChange}
            />
          </div>
          <div className="cleargate-admin-form-group">
            <label>{t('admin.users.displayName')}</label>
            <input
              type="text"
              name="display_name"
              value={formData.display_name || ''}
              onChange={handleChange}
            />
          </div>
          <div className="cleargate-admin-form-group">
            <label>{t('admin.users.role')}</label>
            <select name="role" value={formData.role} onChange={handleChange}>
              <option value="lawyer">Lawyer</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="cleargate-admin-form-actions">
            <button type="button" onClick={onClose} className="cleargate-admin-btn">
              {t('popover.cancel')}
            </button>
            <button type="submit" disabled={submitting} className="cleargate-admin-btn cleargate-admin-btn--primary">
              {submitting ? t('auth.submitting') : t('admin.users.create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

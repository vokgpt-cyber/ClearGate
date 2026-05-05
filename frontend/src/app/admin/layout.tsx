'use client';

import { useRouter, usePathname } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { useLocale } from '@/hooks/useLocale';
import Link from 'next/link';
import { ReactNode, useEffect } from 'react';

interface AdminLayoutProps {
  children: ReactNode;
}

export default function AdminLayout({ children }: AdminLayoutProps) {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const { t } = useLocale();

  // Protect admin routes
  useEffect(() => {
    if (!isLoading && (!user || user.role !== 'admin')) {
      router.replace('/');
    }
  }, [user, isLoading, router]);

  if (isLoading) {
    return (
      <div className="cleargate-app">
        <div className="cleargate-app__main">
          <div className="cleargate-app__content">
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
                {t('auth.checking')}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!user || user.role !== 'admin') {
    return null;
  }

  return (
    <div className="cleargate-app">
      <Sidebar />
      <div className="cleargate-app__main">
        <div className="cleargate-app__content">
          {children}
        </div>
      </div>
    </div>
  );
}

function Sidebar() {
  const { t } = useLocale();
  const pathname = usePathname();

  const isActive = (path: string) => pathname.startsWith(path);

  return (
    <div className="cleargate-admin-sidebar">
      <div className="cleargate-admin-sidebar__header">
        <h3 className="cleargate-admin-sidebar__title">Admin</h3>
        <Link href="/" className="cleargate-admin-sidebar__back">
          {t('admin.backToWorkspace')}
        </Link>
      </div>

      <nav className="cleargate-admin-sidebar__nav">
        <Link
          href="/admin/users"
          className={`cleargate-admin-sidebar__link ${isActive('/admin/users') ? 'is-active' : ''}`}
        >
          {t('admin.users.title')}
        </Link>
        <Link
          href="/admin/feedback"
          className={`cleargate-admin-sidebar__link ${isActive('/admin/feedback') ? 'is-active' : ''}`}
        >
          {t('admin.feedback.title')}
        </Link>
        <Link
          href="/admin/analytics"
          className={`cleargate-admin-sidebar__link ${isActive('/admin/analytics') ? 'is-active' : ''}`}
        >
          {t('admin.analytics.title')}
        </Link>
        <Link
          href="/admin/errors"
          className={`cleargate-admin-sidebar__link ${isActive('/admin/errors') ? 'is-active' : ''}`}
        >
          {t('admin.errors.title')}
        </Link>
      </nav>
    </div>
  );
}

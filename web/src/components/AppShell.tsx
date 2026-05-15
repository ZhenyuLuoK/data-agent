import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import {
  PlugIcon,
  TerminalIcon,
  UploadIcon,
  SettingsIcon,
  BookIcon,
  ChevronDownIcon,
  PlayIcon,
} from './Icon';
import { Toaster } from './Toaster';
import { LanguageSwitch } from './LanguageSwitch';
import { ThemeToggle } from './ThemeToggle';
import { useDefaultsStore } from '@/state/defaultsStore';
import { getDefaults } from '@/api/client';
import type { DefaultsResponse } from '@/api/types';
import { useI18n } from '@/i18n/I18nProvider';

export function AppShell() {
  const { t } = useI18n();
  const [serverDefaults, setServerDefaults] = useState<DefaultsResponse | null>(null);
  const userDefaults = useDefaultsStore((s) => s.defaults);
  const [docsOpen, setDocsOpen] = useState(false);
  const loc = useLocation();

  useEffect(() => {
    getDefaults()
      .then(setServerDefaults)
      .catch(() => setServerDefaults(null));
  }, []);

  const navItems = [
    { to: '/tasks', label: t('nav.tasks'), icon: PlayIcon },
    { to: '/upload', label: t('nav.upload'), icon: UploadIcon },
    { to: '/runs', label: t('nav.runs'), icon: TerminalIcon },
  ];

  const activeModel = userDefaults.model || serverDefaults?.model || '—';
  const activeBase = userDefaults.api_base || serverDefaults?.api_base || '—';

  return (
    <div className="min-h-screen flex flex-col">
      <header
        className="sticky top-0 z-40 h-14 flex items-center px-4 gap-4 border-b"
        style={{
          background: 'color-mix(in oklch, var(--color-bg) 85%, transparent)',
          backdropFilter: 'blur(12px)',
          borderColor: 'var(--color-border)',
        }}
      >
        <NavLink to="/" className="flex items-center gap-2 group">
          <span
            className="grid place-items-center w-7 h-7 rounded-md"
            style={{
              background: 'linear-gradient(135deg, var(--color-accent), oklch(56% 0.20 320))',
              color: 'var(--color-accent-fg)',
            }}
          >
            <PlugIcon size={16} />
          </span>
          <span className="font-semibold tracking-tight">data-agent</span>
          <span className="chip" style={{ height: 18, fontSize: 10 }}>
            {t('app.brand.tag')}
          </span>
        </NavLink>

        <nav className="flex items-center gap-1 ml-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `inline-flex items-center gap-2 h-8 px-3 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-[color:var(--color-surface-hover)] text-[color:var(--color-fg)]'
                    : 'text-[color:var(--color-fg-muted)] hover:bg-[color:var(--color-surface)] hover:text-[color:var(--color-fg)]'
                }`
              }
            >
              <item.icon />
              {item.label}
            </NavLink>
          ))}

          <div className="relative">
            <button
              className={`inline-flex items-center gap-2 h-8 px-3 rounded-md text-sm font-medium transition-colors ${
                loc.pathname.startsWith('/docs')
                  ? 'bg-[color:var(--color-surface-hover)] text-[color:var(--color-fg)]'
                  : 'text-[color:var(--color-fg-muted)] hover:bg-[color:var(--color-surface)] hover:text-[color:var(--color-fg)]'
              }`}
              onClick={() => setDocsOpen((v) => !v)}
              onBlur={() => window.setTimeout(() => setDocsOpen(false), 120)}
              aria-expanded={docsOpen}
              aria-haspopup="menu"
            >
              <BookIcon /> {t('nav.docs')} <ChevronDownIcon size={14} />
            </button>
            {docsOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-1 w-56 surface-raised py-1 text-sm"
                style={{ animation: 'fadein 140ms var(--ease-out-expo)' }}
              >
                <NavLink
                  to="/docs/architecture"
                  className="block px-3 py-2 hover:bg-[color:var(--color-surface)]"
                  role="menuitem"
                >
                  {t('nav.docs.architecture')}
                </NavLink>
                <NavLink
                  to="/docs/papers"
                  className="block px-3 py-2 hover:bg-[color:var(--color-surface)]"
                  role="menuitem"
                >
                  {t('nav.docs.papers')}
                </NavLink>
                <div className="divider my-1" />
                <a
                  className="block px-3 py-2 hover:bg-[color:var(--color-surface)] text-[color:var(--color-fg-muted)]"
                  href="/static/docs/agent-workflow.svg"
                  target="_blank"
                  rel="noreferrer"
                  role="menuitem"
                >
                  {t('nav.docs.workflow')} ↗
                </a>
              </div>
            )}
          </div>
        </nav>

        <div className="flex-1" />

        <div
          className="hidden md:flex items-center gap-2 text-xs text-[color:var(--color-fg-muted)] font-mono"
          title={`model: ${activeModel}\napi_base: ${activeBase}`}
        >
          <span className="chip">
            <span className="status-dot status-running" />
            {activeModel.length > 18 ? `${activeModel.slice(0, 18)}…` : activeModel}
          </span>
          <span className="text-[color:var(--color-fg-faint)]">
            {activeBase.length > 28 ? `${activeBase.slice(0, 28)}…` : activeBase}
          </span>
        </div>

        <ThemeToggle />
        <LanguageSwitch />

        <NavLink
          to="/settings"
          className="btn btn-ghost btn-sm"
          aria-label={t('nav.settings')}
          title={t('nav.settings')}
        >
          <SettingsIcon />
        </NavLink>
      </header>

      <main className="flex-1 min-h-0">
        <Outlet />
      </main>

      <Toaster />
      <style>{`@keyframes fadein { from { opacity: 0; transform: translateY(-4px) } to { opacity: 1; transform: translateY(0) } }`}</style>
    </div>
  );
}

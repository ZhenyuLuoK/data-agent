import { useI18n } from '@/i18n/I18nProvider';
import type { LocaleKey } from '@/i18n/locales';

const ITEMS: { id: LocaleKey; label: string }[] = [
  { id: 'zh', label: '中' },
  { id: 'en', label: 'EN' },
];

export function LanguageSwitch() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div
      role="group"
      aria-label={t('lang.switch')}
      className="flex items-center surface px-0.5 py-0.5"
      style={{ borderRadius: 999 }}
    >
      {ITEMS.map((item) => {
        const active = locale === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => setLocale(item.id)}
            aria-pressed={active}
            className={`h-6 px-2.5 text-xs font-medium rounded-full transition-all ${
              active
                ? 'text-[color:var(--color-accent-fg)]'
                : 'text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)]'
            }`}
            style={{
              background: active ? 'var(--color-accent)' : 'transparent',
              transitionTimingFunction: 'var(--ease-out-expo)',
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

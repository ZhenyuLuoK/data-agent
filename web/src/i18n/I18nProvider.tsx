import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import {
  detectInitialLocale,
  makeTranslator,
  type LocaleKey,
  type Translator,
} from './locales';

interface I18nContextValue {
  locale: LocaleKey;
  t: Translator;
  setLocale: (next: LocaleKey) => void;
}

const I18nContext = createContext<I18nContextValue | null>(null);

const STORAGE_KEY = 'dabench.web.lang';

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<LocaleKey>(() => detectInitialLocale());

  const setLocale = useCallback((next: LocaleKey) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore — quota / private mode
    }
    document.documentElement.lang = next === 'zh' ? 'zh-CN' : 'en';
    setLocaleState(next);
  }, []);

  const t = useMemo(() => makeTranslator(locale), [locale]);

  // Sync html lang on first mount
  useMemo(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
  }, [locale]);

  const value = useMemo<I18nContextValue>(
    () => ({ locale, t, setLocale }),
    [locale, t, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used inside <I18nProvider>');
  return ctx;
}

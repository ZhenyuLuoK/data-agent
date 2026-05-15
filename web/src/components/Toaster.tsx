import { useToastStore, type ToastTone } from '@/state/toastStore';
import { useI18n } from '@/i18n/I18nProvider';
import { XIcon, AlertIcon, CheckIcon } from './Icon';

const TONE_CLASS: Record<ToastTone, { border: string; icon: React.ReactNode; fg: string }> = {
  info: {
    border: 'border-[color:var(--color-info)]',
    icon: <AlertIcon />,
    fg: 'text-[color:var(--color-info)]',
  },
  success: {
    border: 'border-[color:var(--color-success)]',
    icon: <CheckIcon />,
    fg: 'text-[color:var(--color-success)]',
  },
  warning: {
    border: 'border-[color:var(--color-warning)]',
    icon: <AlertIcon />,
    fg: 'text-[color:var(--color-warning)]',
  },
  danger: {
    border: 'border-[color:var(--color-danger)]',
    icon: <AlertIcon />,
    fg: 'text-[color:var(--color-danger)]',
  },
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);
  const { t } = useI18n();

  return (
    <div
      className="fixed top-16 right-4 z-[60] flex flex-col gap-2 w-[360px] max-w-[92vw]"
      role="region"
      aria-label={t('common.empty')}
    >
      {toasts.map((t) => {
        const tone = TONE_CLASS[t.tone];
        return (
          <div
            key={t.id}
            className={`surface-raised border-l-2 ${tone.border} px-4 py-3 flex items-start gap-3`}
            style={{ animation: 'toastin 200ms var(--ease-out-expo)' }}
          >
            <span className={tone.fg}>{tone.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold leading-tight">{t.title}</div>
              {t.description && (
                <div className="text-xs text-[color:var(--color-fg-muted)] mt-1 break-words">
                  {t.description}
                </div>
              )}
            </div>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => dismiss(t.id)}
              aria-label={t.title}
            >
              <XIcon size={14} />
            </button>
          </div>
        );
      })}
      <style>{`@keyframes toastin { from { transform: translateX(16px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }`}</style>
    </div>
  );
}

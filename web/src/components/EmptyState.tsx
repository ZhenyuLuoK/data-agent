import { AlertIcon } from './Icon';
import { useI18n } from '@/i18n/I18nProvider';

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}

export function EmptyState({ title, description, action, icon }: EmptyStateProps) {
  return (
    <div className="surface p-10 flex flex-col items-center text-center">
      <div
        className="w-12 h-12 rounded-xl grid place-items-center mb-4"
        style={{
          background: 'var(--color-bg-elevated)',
          color: 'var(--color-fg-muted)',
        }}
      >
        {icon ?? <AlertIcon size={20} />}
      </div>
      <div className="font-semibold mb-1">{title}</div>
      {description && (
        <div className="text-sm text-[color:var(--color-fg-muted)] max-w-md leading-relaxed">
          {description}
        </div>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <EmptyState
      title={t('empty.loadFailed')}
      description={message}
      action={
        onRetry ? (
          <button className="btn" onClick={onRetry}>
            {t('common.retry')}
          </button>
        ) : null
      }
      icon={<AlertIcon size={20} />}
    />
  );
}

export function LoadingState({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-center py-16 text-[color:var(--color-fg-muted)] text-sm gap-3">
      <span
        className="spin inline-block w-4 h-4 rounded-full border-2"
        style={{
          borderColor: 'var(--color-border-strong)',
          borderTopColor: 'var(--color-accent)',
        }}
      />
      {label ?? t('common.loading')}
    </div>
  );
}

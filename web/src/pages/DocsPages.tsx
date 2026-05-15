import { ExternalLinkIcon } from '@/components/Icon';
import { useI18n } from '@/i18n/I18nProvider';

interface DocsFrameProps {
  title: string;
  src: string;
}

function DocsFrame({ title, src }: DocsFrameProps) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <div className="px-6 py-3 border-b border-[color:var(--color-border)] flex items-center gap-2">
        <span className="font-semibold text-sm">{title}</span>
        <span className="font-mono text-xs text-[color:var(--color-fg-faint)]">{src}</span>
        <div className="flex-1" />
        <a
          className="btn btn-sm"
          href={src}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLinkIcon size={12} /> {t('docs.openInNewTab')}
        </a>
      </div>
      <iframe
        src={src}
        className="flex-1 w-full bg-white"
        title={title}
        referrerPolicy="no-referrer"
      />
    </div>
  );
}

export const DocsArchitecturePage = () => {
  const { t } = useI18n();
  return (
    <DocsFrame
      title={t('nav.docs.architecture')}
      src="/static/docs/agent_architecture_summary.html"
    />
  );
};

export const DocsPapersPage = () => {
  const { t } = useI18n();
  return (
    <DocsFrame
      title={t('nav.docs.papers')}
      src="/static/docs/data-agent/html/index.html"
    />
  );
};

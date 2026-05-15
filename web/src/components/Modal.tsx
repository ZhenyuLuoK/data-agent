import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { XIcon } from './Icon';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}

export function Modal({ open, onClose, title, children, footer, width = 560 }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'var(--color-bg-overlay)', backdropFilter: 'blur(8px)' }}
      onClick={onClose}
    >
      <div
        className="surface-raised w-full overflow-hidden"
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-[color:var(--color-border)]">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="关闭">
            <XIcon />
          </button>
        </header>
        <div className="px-5 py-5 max-h-[70vh] overflow-y-auto">{children}</div>
        {footer && (
          <footer className="px-5 py-4 border-t border-[color:var(--color-border)] flex items-center justify-end gap-2">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  width?: number;
}

export function Drawer({ open, onClose, title, children, width = 480 }: DrawerProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="absolute inset-0"
        style={{ background: 'var(--color-bg-overlay)' }}
      />
      <aside
        className="relative h-full surface-raised border-l border-[color:var(--color-border)] flex flex-col"
        style={{
          width,
          maxWidth: '92vw',
          borderRadius: 0,
          animation: 'slidein 200ms var(--ease-out-expo)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-[color:var(--color-border)]">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="关闭">
            <XIcon />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
        <style>{`@keyframes slidein { from { transform: translateX(24px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }`}</style>
      </aside>
    </div>,
    document.body,
  );
}

import { create } from 'zustand';

export type ToastTone = 'info' | 'success' | 'warning' | 'danger';

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
  duration?: number;
}

interface ToastStore {
  toasts: Toast[];
  push: (toast: Omit<Toast, 'id'>) => number;
  dismiss: (id: number) => void;
}

let counter = 1;

export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  push: (toast) => {
    const id = counter++;
    const next: Toast = { duration: 4500, ...toast, id };
    set({ toasts: [...get().toasts, next] });
    if (next.duration && next.duration > 0) {
      window.setTimeout(() => get().dismiss(id), next.duration);
    }
    return id;
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const toast = {
  info: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: 'info', title, description }),
  success: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: 'success', title, description }),
  warning: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: 'warning', title, description }),
  danger: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: 'danger', title, description }),
};

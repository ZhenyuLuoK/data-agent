import { create } from 'zustand';
import type { AgentOverrides } from '@/api/types';

const STORAGE_KEY = 'dabench.web.defaults';
const REMEMBER_KEY = 'dabench.web.rememberApiKey';

interface PersistedShape {
  defaults: Partial<AgentOverrides>;
  rememberApiKey: boolean;
}

function loadPersisted(): PersistedShape {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const remember = localStorage.getItem(REMEMBER_KEY) === '1';
    const defaults = raw ? (JSON.parse(raw) as Partial<AgentOverrides>) : {};
    if (!remember) {
      // Defensive: scrub api_key if user un-checked but old value lingered
      delete defaults.api_key;
    }
    return { defaults, rememberApiKey: remember };
  } catch {
    return { defaults: {}, rememberApiKey: false };
  }
}

interface DefaultsStore {
  defaults: Partial<AgentOverrides>;
  rememberApiKey: boolean;
  setDefaults: (next: Partial<AgentOverrides>) => void;
  setRememberApiKey: (remember: boolean) => void;
  clear: () => void;
}

export const useDefaultsStore = create<DefaultsStore>((set, get) => {
  const initial = loadPersisted();
  return {
    defaults: initial.defaults,
    rememberApiKey: initial.rememberApiKey,

    setDefaults: (next) => {
      // Drop empty strings so they don't clobber server defaults on submit
      const cleaned: Partial<AgentOverrides> = {};
      for (const [key, value] of Object.entries(next) as [
        keyof AgentOverrides,
        AgentOverrides[keyof AgentOverrides],
      ][]) {
        if (value === '' || value === undefined || value === null) continue;
        // @ts-expect-error narrowed by key
        cleaned[key] = value;
      }
      const remember = get().rememberApiKey;
      const toPersist = { ...cleaned };
      if (!remember) delete toPersist.api_key;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toPersist));
      set({ defaults: cleaned });
    },

    setRememberApiKey: (remember) => {
      localStorage.setItem(REMEMBER_KEY, remember ? '1' : '0');
      if (!remember) {
        const next = { ...get().defaults };
        delete next.api_key;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        set({ defaults: next, rememberApiKey: false });
      } else {
        set({ rememberApiKey: true });
      }
    },

    clear: () => {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(REMEMBER_KEY);
      set({ defaults: {}, rememberApiKey: false });
    },
  };
});

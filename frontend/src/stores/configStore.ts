import { create } from 'zustand';
import { configApi } from '../services/api';
import { useAuthStore } from './authStore';

/**
 * Runtime UI config (GET /api/config). `demoMode` turns on the CPA demo profile from
 * instance env (GANTRY_DEMO_MODE) without a frontend rebuild. Defaults to off, so a
 * failed or pending fetch leaves the normal Gantry UI unchanged.
 */
interface ConfigState {
  demoMode: boolean;
  firmName: string;
  loaded: boolean;
  load: () => Promise<void>;
}

export const useConfigStore = create<ConfigState>((set) => ({
  demoMode: false,
  firmName: '',
  loaded: false,
  load: async () => {
    try {
      const cfg = await configApi.get();
      set({
        demoMode: cfg.demo_mode === true,
        firmName: typeof cfg.demo_firm_name === 'string' ? cfg.demo_firm_name.trim() : '',
        loaded: true,
      });
    } catch {
      set({ demoMode: false, firmName: '', loaded: true });
    }
  },
}));

/** True when demo mode is on and the signed-in user is not an admin (issue 1). */
export function useHideDevChrome(): boolean {
  const demoMode = useConfigStore((s) => s.demoMode);
  const role = useAuthStore((s) => s.user?.role);
  return demoMode && role !== 'admin';
}

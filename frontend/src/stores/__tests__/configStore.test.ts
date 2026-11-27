import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useConfigStore, useHideDevChrome } from '../configStore';
import { useAuthStore } from '../authStore';

vi.mock('../../services/api', () => ({
  configApi: { get: vi.fn() },
  authApi: { login: vi.fn(), logout: vi.fn(), me: vi.fn() },
}));

import { configApi } from '../../services/api';

const admin = { id: 1, email: 'a@example.com', display_name: 'Setup Admin', role: 'admin' as const };
const member = { id: 2, email: 'u@example.com', display_name: 'Sarah Chen, CPA', role: 'user' as const };

describe('configStore (GANTRY_DEMO_MODE)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useConfigStore.setState({ demoMode: false, firmName: '', loaded: false });
  });

  it('defaults to demo mode off before load', () => {
    expect(useConfigStore.getState().demoMode).toBe(false);
    expect(useConfigStore.getState().firmName).toBe('');
  });

  it('observes demo_mode === true from the runtime API (no rebuild)', async () => {
    vi.mocked(configApi.get).mockResolvedValue({ demo_mode: true, demo_firm_name: 'Sample & Co. CPAs' });
    await useConfigStore.getState().load();
    const s = useConfigStore.getState();
    expect(s.demoMode).toBe(true);
    expect(s.firmName).toBe('Sample & Co. CPAs');
    expect(s.loaded).toBe(true);
  });

  it('keeps demo mode off when the API says false', async () => {
    vi.mocked(configApi.get).mockResolvedValue({ demo_mode: false, demo_firm_name: '' });
    await useConfigStore.getState().load();
    expect(useConfigStore.getState().demoMode).toBe(false);
  });

  it('falls back to off when the config fetch fails', async () => {
    vi.mocked(configApi.get).mockRejectedValue(new Error('down'));
    await useConfigStore.getState().load();
    expect(useConfigStore.getState().demoMode).toBe(false);
    expect(useConfigStore.getState().loaded).toBe(true);
  });
});

describe('useHideDevChrome', () => {
  const cases = [
    { demoMode: false, user: member, hide: false },
    { demoMode: false, user: admin, hide: false },
    { demoMode: true, user: admin, hide: false },
    { demoMode: true, user: member, hide: true },
  ];
  it.each(cases)('demo=$demoMode role=$user.role -> hide=$hide', ({ demoMode, user, hide }) => {
    useConfigStore.setState({ demoMode, loaded: true });
    useAuthStore.setState({ user, isLoading: false, error: null });
    const { result } = renderHook(() => useHideDevChrome());
    expect(result.current).toBe(hide);
  });
});

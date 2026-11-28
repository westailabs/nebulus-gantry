import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { DemoAdminRoute } from '../DemoAdminRoute';
import { useAuthStore } from '../../stores/authStore';
import { useConfigStore } from '../../stores/configStore';

const admin = { id: 1, email: 'a@example.com', display_name: 'Setup Admin', role: 'admin' as const };
const member = { id: 2, email: 'u@example.com', display_name: 'Sarah Chen, CPA', role: 'user' as const };

function renderOrchestrator() {
  return render(
    <MemoryRouter initialEntries={['/orchestrator']}>
      <Routes>
        <Route path="/" element={<div>Home page</div>} />
        <Route path="/orchestrator" element={<DemoAdminRoute><div>Orchestrator page</div></DemoAdminRoute>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('DemoAdminRoute (/orchestrator)', () => {
  it('demo mode + non-admin: redirects home', () => {
    useConfigStore.setState({ demoMode: true, loaded: true });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderOrchestrator();
    expect(screen.getByText('Home page')).toBeInTheDocument();
    expect(screen.queryByText('Orchestrator page')).not.toBeInTheDocument();
  });

  it('demo mode + admin: still reachable', () => {
    useConfigStore.setState({ demoMode: true, loaded: true });
    useAuthStore.setState({ user: admin, isLoading: false, error: null });
    renderOrchestrator();
    expect(screen.getByText('Orchestrator page')).toBeInTheDocument();
  });

  it('flag off: unchanged for a non-admin route-hit', () => {
    useConfigStore.setState({ demoMode: false, loaded: true });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderOrchestrator();
    expect(screen.getByText('Orchestrator page')).toBeInTheDocument();
  });

  it('config still loading: a non-admin sees a loader, not a blank page or the console', () => {
    useConfigStore.setState({ demoMode: false, loaded: false });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderOrchestrator();
    expect(screen.getByRole('status')).toHaveTextContent('Loading...');
    expect(screen.queryByText('Orchestrator page')).not.toBeInTheDocument();
    expect(screen.queryByText('Home page')).not.toBeInTheDocument();
  });

  it('loading then demo mode: the loader gives way to a redirect home', () => {
    useConfigStore.setState({ demoMode: false, loaded: false });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderOrchestrator();
    expect(screen.getByRole('status')).toBeInTheDocument();
    act(() => useConfigStore.setState({ demoMode: true, loaded: true }));
    expect(screen.getByText('Home page')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('loading then flag off: the loader gives way to the page, never blank', () => {
    useConfigStore.setState({ demoMode: false, loaded: false });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderOrchestrator();
    act(() => useConfigStore.setState({ demoMode: false, loaded: true }));
    expect(screen.getByText('Orchestrator page')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('a failed config fetch ends the loader with the flag off', async () => {
    const { configApi } = await import('../../services/api');
    vi.spyOn(configApi, 'get').mockRejectedValue(new Error('down'));
    useConfigStore.setState({ demoMode: false, loaded: false });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderOrchestrator();
    await act(async () => { await useConfigStore.getState().load(); });
    expect(screen.getByText('Orchestrator page')).toBeInTheDocument();
  });

  it('an admin is never held behind the loader', () => {
    useConfigStore.setState({ demoMode: true, loaded: false });
    useAuthStore.setState({ user: admin, isLoading: false, error: null });
    renderOrchestrator();
    expect(screen.getByText('Orchestrator page')).toBeInTheDocument();
  });
});

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useAuthStore } from '../../stores/authStore';
import { useUIStore } from '../../stores/uiStore';
import { useConfigStore } from '../../stores/configStore';
import { Layout } from '../Layout';

vi.mock('../SearchModal', () => ({ SearchModal: () => null }));

const admin = { id: 1, email: 'a@example.com', display_name: 'Setup Admin', role: 'admin' as const };
const member = { id: 2, email: 'u@example.com', display_name: 'Sarah Chen, CPA', role: 'user' as const };

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Layout><div>Page body</div></Layout>
    </MemoryRouter>,
  );
}

describe('Layout nav vs CPA demo mode', () => {
  beforeEach(() => {
    useUIStore.setState({ isSidebarOpen: false, overlordAvailable: false });
  });

  it('demo mode + non-admin: no Orchestrator link', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderLayout();
    expect(screen.queryByRole('link', { name: 'Orchestrator' })).not.toBeInTheDocument();
  });

  it('demo mode + admin: Orchestrator link still there', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    useAuthStore.setState({ user: admin, isLoading: false, error: null });
    renderLayout();
    expect(screen.getByRole('link', { name: 'Orchestrator' })).toBeInTheDocument();
  });

  it('flag off: admin Orchestrator link unchanged, non-admin still without it', () => {
    useConfigStore.setState({ demoMode: false, firmName: '', loaded: true });
    useAuthStore.setState({ user: admin, isLoading: false, error: null });
    const { unmount } = renderLayout();
    expect(screen.getByRole('link', { name: 'Orchestrator' })).toBeInTheDocument();
    unmount();
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderLayout();
    expect(screen.queryByRole('link', { name: 'Orchestrator' })).not.toBeInTheDocument();
  });
});

describe('Layout header firm name (issue 5)', () => {
  beforeEach(() => {
    useUIStore.setState({ isSidebarOpen: false, overlordAvailable: false });
    useAuthStore.setState({ user: member, isLoading: false, error: null });
  });

  it('demo mode: shows the firm name and the walkthrough user\'s display name', () => {
    useConfigStore.setState({ demoMode: true, firmName: 'Sample & Co. CPAs', loaded: true });
    renderLayout();
    expect(screen.getByTestId('header-firm-name')).toHaveTextContent('Sample & Co. CPAs');
    expect(screen.getByRole('link', { name: /Sarah Chen, CPA/ })).toBeInTheDocument();
  });

  it('flag off: no firm name even if one is configured', () => {
    useConfigStore.setState({ demoMode: false, firmName: 'Sample & Co. CPAs', loaded: true });
    renderLayout();
    expect(screen.queryByTestId('header-firm-name')).not.toBeInTheDocument();
  });
});

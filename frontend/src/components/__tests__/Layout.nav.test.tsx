import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useAuthStore } from '../../stores/authStore';
import { useUIStore } from '../../stores/uiStore';
import { Layout } from '../Layout';

vi.mock('../SearchModal', () => ({
  SearchModal: () => null,
}));

const admin = { id: 1, email: 'admin@example.com', display_name: 'Demo Admin', role: 'admin' as const };
const member = { id: 2, email: 'user@example.com', display_name: 'Sam', role: 'user' as const };

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={(
            <Layout>
              <div>Page body</div>
            </Layout>
          )}
        />
      </Routes>
    </MemoryRouter>,
  );
}

function nav() {
  return screen.getByRole('navigation', { name: 'Main' });
}

describe('Layout header nav', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: admin, isLoading: false, error: null });
    useUIStore.setState({ isSidebarOpen: false, overlordAvailable: false });
  });

  it('places Home after Search and before Orchestrator, and the logo links home', () => {
    renderAt('/orchestrator');
    const home = within(nav()).getByRole('link', { name: 'Home' });
    const orchestrator = screen.getByRole('link', { name: 'Orchestrator' });
    const search = screen.getByRole('button', { name: /search/i });
    const logo = screen.getByRole('link', { name: 'Gantry home' });
    expect(home).toHaveAttribute('href', '/');
    expect(logo).toHaveAttribute('href', '/');
    expect(search.compareDocumentPosition(home) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(home.compareDocumentPosition(orchestrator) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('marks the current tab with aria-current="page" on Orchestrator, Admin, Home, and Settings', () => {
    const { unmount } = renderAt('/orchestrator');
    expect(screen.getByRole('link', { name: 'Orchestrator' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Admin' })).not.toHaveAttribute('aria-current');
    const homeInNav = within(nav()).getByRole('link', { name: 'Home' });
    expect(homeInNav).not.toHaveAttribute('aria-current');
    unmount();

    renderAt('/admin');
    expect(screen.getByRole('link', { name: 'Admin' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav()).getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current');
  });

  it('marks Home only on the chat route, not on nested paths', () => {
    const { unmount } = renderAt('/');
    expect(within(nav()).getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page');
    unmount();

    renderAt('/settings');
    expect(within(nav()).getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: /Demo Admin/ })).toHaveAttribute('aria-current', 'page');
  });

  it('lets a non-admin get home from Settings, and hides admin-only tabs', () => {
    useAuthStore.setState({ user: member, isLoading: false, error: null });
    renderAt('/settings');
    expect(screen.queryByRole('link', { name: 'Orchestrator' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Gantry home' })).toHaveAttribute('href', '/');
    expect(within(nav()).getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
  });

  it('shows Overlord when available and marks it current', () => {
    useUIStore.setState({ overlordAvailable: true });
    renderAt('/overlord');
    const link = screen.getByRole('link', { name: 'Overlord' });
    expect(link).toHaveAttribute('href', '/overlord');
    expect(link).toHaveAttribute('aria-current', 'page');
    expect(within(nav()).getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
  });

  it('can reach Home from /personas (a route with no own nav item)', () => {
    renderAt('/personas');
    expect(within(nav()).getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: 'Gantry home' })).toHaveAttribute('href', '/');
  });
});

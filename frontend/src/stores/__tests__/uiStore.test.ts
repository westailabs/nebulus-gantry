import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore, SIDEBAR_DEFAULT_WIDTH, SIDEBAR_MIN_WIDTH } from '../uiStore';

describe('uiStore', () => {
  beforeEach(() => {
    useUIStore.setState({ isSidebarOpen: false });
  });

  it('starts with sidebar closed', () => {
    const state = useUIStore.getState();
    expect(state.isSidebarOpen).toBe(false);
  });

  it('toggleSidebar flips the state', () => {
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().isSidebarOpen).toBe(true);

    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().isSidebarOpen).toBe(false);
  });

  it('openSidebar sets true', () => {
    useUIStore.getState().openSidebar();
    expect(useUIStore.getState().isSidebarOpen).toBe(true);
  });

  it('closeSidebar sets false', () => {
    useUIStore.getState().openSidebar();
    useUIStore.getState().closeSidebar();
    expect(useUIStore.getState().isSidebarOpen).toBe(false);
  });
});

describe('sidebarWidth', () => {
  beforeEach(() => {
    localStorage.clear();
    useUIStore.setState({ sidebarWidth: SIDEBAR_DEFAULT_WIDTH });
  });

  it('clamps to the minimum and persists', () => {
    useUIStore.getState().setSidebarWidth(50);
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_MIN_WIDTH);
    expect(localStorage.getItem('gantry-sidebar-width')).toBe(String(SIDEBAR_MIN_WIDTH));
  });

  it('clamps to half the viewport', () => {
    const max = Math.floor(window.innerWidth * 0.5);
    useUIStore.getState().setSidebarWidth(5000);
    expect(useUIStore.getState().sidebarWidth).toBe(max);
  });

  it('resetSidebarWidth restores the default', () => {
    useUIStore.getState().setSidebarWidth(400);
    useUIStore.getState().resetSidebarWidth();
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(localStorage.getItem('gantry-sidebar-width')).toBe(String(SIDEBAR_DEFAULT_WIDTH));
  });
});

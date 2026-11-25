import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore, loadSidebarWidth, SIDEBAR_DEFAULT_WIDTH, SIDEBAR_MIN_WIDTH } from '../uiStore';

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

describe('loadSidebarWidth', () => {
  beforeEach(() => localStorage.clear());

  it('uses the 256px default when the key is missing (Number(null) must not become 0)', () => {
    expect(localStorage.getItem('gantry-sidebar-width')).toBeNull();
    expect(Number(null)).toBe(0); // documents the bug: Number(null) is 0
    expect(loadSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
  });

  it('uses the default for blank, non-finite, and non-positive stored values', () => {
    localStorage.setItem('gantry-sidebar-width', '');
    expect(loadSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
    localStorage.setItem('gantry-sidebar-width', '   ');
    expect(loadSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
    localStorage.setItem('gantry-sidebar-width', 'not-a-number');
    expect(loadSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
    localStorage.setItem('gantry-sidebar-width', '0');
    expect(loadSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
  });

  it('returns a persisted in-range width', () => {
    localStorage.setItem('gantry-sidebar-width', '320');
    expect(loadSidebarWidth()).toBe(320);
  });
});

import { create } from 'zustand';

export const SIDEBAR_DEFAULT_WIDTH = 256;
export const SIDEBAR_MIN_WIDTH = 200;
const WIDTH_KEY = 'gantry-sidebar-width';

function clampWidth(width: number, viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth) {
  const max = Math.max(SIDEBAR_MIN_WIDTH, Math.floor(viewportWidth * 0.5));
  return Math.min(Math.max(Math.round(width), SIDEBAR_MIN_WIDTH), max);
}

export function loadSidebarWidth(): number {
  if (typeof localStorage === 'undefined') return SIDEBAR_DEFAULT_WIDTH;
  // getItem returns null when unset; Number(null) is 0, which would clamp to
  // the 200px minimum instead of the 256px default. Treat missing, blank,
  // non-finite, and non-positive values as "use the default".
  const raw = localStorage.getItem(WIDTH_KEY);
  if (raw == null || raw.trim() === '') return SIDEBAR_DEFAULT_WIDTH;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return SIDEBAR_DEFAULT_WIDTH;
  return clampWidth(n);
}

function persistWidth(width: number) {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem(WIDTH_KEY, String(width));
}

interface UIState {
  isSidebarOpen: boolean;
  sidebarWidth: number;
  overlordAvailable: boolean | null;
  toggleSidebar: () => void;
  openSidebar: () => void;
  closeSidebar: () => void;
  setSidebarWidth: (width: number) => void;
  resetSidebarWidth: () => void;
  checkOverlord: () => Promise<void>;
}

export const useUIStore = create<UIState>((set) => ({
  isSidebarOpen: false,
  sidebarWidth: loadSidebarWidth(),
  overlordAvailable: null,
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  openSidebar: () => set({ isSidebarOpen: true }),
  closeSidebar: () => set({ isSidebarOpen: false }),
  setSidebarWidth: (width) => {
    const sidebarWidth = clampWidth(width);
    persistWidth(sidebarWidth);
    set({ sidebarWidth });
  },
  resetSidebarWidth: () => {
    persistWidth(SIDEBAR_DEFAULT_WIDTH);
    set({ sidebarWidth: clampWidth(SIDEBAR_DEFAULT_WIDTH) });
  },
  checkOverlord: async () => {
    try {
      const apiUrl = import.meta.env.VITE_API_URL ?? '';
      const res = await fetch(`${apiUrl}/api/overlord/available`);
      if (res.ok) {
        const data = await res.json();
        set({ overlordAvailable: data.available === true });
      } else {
        set({ overlordAvailable: false });
      }
    } catch {
      set({ overlordAvailable: false });
    }
  },
}));

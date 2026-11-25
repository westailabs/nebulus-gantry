import { useCallback, useEffect, useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { useUIStore, SIDEBAR_DEFAULT_WIDTH, SIDEBAR_MIN_WIDTH } from '../stores/uiStore';

export function clampSidebarWidth(width: number, viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth) {
  const max = Math.max(SIDEBAR_MIN_WIDTH, Math.floor(viewportWidth * 0.5));
  return Math.min(Math.max(Math.round(width), SIDEBAR_MIN_WIDTH), max);
}

/** Pointer + keyboard resize for the conversation sidebar. */
export function useSidebarResize() {
  const sidebarWidth = useUIStore((s) => s.sidebarWidth);
  const setSidebarWidth = useUIStore((s) => s.setSidebarWidth);
  const resetSidebarWidth = useUIStore((s) => s.resetSidebarWidth);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(sidebarWidth);

  useEffect(() => {
    const onResize = () => setSidebarWidth(useUIStore.getState().sidebarWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [setSidebarWidth]);

  const onPointerDown = useCallback((e: PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragging.current = true;
    startX.current = e.clientX;
    startW.current = useUIStore.getState().sidebarWidth;
    const el = e.currentTarget as HTMLElement;
    if (typeof el.setPointerCapture === 'function' && e.pointerId != null) {
      el.setPointerCapture(e.pointerId);
    }
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  const onPointerMove = useCallback((e: PointerEvent) => {
    if (!dragging.current) return;
    setSidebarWidth(startW.current + (e.clientX - startX.current));
  }, [setSidebarWidth]);

  const endDrag = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  const onDoubleClick = useCallback(() => {
    resetSidebarWidth();
  }, [resetSidebarWidth]);

  const onKeyDown = useCallback((e: KeyboardEvent) => {
    const step = e.shiftKey ? 32 : 16;
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setSidebarWidth(useUIStore.getState().sidebarWidth - step);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      setSidebarWidth(useUIStore.getState().sidebarWidth + step);
    } else if (e.key === 'Home') {
      e.preventDefault();
      setSidebarWidth(SIDEBAR_MIN_WIDTH);
    } else if (e.key === 'End') {
      e.preventDefault();
      setSidebarWidth(window.innerWidth * 0.5);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      resetSidebarWidth();
    }
  }, [setSidebarWidth, resetSidebarWidth]);

  return {
    sidebarWidth,
    defaultWidth: SIDEBAR_DEFAULT_WIDTH,
    minWidth: SIDEBAR_MIN_WIDTH,
    maxWidth: Math.max(SIDEBAR_MIN_WIDTH, Math.floor((typeof window === 'undefined' ? 1280 : window.innerWidth) * 0.5)),
    onPointerDown,
    onPointerMove,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onLostPointerCapture: endDrag,
    onDoubleClick,
    onKeyDown,
  };
}

export { SIDEBAR_DEFAULT_WIDTH, SIDEBAR_MIN_WIDTH };

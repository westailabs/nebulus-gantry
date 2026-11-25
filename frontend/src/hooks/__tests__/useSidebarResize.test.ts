import { describe, it, expect } from 'vitest';
import { clampSidebarWidth } from '../useSidebarResize';
import { SIDEBAR_MIN_WIDTH } from '../../stores/uiStore';

describe('clampSidebarWidth', () => {
  it('enforces a 200px minimum', () => {
    expect(clampSidebarWidth(50, 1200)).toBe(SIDEBAR_MIN_WIDTH);
  });

  it('caps at half the viewport', () => {
    expect(clampSidebarWidth(900, 1000)).toBe(500);
  });

  it('rounds and leaves a mid value alone', () => {
    expect(clampSidebarWidth(320.6, 1200)).toBe(321);
  });
});

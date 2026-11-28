import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { useConfigStore } from '../stores/configStore';

/**
 * Engineering-console routes (e.g. /orchestrator). In CPA demo mode a non-admin who
 * route-hits one is sent home. With the flag off nothing changes for any role. While
 * the runtime config is still loading a non-admin sees a small loader (never a blank
 * page and never a flash of the console), then is redirected home or shown the page.
 * A failed config fetch counts as loaded with the flag off, so the loader always ends.
 */
export function DemoAdminRoute({ children }: { children: ReactNode }) {
  const role = useAuthStore((s) => s.user?.role);
  const { demoMode, loaded } = useConfigStore();
  if (role !== 'admin') {
    if (!loaded) {
      return (
        <div role="status" className="min-h-[50vh] flex items-center justify-center text-gray-500">
          Loading...
        </div>
      );
    }
    if (demoMode) return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

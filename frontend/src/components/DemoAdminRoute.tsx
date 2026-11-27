import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { useConfigStore } from '../stores/configStore';

/**
 * Engineering-console routes (e.g. /orchestrator). In CPA demo mode a non-admin who
 * route-hits one is sent home. With the flag off nothing changes for any role. While
 * the runtime config is still loading, non-admins see nothing rather than a flash of
 * the console.
 */
export function DemoAdminRoute({ children }: { children: ReactNode }) {
  const role = useAuthStore((s) => s.user?.role);
  const { demoMode, loaded } = useConfigStore();
  if (role !== 'admin') {
    if (!loaded) return null;
    if (demoMode) return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

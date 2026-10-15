import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { backendFallbackPathFor, backendUnavailableEvent } from "../api/errors";

/**
 * Global handler for "the backend is down / restarting". The API client fires
 * `openbot:backend-unavailable` on 404, 5xx or network failure; this component
 * navigates the user to the default home view (inbox) instead of leaving them
 * on a page showing the raw error.
 *
 * The navigation is guarded against loops: while the user is already on the
 * home view, failing queries there only swap in the friendly offline copy —
 * no navigation is re-triggered.
 */
export default function BackendFallback({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const goHome = () => {
      const target = backendFallbackPathFor(location.pathname);
      if (target) navigate(target, { replace: true });
    };
    window.addEventListener(backendUnavailableEvent, goHome);
    return () => window.removeEventListener(backendUnavailableEvent, goHome);
  }, [navigate, location.pathname]);

  return <>{children}</>;
}

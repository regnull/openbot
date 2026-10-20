import { useEffect, useState, type RefObject } from "react";
import { isWebGL2Available } from "../openlings/viewer/OpenlingViewer";
import { OfficeViewer, type OfficeLoadStats, type OfficeSnapshot } from "./OfficeViewer";

export type OfficeViewerState =
  | { phase: "loading"; progress: number | null }
  | { phase: "ready"; stats: OfficeLoadStats }
  | { phase: "error"; message: string }
  | { phase: "unsupported"; message: string };

declare global {
  interface Window { __officeViewer?: OfficeViewer }
}

/** Mounts the Living Office into `containerRef` and streams its (throttled) snapshots. */
export function useOfficeViewer(containerRef: RefObject<HTMLDivElement | null>) {
  const [viewer, setViewer] = useState<OfficeViewer | null>(null);
  const [snapshot, setSnapshot] = useState<OfficeSnapshot | null>(null);
  const [state, setState] = useState<OfficeViewerState>(() => isWebGL2Available()
    ? { phase: "loading", progress: null }
    : { phase: "unsupported", message: "This browser or device does not provide WebGL 2, which the 3D office needs." });
  const [attempt, setAttempt] = useState(0);
  const supported = state.phase !== "unsupported";

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !supported) return;
    let v: OfficeViewer;
    try {
      v = new OfficeViewer(el, {
        onProgress: (progress) => setState({ phase: "loading", progress }),
        onReady: (stats) => setState({ phase: "ready", stats }),
        onError: (error) => setState({ phase: "error", message: error.message }),
        onSnapshot: setSnapshot,
      });
    } catch (error) {
      // oxlint-disable-next-line react/set-state-in-effect
      setState({ phase: "unsupported", message: `The 3D renderer could not start: ${error instanceof Error ? error.message : String(error)}` });
      return;
    }
    setViewer(v);
    // Handle for the office's browser validation script; dev builds only.
    if (import.meta.env.DEV) window.__officeViewer = v;
    return () => {
      v.dispose();
      setViewer(null);
      setSnapshot(null);
      if (window.__officeViewer === v) delete window.__officeViewer;
    };
  }, [containerRef, attempt, supported]);

  const retry = () => {
    setState({ phase: "loading", progress: null });
    setAttempt((n) => n + 1);
  };
  return { viewer, state, snapshot, retry };
}

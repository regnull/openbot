import { useEffect, useState, type RefObject } from "react";
import type { OpenlingStats } from "./viewer/loadOpenling";
import { OpenlingViewer, isWebGL2Available } from "./viewer/OpenlingViewer";

export type LoadedStats = OpenlingStats & { loadMs: number; drawCalls: number; bytes: number | null };

export type ViewerState =
  | { phase: "loading"; progress: number | null }
  | { phase: "ready"; stats: LoadedStats }
  | { phase: "error"; message: string }
  | { phase: "unsupported"; message: string };

declare global {
  interface Window { __openlingViewer?: OpenlingViewer }
}

/**
 * Mounts an OpenlingViewer into `containerRef` for the lifetime of the component (or until
 * retry, or until the model changes). `animated` loads the rigged asset and the props.
 */
export function useOpenlingViewer(containerRef: RefObject<HTMLDivElement | null>, modelUrl: string, { animated = false }: { animated?: boolean } = {}) {
  const [viewer, setViewer] = useState<OpenlingViewer | null>(null);
  const [state, setState] = useState<ViewerState>(() => isWebGL2Available()
    ? { phase: "loading", progress: null }
    : { phase: "unsupported", message: "This browser or device does not provide WebGL 2, which the 3D preview needs." });
  const [attempt, setAttempt] = useState(0);
  const supported = state.phase !== "unsupported";

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !supported) return;
    let v: OpenlingViewer;
    try {
      v = new OpenlingViewer(el, {
        modelUrl,
        animated,
        onProgress: (progress) => setState({ phase: "loading", progress }),
        onLoad: (stats) => setState({ phase: "ready", stats }),
        onError: (error) => setState({ phase: "error", message: error.message }),
      });
    } catch (error) {
      // WebGLRenderer throws synchronously when it cannot get a context; nothing else can report it.
      // oxlint-disable-next-line react/set-state-in-effect
      setState({ phase: "unsupported", message: `The 3D renderer could not start: ${error instanceof Error ? error.message : String(error)}` });
      return;
    }
    setViewer(v);
    // oxlint-disable-next-line react/set-state-in-effect
    setState((prev) => (prev.phase === "ready" ? { phase: "loading", progress: null } : prev));
    // Handle for the lab's browser validation script (frame timing, screenshots); dev builds only.
    if (import.meta.env.DEV) window.__openlingViewer = v;
    return () => {
      v.dispose();
      setViewer(null);
      if (window.__openlingViewer === v) delete window.__openlingViewer;
    };
  }, [containerRef, modelUrl, animated, attempt, supported]);

  const retry = () => {
    setState({ phase: "loading", progress: null });
    setAttempt((n) => n + 1);
  };
  return { viewer, state, retry };
}

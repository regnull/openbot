import { useEffect, useRef, useState } from "react";
import { ControlGroup, ToolButton } from "../components/openlings/LabControls";
import { AgentChat } from "../components/office/AgentChat";
import { AgentDetails, AgentList, EventLog } from "../components/office/OfficePanels";
import type { OfficeQuality } from "../components/office/OfficeViewer";
import { OFFICE_LIGHTING, type OfficeLightingId } from "../components/office/runtime/officeLighting";
import { useOfficeViewer, type OfficeViewerState } from "../components/office/useOfficeViewer";
import { Button, Spinner } from "../components/ui";
import { OFFICE_LAYOUT } from "../lib/office/layout";

const OVERVIEWS = [
  { id: "main", label: "Isometric" }, { id: "front", label: "Front" }, { id: "top", label: "Top" },
  { id: "left", label: "Left" }, { id: "right", label: "Right" },
];
const ZONE_VIEWS = [...OFFICE_LAYOUT.zones].sort((a, b) => a.number - b.number);
const SPEEDS = [0.5, 1, 2, 4];

/** Where the chat panel sits over the 3D view (keep in step with AgentChat's classes). */
function chatInsets(w: number, h: number): { right: number; bottom: number } {
  return window.matchMedia?.("(min-width: 768px)").matches
    ? { right: Math.min(360, w * 0.42) + 12, bottom: 0 }
    : { right: 0, bottom: h * 0.64 + 8 };
}

/**
 * The Living Office (Phase 1): a 3D office where Openlings work through a simulated
 * OpenBot task. Everything shown is demo data; nothing here talks to the backend.
 * Phase 1.1: clicking an Openling greets you and opens a chat to assign it demo tasks.
 */
export default function OfficeLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const { viewer, state, snapshot, retry } = useOfficeViewer(containerRef);
  const mainRef = useRef<HTMLElement>(null);
  const [chatSeq, setChatSeq] = useState(-1);
  const [view, setView] = useState("main");
  const [bubbles, setBubbles] = useState(true);
  const [labels, setLabels] = useState(true);
  const [lighting, setLighting] = useState<OfficeLightingId>("day");
  const [quality, setQuality] = useState<OfficeQuality>("high");
  const ready = state.phase === "ready";

  useEffect(() => { viewer?.setBubbles(bubbles); }, [viewer, bubbles]);
  useEffect(() => { viewer?.setZoneLabels(labels); }, [viewer, labels]);
  useEffect(() => { viewer?.setLighting(lighting); }, [viewer, lighting]);
  useEffect(() => { viewer?.setQuality(quality); }, [viewer, quality]);
  // close-ups leave room for the chat panel, which opens with every selection
  useEffect(() => {
    const el = mainRef.current;
    if (!el || !viewer) return;
    const update = () => { const i = chatInsets(el.clientWidth, el.clientHeight); viewer.setViewInsets(i.right, i.bottom); };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [viewer]);

  const chooseView = (id: string) => { setView(id); viewer?.view(id); };
  const selected = snapshot?.agents.find((a) => a.id === snapshot.selected) ?? null;
  const running = snapshot?.running ?? true;
  // the chat shows for the selection it was opened for; closing it keeps the selection
  const chat = snapshot?.chat && snapshot.selectSeq !== chatSeq ? snapshot.chat : null;

  return (
    <div className="flex h-dvh min-h-[520px] flex-col overflow-hidden bg-canvas text-fg">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pb-2 pt-3 sm:px-6">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 truncate text-sm font-semibold tracking-tight">
            OpenBot <span className="text-faint">/</span> Living Office
            <span className="rounded-ui border border-warn/40 bg-warn/10 px-1.5 py-px text-[10px] font-medium uppercase tracking-[0.08em] text-warn">Demo</span>
          </h1>
          <p className="truncate font-sans text-xs text-muted">{snapshot ? snapshot.phase : "Phase 1 · simulated workflow"}</p>
        </div>
        {snapshot && (
          <dl className="hidden items-center gap-4 font-sans text-xs md:flex" aria-label="Office summary">
            <Stat label="Active agents" value={`${snapshot.active}/${snapshot.agents.length}`} />
            <Stat label="In progress" value={String(snapshot.inProgress)} />
            <Stat label="Completed" value={String(snapshot.completed)} />
          </dl>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <ControlGroup label="Simulation">
            <ToolButton active={running} onClick={() => (running ? viewer?.pause() : viewer?.play())} title={running ? "Pause the workflow" : "Resume the workflow"}>
              {running ? "Pause" : snapshot && snapshot.t > 0 ? "Resume" : "Play"}
            </ToolButton>
            <ToolButton onClick={() => viewer?.reset()} title="Restart the demo from the beginning">Reset</ToolButton>
          </ControlGroup>
          <ControlGroup label="Speed">
            {SPEEDS.map((s) => <ToolButton key={s} active={snapshot?.speed === s} onClick={() => viewer?.setSpeed(s)}>{s}×</ToolButton>)}
          </ControlGroup>
          <ControlGroup label="Trigger">
            <ToolButton onClick={() => viewer?.triggerBlocked()} title="The Tester hits a failure; Ops investigates">Blocked</ToolButton>
            <ToolButton onClick={() => viewer?.triggerComplete()} title="Finish the active subtasks now">Complete</ToolButton>
            <ToolButton onClick={() => viewer?.triggerReport()} title="The Reporter presents and reports to the Commander">Report</ToolButton>
          </ControlGroup>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 sm:px-6 md:flex-row">
        <main ref={mainRef} className="relative min-h-[52dvh] min-w-0 flex-1 overflow-hidden rounded-ui border border-line bg-sunken md:min-h-0">
          <div ref={containerRef} className="absolute inset-0 cursor-grab active:cursor-grabbing" role="img"
            aria-label="Interactive 3D OpenBot office. Drag to orbit, right-drag to pan, scroll to zoom, click an Openling to select it." />
          <Overlay state={state} onRetry={retry} />
          {ready && !chat && (
            <div className="pointer-events-none absolute bottom-2 left-2 rounded-ui border border-line bg-surface/90 px-2 py-1 font-sans text-[11px] text-muted backdrop-blur-sm">
              Drag to orbit · right-drag to pan · scroll to zoom · click an Openling to say hi
            </div>
          )}
          {viewer && chat && snapshot && (
            <AgentChat key={chat.agent} chat={chat} canGreet={snapshot.running}
              onSend={(text) => viewer.sendMessage(chat.agent, text)}
              onAnswer={(id, action) => viewer.answerProposal(chat.agent, id, action)}
              onQuick={(id) => viewer.quickTask(chat.agent, id)}
              onSayHi={() => viewer.sayHi(chat.agent)}
              onClose={() => setChatSeq(snapshot.selectSeq)} />
          )}
        </main>
        <aside aria-label="Office panels" className="max-h-[40dvh] shrink-0 overflow-y-auto rounded-ui border border-line bg-surface md:max-h-none md:w-[300px]">
          {!snapshot && <p className="px-3 py-3 font-sans text-xs text-muted">Loading the office and the Openlings…</p>}
          {snapshot && selected && (
            <AgentDetails row={selected} following={snapshot.following} onClose={() => viewer?.select(null)}
              chatOpen={!!chat} onChat={() => viewer?.select(selected.id, false)}
              onFocus={() => viewer?.focusAgent(selected.id, false)}
              onFollow={() => (snapshot.following ? viewer?.stopFollow() : viewer?.focusAgent(selected.id, true))} />
          )}
          {snapshot && <AgentList snapshot={snapshot} onSelect={(id) => viewer?.select(id, true)} />}
          {snapshot && <EventLog snapshot={snapshot} />}
        </aside>
      </div>

      <footer className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 px-3 pb-3 pt-2.5 sm:px-6">
        <ControlGroup label="View">
          {OVERVIEWS.map((v) => <ToolButton key={v.id} active={view === v.id} onClick={() => chooseView(v.id)}>{v.label}</ToolButton>)}
        </ControlGroup>
        <ControlGroup label="Zones">
          {ZONE_VIEWS.map((z) => (
            <ToolButton key={z.id} active={view === z.id} onClick={() => chooseView(z.id)} title={`${z.label} — ${z.tagline}`}>
              <span className="tabular-nums">{z.number}</span><span className="hidden xl:inline"> {z.label.split(" /")[0].replace("Central ", "")}</span>
            </ToolButton>
          ))}
        </ControlGroup>
        <ControlGroup label="Show">
          <ToolButton active={bubbles} onClick={() => setBubbles(!bubbles)} title="Status bubbles above the Openlings">Bubbles</ToolButton>
          <ToolButton active={labels} onClick={() => setLabels(!labels)} title="Numbered zone labels">Labels</ToolButton>
        </ControlGroup>
        <ControlGroup label="Light">
          {(Object.keys(OFFICE_LIGHTING) as OfficeLightingId[]).map((id) => (
            <ToolButton key={id} active={lighting === id} onClick={() => setLighting(id)}>{OFFICE_LIGHTING[id].label}</ToolButton>
          ))}
        </ControlGroup>
        <ControlGroup label="Quality">
          {(["high", "balanced", "reduced"] as OfficeQuality[]).map((q) => (
            <ToolButton key={q} active={quality === q} onClick={() => setQuality(q)}>{q[0].toUpperCase() + q.slice(1)}</ToolButton>
          ))}
        </ControlGroup>
      </footer>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-faint">{label}</dt>
      <dd className="font-mono text-sm font-medium tabular-nums text-fg">{value}</dd>
    </div>
  );
}

function Overlay({ state, onRetry }: { state: OfficeViewerState; onRetry: () => void }) {
  if (state.phase === "ready") return null;
  return (
    <div className="absolute inset-0 flex items-center justify-center p-6">
      <div className="max-w-sm rounded-ui border border-line bg-surface/95 px-4 py-3 text-center text-xs leading-relaxed backdrop-blur-sm" role={state.phase === "loading" ? "status" : "alert"}>
        {state.phase === "loading" && (
          <span className="inline-flex items-center gap-2 text-muted">
            <Spinner />Loading the office{state.progress !== null ? ` · ${Math.round(state.progress * 100)}%` : "…"}
          </span>
        )}
        {state.phase === "error" && (
          <div className="space-y-2">
            <p className="font-medium text-danger">The office could not be loaded.</p>
            <p className="break-words text-muted">{state.message}</p>
            <Button size="sm" variant="secondary" onClick={onRetry}>Try again</Button>
          </div>
        )}
        {state.phase === "unsupported" && (
          <div className="space-y-1">
            <p className="font-medium text-fg">3D office unavailable</p>
            <p className="text-muted">{state.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}

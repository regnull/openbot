import { useEffect, useRef, useState } from "react";
import { ControlGroup, ToolButton } from "../components/openlings/LabControls";
import {
  AnimationSection, ExpressionSection, GallerySection, MultiSection, RolesSection, Section, WardrobeSection,
} from "../components/openlings/LabPanels";
import { useCharacterState } from "../components/openlings/useCharacterState";
import type { OpenlingCharacter } from "../components/openlings/runtime/OpenlingCharacter";
import type { StageMode } from "../components/openlings/runtime/LabStage";
import { useOpenlingViewer, type ViewerState } from "../components/openlings/useOpenlingViewer";
import { LIGHTING_PRESETS, type LightingPresetId } from "../components/openlings/viewer/lighting";
import { ANIMATED_OPENLING_URL, BASE_OPENLING_URL } from "../components/openlings/viewer/loadOpenling";
import { Button, Spinner } from "../components/ui";
import { CAMERA_VIEWS, DEFAULT_VIEW, type CameraViewId } from "../lib/openlings/cameraViews";
import { PROPS, type PropId } from "../lib/openlings/props";
import type { RoleId } from "../lib/openlings/roles";

type LabTab = "single" | "roles" | "props" | "multi";
const TABS: { id: LabTab; label: string }[] = [
  { id: "single", label: "Single" },
  { id: "roles", label: "Roles" },
  { id: "props", label: "Props" },
  { id: "multi", label: "Multi-agent" },
];
const STAGE_FOR_TAB: Record<LabTab, StageMode> = { single: "single", roles: "single", props: "props", multi: "multi" };
type ModelId = "animated" | "static";

/**
 * Internal lab for the Openling character system: the rigged Base Openling with its six
 * clips, expressions and 13 props; the six role presets; the props gallery; several
 * independent Openlings at once. The static lookdev GLB stays available as the
 * visual-fidelity baseline.
 */
export default function OpenlingsLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [model, setModel] = useState<ModelId>("animated");
  const animated = model === "animated";
  const { viewer, state, retry } = useOpenlingViewer(containerRef, animated ? ANIMATED_OPENLING_URL : BASE_OPENLING_URL, { animated });
  const [tab, setTab] = useState<LabTab>("single");
  const [view, setView] = useState<CameraViewId>(DEFAULT_VIEW);
  const [lighting, setLighting] = useState<LightingPresetId>("studio");
  const [bloom, setBloom] = useState(LIGHTING_PRESETS.studio.bloom);
  const [exposure, setExposure] = useState(1);
  const [role, setRole] = useState<RoleId | null>(null);
  const [stageVersion, setStageVersion] = useState(0);
  const [pendingProp, setPendingProp] = useState<PropId | null>(null);
  const ready = state.phase === "ready";

  useEffect(() => { viewer?.setLighting(lighting); }, [viewer, lighting]);
  useEffect(() => { viewer?.setBloom(bloom); }, [viewer, bloom]);
  useEffect(() => { viewer?.setExposure(exposure); }, [viewer, exposure]);
  const stageMode = STAGE_FOR_TAB[tab];
  useEffect(() => {
    if (!viewer?.stage || !ready) return;
    // Single and Roles share one Openling: only rebuild the stage when the mode really changes.
    if (viewer.stage.mode !== stageMode) {
      viewer.setStageMode(stageMode);
      // oxlint-disable-next-line react/set-state-in-effect
      setView(viewer.stage.framing().view);
    }
    // oxlint-disable-next-line react/set-state-in-effect
    setStageVersion((v) => v + 1);
  }, [viewer, ready, stageMode]);

  const stage = ready ? viewer?.stage ?? null : null;
  // stageVersion: the primary character is recreated whenever the stage mode is set
  const character = stage && stageVersion >= 0 ? stage.primary : null;

  const chooseView = (id: CameraViewId) => { setView(id); viewer?.setView(id); };
  const reset = () => { setView(DEFAULT_VIEW); viewer?.setView("reset"); };
  const chooseLighting = (id: LightingPresetId) => { setLighting(id); setBloom(LIGHTING_PRESETS[id].bloom); };
  const chooseTab = (id: LabTab) => {
    if (id !== "roles") setRole(null);
    setTab(id);
  };
  const tryOn = (id: PropId) => {
    setTab("single");
    // the single-mode character is created by the tab effect; place the prop once it exists
    setPendingProp(id);
  };
  useEffect(() => {
    if (!pendingProp || !character) return;
    character.place(pendingProp, PROPS[pendingProp].defaultPlacement);
    // oxlint-disable-next-line react/set-state-in-effect
    setPendingProp(null);
  }, [pendingProp, character]);

  return (
    <div className="flex h-dvh min-h-[480px] flex-col overflow-hidden bg-canvas text-fg">
      <header className="flex items-start justify-between gap-4 px-4 pb-2 pt-4 sm:px-6">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold tracking-tight">Openlings — 3D Character Lab</h1>
          <p className="truncate font-sans text-xs text-muted">{animated ? "Animated Openling · clips, expressions, props, roles" : "Base Openling · static lookdev GLB (visual fidelity baseline)"}</p>
        </div>
        {state.phase === "ready" && <AssetFacts state={state} />}
      </header>

      <nav className="flex items-center gap-3 px-4 pb-2 sm:px-6" aria-label="Lab mode">
        <div role="tablist" className="flex items-center rounded-ui border border-line bg-surface p-0.5">
          {TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} disabled={!animated && t.id !== "single"}
              onClick={() => chooseTab(t.id)}
              className={`h-7 rounded-[2px] px-2.5 text-xs leading-none transition-colors disabled:opacity-40 ${tab === t.id ? "bg-fg text-canvas" : "text-muted hover:bg-sunken hover:text-fg"}`}>
              {t.label}
            </button>
          ))}
        </div>
        <ControlGroup label="Model">
          <ToolButton active={animated} onClick={() => setModel("animated")} title="Rigged GLB with clips, morphs and sockets">Animated v01</ToolButton>
          <ToolButton active={!animated} onClick={() => { setModel("static"); setTab("single"); }} title="The approved static lookdev GLB">Static lookdev</ToolButton>
        </ControlGroup>
      </nav>

      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 sm:px-6 md:flex-row">
        <main className="relative min-h-[46dvh] min-w-0 flex-1 md:min-h-0">
          <section className="absolute inset-0 overflow-hidden rounded-ui border border-line bg-sunken">
            <div ref={containerRef} className="absolute inset-0 cursor-grab active:cursor-grabbing" aria-label="Interactive 3D preview of the Openling lab. Drag to orbit, scroll to zoom." role="img" />
            <ViewerOverlay state={state} onRetry={retry} />
          </section>
        </main>
        {animated && (
          <aside aria-label="Lab controls" className="max-h-[42dvh] shrink-0 overflow-y-auto rounded-ui border border-line bg-surface md:max-h-none md:w-[300px]">
            {!stage && <p className="px-3 py-3 text-xs text-muted">Loading the Openling and its props…</p>}
            {stage && tab === "props" && <GallerySection stage={stage} onTryOn={tryOn} />}
            {stage && tab === "multi" && <MultiSection key={stageVersion} stage={stage} onReset={() => { viewer?.setStageMode("multi"); setStageVersion((v) => v + 1); }} />}
            {stage && (tab === "single" || tab === "roles") && character && (
              <CharacterPanels key={stageVersion} character={character} tab={tab} role={role} onRole={setRole} />
            )}
          </aside>
        )}
      </div>

      <footer className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 px-3 pb-4 pt-3 sm:px-6">
        <ControlGroup label="Camera">
          {CAMERA_VIEWS.map((v) => <ToolButton key={v.id} active={view === v.id} onClick={() => chooseView(v.id)}>{v.label}</ToolButton>)}
          <ToolButton onClick={reset} title="Back to the default Front ¾ framing">Reset</ToolButton>
        </ControlGroup>
        <ControlGroup label="Light">
          {(Object.keys(LIGHTING_PRESETS) as LightingPresetId[]).map((id) => (
            <ToolButton key={id} active={lighting === id} onClick={() => chooseLighting(id)}>{LIGHTING_PRESETS[id].label}</ToolButton>
          ))}
        </ControlGroup>
        <ControlGroup label="Render">
          <ToolButton active={bloom} onClick={() => setBloom(!bloom)} title="Glow on the emissive status light">Bloom {bloom ? "on" : "off"}</ToolButton>
          <label className="flex h-7 items-center gap-2 px-2 text-xs text-muted" title="Exposure before tone mapping">
            <span className="hidden sm:inline">Exp</span>
            <input type="range" min={0.6} max={1.6} step={0.05} value={exposure} onChange={(e) => setExposure(Number(e.target.value))} aria-label="Exposure" className="w-20 accent-[var(--fg)]" />
            <span className="w-8 tabular-nums text-fg">{exposure.toFixed(2)}</span>
          </label>
        </ControlGroup>
      </footer>
    </div>
  );
}

function CharacterPanels({ character, tab, role, onRole }: { character: OpenlingCharacter; tab: LabTab; role: RoleId | null; onRole: (id: RoleId) => void }) {
  const s = useCharacterState(character);
  if (!s) return null;
  return (
    <>
      {tab === "roles" && <RolesSection character={character} role={role} onRole={onRole} />}
      <AnimationSection character={character} state={s} />
      <ExpressionSection character={character} state={s} />
      <WardrobeSection character={character} state={s} />
      {tab === "single" && (
        <Section title="Reset">
          <Button size="sm" variant="secondary" onClick={() => { character.clearProps(); character.setExpression("Neutral"); character.setSpeed(1); character.setPaused(false); character.play("Idle", { restart: true }); }}>
            Idle · Neutral · no props
          </Button>
        </Section>
      )}
    </>
  );
}

function ViewerOverlay({ state, onRetry }: { state: ViewerState; onRetry: () => void }) {
  if (state.phase === "ready") return null;
  return (
    <div className="absolute inset-0 flex items-center justify-center p-6">
      <div className="max-w-sm rounded-ui border border-line bg-surface/95 px-4 py-3 text-center text-xs leading-relaxed backdrop-blur-sm" role={state.phase === "loading" ? "status" : "alert"}>
        {state.phase === "loading" && (
          <span className="inline-flex items-center gap-2 text-muted">
            <Spinner />Loading Openling{state.progress !== null ? ` · ${Math.round(state.progress * 100)}%` : "…"}
          </span>
        )}
        {state.phase === "error" && (
          <div className="space-y-2">
            <p className="font-medium text-danger">The Openling model could not be loaded.</p>
            <p className="break-words text-muted">{state.message}</p>
            <Button size="sm" variant="secondary" onClick={onRetry}>Try again</Button>
          </div>
        )}
        {state.phase === "unsupported" && (
          <div className="space-y-1">
            <p className="font-medium text-fg">3D preview unavailable</p>
            <p className="text-muted">{state.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function AssetFacts({ state }: { state: Extract<ViewerState, { phase: "ready" }> }) {
  const s = state.stats;
  const facts = [
    s.bytes ? `GLB ${(s.bytes / 1e6).toFixed(1)} MB` : null,
    `${s.triangles.toLocaleString()} tris`,
    `${s.materials.length} materials`,
    `${s.textures} textures`,
    `${s.drawCalls} draws/frame`,
    `loaded in ${s.loadMs} ms`,
  ].filter(Boolean);
  return <p className="hidden shrink-0 pt-0.5 text-right text-[11px] leading-5 text-faint md:block">{facts.join(" · ")}</p>;
}

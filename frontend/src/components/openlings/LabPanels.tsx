import { useEffect, useState, type ReactNode } from "react";
import { CLIPS, type OpenlingClip } from "../../lib/openlings/animations";
import { EXPRESSIONS, type OpenlingExpression } from "../../lib/openlings/expressions";
import { PROPS, PROP_IDS, type LoadoutChange, type PlacedMode, type PropId } from "../../lib/openlings/props";
import { ROLES, type RoleId } from "../../lib/openlings/roles";
import type { CharacterState, OpenlingCharacter } from "./runtime/OpenlingCharacter";
import type { LabStage } from "./runtime/LabStage";

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="border-b border-line px-3 py-3 last:border-b-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-[10px] font-medium uppercase tracking-[0.08em] text-faint">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** A compact wrap of toggle chips. */
export function Chips({ children, label }: { children: ReactNode; label: string }) {
  return <div role="group" aria-label={label} className="flex flex-wrap gap-1">{children}</div>;
}

export function Chip({ active = false, disabled = false, onClick, children, title }: { active?: boolean; disabled?: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`h-7 rounded-ui border px-2 text-xs leading-none transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${active ? "border-fg bg-fg text-canvas" : "border-line bg-surface text-muted hover:border-line-strong hover:text-fg"}`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- character controls
export function AnimationSection({ character, state }: { character: OpenlingCharacter; state: CharacterState }) {
  return (
    <Section title="Animation">
      <Chips label="Animation">
        {CLIPS.map((c) => (
          <Chip key={c.id} active={!state.restPose && state.clip === c.id} onClick={() => character.play(c.id as OpenlingClip, { restart: !c.loop })}
            title={c.loop ? `${c.label} (loop, ${c.duration}s)` : `${c.label} (one-shot, ${c.duration}s, then back)`}>
            {c.label}
          </Chip>
        ))}
        <Chip active={state.restPose} onClick={() => character.restPose()} title="Bind pose (wide-A), as in the reference renders">Rest pose</Chip>
      </Chips>
      <div className="mt-2 flex items-center gap-2">
        <Chip active={state.paused} onClick={() => character.setPaused(!state.paused)}>{state.paused ? "Play" : "Pause"}</Chip>
        <label className="flex flex-1 items-center gap-2 text-xs text-muted">
          <span>Speed</span>
          <input type="range" min={0.25} max={2} step={0.05} value={state.speed} onChange={(e) => character.setSpeed(Number(e.target.value))} aria-label="Animation speed" className="min-w-0 flex-1 accent-[var(--fg)]" />
          <span className="w-9 tabular-nums text-fg">{state.speed.toFixed(2)}×</span>
        </label>
      </div>
    </Section>
  );
}

export function ExpressionSection({ character, state }: { character: OpenlingCharacter; state: CharacterState }) {
  return (
    <Section title="Expression" aside={<Chip onClick={() => character.blink()} title="Blink once">Blink</Chip>}>
      <Chips label="Expression">
        {EXPRESSIONS.map((e) => (
          <Chip key={e.id} active={state.expression === e.id} onClick={() => character.setExpression(e.id as OpenlingExpression)}>{e.label}</Chip>
        ))}
      </Chips>
      <label className="mt-2 flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={state.autoBlink} onChange={(e) => character.setAutoBlink(e.target.checked)} className="accent-[var(--fg)]" />
        Automatic blink
      </label>
    </Section>
  );
}

const HEAD = PROP_IDS.filter((id) => PROPS[id].category === "head");
const HAND = PROP_IDS.filter((id) => PROPS[id].placements.heldLeft || PROPS[id].placements.heldRight);
const DESK = PROP_IDS.filter((id) => PROPS[id].placements.desk);
const FLOOR = PROP_IDS.filter((id) => PROPS[id].placements.floor);

export function WardrobeSection({ character, state }: { character: OpenlingCharacter; state: CharacterState }) {
  const [note, setNote] = useState<string | null>(null);
  const place = (id: PropId, placement: PlacedMode | "hidden") => {
    const change: LoadoutChange = character.place(id, placement);
    setNote(change.removed.length ? change.removed.map((r) => `${PROPS[r.id].label} off: ${r.reason}.`).join(" ") : null);
  };
  const toggle = (id: PropId, placement: PlacedMode) => place(id, state.loadout[id] === placement ? "hidden" : placement);
  const held = (hand: "heldLeft" | "heldRight") => (Object.entries(state.loadout).find(([, w]) => w === hand)?.[0] ?? "") as PropId | "";
  const handSelect = (hand: "heldLeft" | "heldRight", label: string) => (
    <label className="flex items-center gap-2 text-xs text-muted">
      <span className="w-14 shrink-0">{label}</span>
      <select
        aria-label={`${label} prop`}
        value={held(hand)}
        onChange={(e) => {
          const id = e.target.value as PropId | "";
          if (id) place(id, hand);
          else if (held(hand)) place(held(hand) as PropId, "hidden");
        }}
        className="h-7 min-w-0 flex-1 rounded-ui border border-line bg-surface px-1.5 text-xs text-fg"
      >
        <option value="">Empty</option>
        {HAND.filter((id) => PROPS[id].placements[hand]).map((id) => <option key={id} value={id}>{PROPS[id].label}</option>)}
      </select>
    </label>
  );
  return (
    <Section title="Props" aside={<Chip onClick={() => { character.clearProps(); setNote(null); }}>Clear</Chip>}>
      <p className="mb-1 text-[11px] text-faint">Head</p>
      <Chips label="Worn props">
        {HEAD.map((id) => <Chip key={id} active={state.loadout[id] === "worn"} onClick={() => toggle(id, "worn")} title={PROPS[id].tagline}>{PROPS[id].label}</Chip>)}
      </Chips>
      <div className="mt-2 space-y-1.5">
        {handSelect("heldLeft", "Left hand")}
        {handSelect("heldRight", "Right hand")}
      </div>
      <p className="mb-1 mt-2 text-[11px] text-faint">Desk</p>
      <Chips label="Desk props">
        {DESK.map((id) => <Chip key={id} active={state.loadout[id] === "desk"} onClick={() => toggle(id, "desk")}>{PROPS[id].label}</Chip>)}
      </Chips>
      <p className="mb-1 mt-2 text-[11px] text-faint">Floor</p>
      <Chips label="Floor props">
        {FLOOR.map((id) => <Chip key={id} active={state.loadout[id] === "floor"} onClick={() => toggle(id, "floor")}>{PROPS[id].label}</Chip>)}
      </Chips>
      {note && <p role="status" className="mt-2 rounded-ui bg-sunken px-2 py-1.5 text-[11px] leading-snug text-muted">{note}</p>}
    </Section>
  );
}

// ---------------------------------------------------------------- roles
export function RolesSection({ character, role, onRole }: { character: OpenlingCharacter; role: RoleId | null; onRole: (id: RoleId) => void }) {
  return (
    <Section title="Role presets">
      <div className="grid grid-cols-2 gap-1">
        {ROLES.map((r) => (
          <button key={r.id} type="button" aria-pressed={role === r.id}
            onClick={() => { character.applyRole(r); onRole(r.id); }}
            className={`rounded-ui border px-2 py-1.5 text-left transition-colors ${role === r.id ? "border-fg bg-fg text-canvas" : "border-line bg-surface text-fg hover:border-line-strong"}`}>
            <span className="block text-xs font-medium">{r.label}</span>
            <span className={`block truncate text-[10px] ${role === r.id ? "text-canvas/75" : "text-faint"}`}>{r.props.map((p) => PROPS[p.id].label).join(" · ")}</span>
          </button>
        ))}
      </div>
      {role && <p className="mt-2 text-[11px] leading-snug text-muted">{ROLES.find((r) => r.id === role)!.summary}. Same Openling, rig and clips; only props, clip and expression change.</p>}
    </Section>
  );
}

// ---------------------------------------------------------------- props gallery
export function GallerySection({ stage, onTryOn }: { stage: LabStage; onTryOn: (id: PropId) => void }) {
  const [spin, setSpin] = useState(true);
  useEffect(() => { stage.setGallerySpin(spin); }, [stage, spin]);
  return (
    <Section title={`Props · ${PROP_IDS.length}`} aside={<Chip active={spin} onClick={() => setSpin(!spin)}>Turntable</Chip>}>
      <ol className="space-y-1">
        {PROP_IDS.map((id, i) => (
          <li key={id} className="flex items-center gap-2 text-xs">
            <span className="w-5 shrink-0 tabular-nums text-faint">{i + 1}</span>
            <span className="min-w-0 flex-1 truncate">
              <span className="text-fg">{PROPS[id].label}</span> <span className="text-faint">· {PROPS[id].tagline}</span>
            </span>
            <Chip onClick={() => onTryOn(id)} title={`Put on an Openling (${PROPS[id].defaultPlacement})`}>Try</Chip>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-[11px] text-faint">Numbered left to right, back row first.</p>
    </Section>
  );
}

// ---------------------------------------------------------------- multi-agent
export function MultiSection({ stage, onReset }: { stage: LabStage; onReset: () => void }) {
  const [, setTick] = useState(0);
  const characters = stage.characters;
  useEffect(() => {
    const offs = characters.map((c) => c.onChange(() => setTick((t) => t + 1)));
    return () => offs.forEach((off) => off());
  }, [characters]);
  const clips: OpenlingClip[] = ["Idle", "Walk", "Reporting", "Wave"];
  const faces: OpenlingExpression[] = ["Neutral", "Happy", "Focused", "Worried", "Reporting"];
  return (
    <Section title="Six Openlings">
      <ul className="space-y-1">
        {characters.map((c, i) => {
          const s = c.state;
          const role = ROLES.find((r) => r.id === stage.roleOf(c));
          return (
            <li key={i} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-fg">{role?.label}</span>
              <span className="truncate text-faint">{s.clip} · {s.expression} · {Object.keys(s.loadout).length} props</span>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip onClick={() => stage.characters.forEach((c, i) => setTimeout(() => c.play("Wave", { restart: true }), i * 180))}>Everyone wave</Chip>
        <Chip onClick={() => stage.characters.forEach((c, i) => {
          if (c.state.clip === "Typing") return; // the Coder stays at the desk
          c.play(clips[(i + Math.floor(Math.random() * 4)) % clips.length]);
          c.setExpression(faces[Math.floor(Math.random() * faces.length)]);
        })}>Shuffle</Chip>
        <Chip onClick={onReset}>Reset roles</Chip>
      </div>
      <p className="mt-2 text-[11px] leading-snug text-faint">Each Openling has its own skeleton, mixer, blink schedule and props; geometry, materials and clips are shared.</p>
    </Section>
  );
}

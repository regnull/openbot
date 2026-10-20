import { useState } from "react";
import type { AgentId } from "../../lib/office/agents";
import type { AgentStatus } from "../../lib/office/status";
import { Badge, Button, type BadgeTone } from "../ui";
import type { AgentRow, OfficeSnapshot } from "./OfficeViewer";

const TONE: Record<string, BadgeTone> = { calm: "zinc", active: "blue", warn: "amber", danger: "red", ok: "green", rest: "zinc" };

function statusBadge(row: Pick<AgentRow, "status" | "statusLabel" | "tone">) {
  return <Badge tone={TONE[row.tone] ?? "zinc"} pulse={row.status === "blocked" || row.status === "human_review"}>{row.statusLabel.toLowerCase()}</Badge>;
}

function clock(t: number) {
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

type Filter = "all" | "active" | "attention";
const ACTIVE: AgentStatus[] = ["thinking", "working", "coding", "testing", "reporting"];

/** Compact list of every Openling: name, role, status, where it is. */
export function AgentList({ snapshot, onSelect }: { snapshot: OfficeSnapshot; onSelect: (id: AgentId) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const rows = snapshot.agents.filter((a) => filter === "all" || (filter === "active" ? ACTIVE.includes(a.status) : a.status === "blocked" || a.status === "human_review"));
  return (
    <section className="border-b border-line px-3 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-faint">Agents</h2>
        <div role="group" aria-label="Filter agents" className="flex rounded-ui border border-line p-0.5">
          {(["all", "active", "attention"] as Filter[]).map((f) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
              className={`h-6 rounded-[2px] px-2 text-[11px] ${filter === f ? "bg-fg text-canvas" : "text-muted hover:bg-sunken"}`}>{f}</button>
          ))}
        </div>
      </div>
      <ul className="space-y-0.5">
        {rows.map((a) => (
          <li key={a.id}>
            <button type="button" onClick={() => onSelect(a.id)} aria-current={snapshot.selected === a.id}
              className={`flex w-full items-center gap-2 rounded-ui px-2 py-1.5 text-left transition-colors hover:bg-sunken ${snapshot.selected === a.id ? "bg-sunken" : ""}`}>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium">{a.name} <span className="font-normal text-muted">· {a.role}</span></span>
                <span className="block truncate font-sans text-[11px] text-faint">{a.walking ? "walking · " : ""}{a.zone}</span>
              </span>
              {statusBadge(a)}
            </button>
          </li>
        ))}
        {!rows.length && <li className="px-2 py-2 font-sans text-xs text-muted">No agents match this filter.</li>}
      </ul>
    </section>
  );
}

/** The selected Openling: status, task, progress, zone, recent events, camera follow. */
export function AgentDetails({ row, following, onFocus, onFollow, onClose, chatOpen, onChat }: {
  row: AgentRow; following: boolean; onFocus: () => void; onFollow: () => void; onClose: () => void; chatOpen: boolean; onChat: () => void;
}) {
  return (
    <section className="border-b border-line px-3 py-3" aria-label={`${row.name} details`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold">{row.name}</h2>
          <p className="font-sans text-xs text-muted">{row.role} · {row.zone}</p>
        </div>
        <button type="button" onClick={onClose} className="h-6 rounded-ui px-1.5 text-xs text-muted hover:bg-sunken" aria-label="Close details">✕</button>
      </div>
      <dl className="mt-2 space-y-1.5 font-sans text-xs">
        <div className="flex items-center justify-between gap-2"><dt className="text-faint">Status</dt><dd>{statusBadge(row)}</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-faint">Doing</dt><dd className="truncate text-right">{row.detail}</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-faint">Current task</dt><dd className="truncate text-right">{row.task ?? "—"}</dd></div>
      </dl>
      {row.progress !== null && (
        <div className="mt-2">
          <div className="h-1.5 overflow-hidden rounded-full bg-sunken"><div className="h-full rounded-full bg-info transition-[width] duration-300" style={{ width: `${Math.round(row.progress * 100)}%` }} /></div>
          <p className="mt-1 text-right text-[11px] tabular-nums text-faint">{Math.round(row.progress * 100)}%</p>
        </div>
      )}
      <h3 className="mt-2 text-[11px] font-medium uppercase tracking-[0.08em] text-faint">Recent</h3>
      <ul className="mt-1 space-y-0.5 font-sans text-[11px] text-muted">
        {row.recent.slice(0, 5).map((r, i) => <li key={i} className="flex gap-2"><span className="tabular-nums text-faint">{clock(r.t)}</span><span className="truncate">{r.text}</span></li>)}
        {!row.recent.length && <li>Nothing yet.</li>}
      </ul>
      <div className="mt-2 flex gap-2">
        <Button size="sm" variant="secondary" onClick={onFocus}>Focus</Button>
        <Button size="sm" variant={following ? "primary" : "secondary"} onClick={onFollow}>{following ? "Following" : "Follow"}</Button>
        {!chatOpen && <Button size="sm" variant="secondary" onClick={onChat}>Chat</Button>}
      </div>
    </section>
  );
}

export function EventLog({ snapshot }: { snapshot: OfficeSnapshot }) {
  const names = new Map(snapshot.agents.map((a) => [a.id, a.name]));
  return (
    <section className="px-3 py-3">
      <h2 className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-faint">Event log <span className="normal-case tracking-normal">(simulated)</span></h2>
      <ul className="space-y-0.5 font-sans text-[11px] text-muted">
        {snapshot.log.map((l, i) => (
          <li key={`${l.t}-${i}`} className="flex gap-2">
            <span className="shrink-0 tabular-nums text-faint">{clock(l.t)}</span>
            <span className="min-w-0 truncate">{l.agent ? <span className="text-fg">{names.get(l.agent)}: </span> : null}{l.text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

import { useQuery } from "@tanstack/react-query";
import { createPortal } from "react-dom";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Api } from "../api/client";
import type { CatalogModel } from "../api/types";
import { filterConfiguredProviders, filterModels, formatContext, formatCost, groupModels, modelTasks, sortModels, withSuggested, type ModelSort } from "../lib/modelCatalog";
import { Badge, Button, Input, Spinner } from "./ui";

export interface ModelPickerProps {
  provider: string;
  value: string;
  onChange: (value: string) => void;
  suggested?: string[];
  suggestedLabel?: string;
  id?: string;
  required?: boolean;
  className?: string;
}

const PROVIDER_LABEL: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", openrouter: "OpenRouter", ollama: "Ollama" };
const TASKS = ["All models", "Suggested", "General", "Reasoning", "Code", "Vision", "Embeddings"] as const;
type Task = typeof TASKS[number];

function notConfiguredText(provider: string): string {
  const name = PROVIDER_LABEL[provider] ?? provider;
  return provider === "ollama" ? `${name} is not configured. Set its base URL in Settings.` : `${name} is not configured. Add its API key in Settings.`;
}

const Chip = ({ on, name, onToggle, children }: { on: boolean; name: string; onToggle: () => void; children: ReactNode }) => (
  <button type="button" aria-pressed={on} data-chip={name} onClick={onToggle}
    className={`min-h-9 rounded-ui border px-2 text-xs transition-colors ${on ? "border-accent bg-accent/15 text-fg" : "border-line text-muted hover:border-line-strong hover:bg-sunken hover:text-fg"}`}>
    {children}
  </button>
);

function taskMatches(model: CatalogModel, task: Task, suggested: Set<string>): boolean {
  if (task === "All models") return true;
  if (task === "Suggested") return suggested.has(model.id);
  if (task === "General") return modelTasks(model).includes("General");
  return modelTasks(model).includes(task);
}

function ModelRow({ model, selected, installed, provider, onPick }: { model: CatalogModel; selected: boolean; installed: Set<string> | null; provider: string; onPick: () => void }) {
  const cost = formatCost(model);
  return (
    <button type="button" role="option" aria-selected={selected} onClick={onPick}
      className={`flex min-h-12 w-full flex-col items-start gap-1 border-b border-line px-3 py-2 text-left transition-colors ${selected ? "border-l-4 border-l-accent bg-accent/15 pl-2 text-fg" : "border-l-4 border-l-transparent hover:bg-sunken"}`}>
      <span className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="break-all font-mono text-[13px] font-semibold text-fg">{model.id}</span>
        {model.name !== model.id && <span className="font-sans text-xs text-muted">{model.name}</span>}
        {selected && <span aria-hidden className="ml-auto text-accent">✓</span>}
      </span>
      {(cost || model.context != null || model.reasoning || model.image_input || model.status === "beta" || model.effort_levels.length > 0) && (
        <span className="flex flex-wrap gap-1.5">
          {cost && <span className="font-sans text-[11px] text-muted">{cost}{provider === "ollama" ? " on Ollama Cloud" : ""}</span>}
          {model.reasoning && <Badge>reasoning</Badge>}
          {model.effort_levels.length > 0 && <Badge tone="green">effort: {model.effort_levels.join(", ")}</Badge>}
          {model.image_input && <Badge>vision</Badge>}
          {model.context != null && <Badge>{formatContext(model.context)} context</Badge>}
          {model.status === "beta" && <Badge tone="amber">beta</Badge>}
          {installed && !installed.has(model.id) && <span className="self-center font-sans text-[11px] text-faint">not installed</span>}
        </span>
      )}
      {model.description && <span className="line-clamp-2 break-words text-left font-sans text-xs leading-relaxed text-muted">{model.description}</span>}
    </button>
  );
}

export function ModelPicker({ provider, value, onChange, suggested = [], suggestedLabel = "Suggested", id, required, className = "" }: ModelPickerProps) {
  const models = useQuery({ queryKey: ["models", provider], queryFn: () => Api.getModels(provider), staleTime: 5 * 60_000 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: Api.getProviders, staleTime: 5 * 60_000, enabled: provider === "openrouter" });
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [reasoning, setReasoning] = useState(false);
  const [vision, setVision] = useState(false);
  const [sort, setSort] = useState<ModelSort>("newest");
  const [taskMode, setTaskMode] = useState(provider === "openrouter");
  const [task, setTask] = useState<Task>("All models");
  const [family, setFamily] = useState("All families");
  const [selectedUpstreams, setSelectedUpstreams] = useState<string[]>([]);
  const [seenProvider, setSeenProvider] = useState(provider);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const suppressFocusOpen = useRef(false);
  const titleId = useId();
  const dialogId = useId();
  const listId = useId();
  const suggestedSet = useMemo(() => new Set(suggested), [suggested]);
  const configuredUpstreams = useMemo(() => (providers.data?.providers ?? []).filter((p) => p.configured), [providers.data]);
  const unconfigured = models.data !== undefined && !models.data.configured;

  if (provider !== seenProvider) {
    setSeenProvider(provider);
    setTaskMode(provider === "openrouter");
    setTask("All models");
    setFamily("All families");
    setSelectedUpstreams([]);
  }
  const openPicker = () => {
    setQuery("");
    setOpen(true);
  };
  const close = () => {
    setQuery("");
    setOpen(false);
    suppressFocusOpen.current = true;
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      suppressFocusOpen.current = false;
    });
  };
  useEffect(() => {
    if (!open) { document.body.style.overflow = ""; return; }
    searchRef.current?.focus();
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); close(); } };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); document.body.style.overflow = ""; };
  }, [open]);
  const all = useMemo(() => {
    let result = withSuggested(filterConfiguredProviders(models.data?.models ?? [], providers.data?.providers), suggested);
    if (selectedUpstreams.length) result = result.filter((m) => { const slash = m.id.indexOf("/"); return slash < 0 || selectedUpstreams.includes(m.id.slice(0, slash)); });
    return result;
  }, [models.data, providers.data, suggested, selectedUpstreams]);
  const filtered = useMemo(() => filterModels(all, { text: query, reasoning, vision }), [all, query, reasoning, vision]);
  const visible = useMemo(() => filtered.filter((m) => taskMatches(m, task, suggestedSet)), [filtered, task, suggestedSet]);
  const familyGroups = useMemo(() => groupModels(visible, suggested, suggestedLabel, sort, false), [visible, suggested, suggestedLabel, sort]);
  const groups = useMemo(() => taskMode
    ? (task === "All models" ? groupModels(sortModels(visible, sort), suggested, suggestedLabel, sort, false) : [{ label: task, models: sortModels(visible, sort) }])
    : family === "All families" ? familyGroups : familyGroups.filter((group) => group.label === family), [taskMode, task, family, familyGroups, visible, suggested, suggestedLabel, sort]);
  const flat = useMemo(() => groups.flatMap((g) => g.models), [groups]);
  const known = value === "" || all.some((m) => m.id === value);
  const installed = provider === "ollama" ? suggestedSet : null;
  const counts = useMemo(() => new Map(TASKS.map((name) => [name, filtered.filter((m) => taskMatches(m, name, suggestedSet)).length])), [filtered, suggestedSet]);
  const select = (model: CatalogModel) => { onChange(model.id); close(); };
  const useTyped = () => { if (query.trim()) { onChange(query); close(); } };
  const status = models.isLoading ? "Loading models…" : models.error ? "Models could not be loaded." : unconfigured ? notConfiguredText(provider) : flat.length ? `${flat.length} models available.` : query ? `No models match ${query}.` : "No models available.";

  const dialog = open && createPortal(
    <div id={dialogId} className="fixed inset-0 z-50 flex items-center justify-center bg-overlay p-2 sm:p-4" role="dialog" aria-modal="true" aria-labelledby={titleId} onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <section ref={dialogRef} onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const boundary = dialogRef.current;
        if (!boundary) return;
        const focusable = [...boundary.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex=\"-1\"])")];
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }} className="flex h-[min(720px,calc(100vh-16px))] w-[min(960px,calc(100vw-16px))] max-w-full flex-col overflow-hidden rounded-ui border border-line bg-surface shadow-[0_24px_60px_-20px_rgb(0_0_0/0.65)] sm:h-[min(720px,calc(100vh-32px))] sm:w-[min(960px,calc(100vw-32px))]" data-positioning="viewport-aware">
        <header className="shrink-0 border-b border-line p-4">
          <div className="flex items-start justify-between gap-3"><div><h2 id={titleId} className="text-base font-semibold">Choose a model</h2><p className="mt-1 font-sans text-xs text-muted">Search the catalog or enter a model ID directly.</p></div><button type="button" onClick={close} className="min-h-9 rounded-ui border border-line px-2 text-xs text-muted hover:bg-sunken hover:text-fg">Esc <span aria-hidden>×</span></button></div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row"><Input ref={searchRef} aria-label="Search model IDs, names, or families" placeholder="Search model IDs, names, or families" value={query} onChange={(e) => setQuery(e.target.value)} autoComplete="off" spellCheck={false} className="font-mono" />{provider === "openrouter" && configuredUpstreams.length > 0 && <select aria-label="Configured providers" value={selectedUpstreams.length ? selectedUpstreams.join(",") : ""} onChange={(e) => setSelectedUpstreams(e.target.value ? e.target.value.split(",") : [])} className="h-9 rounded-ui border border-line bg-surface px-2 text-xs"><option value="">All configured providers</option>{configuredUpstreams.map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}</select>}</div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
          <nav aria-label="Browse models" className="scrollbar-subtle shrink-0 overflow-x-auto border-b border-line p-3 sm:w-56 sm:overflow-y-auto sm:border-b-0 sm:border-r"><div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Browse</div><div role="tablist" aria-label="Browse mode" className="mb-3 flex gap-1 sm:flex-col">{[true, false].map((mode) => <button key={String(mode)} type="button" role="tab" aria-selected={taskMode === mode} onClick={() => { setTaskMode(mode); setTask("All models"); setFamily("All families"); }} className={`min-h-10 rounded-ui border px-2 text-left text-xs ${taskMode === mode ? "border-accent bg-accent/15 text-fg" : "border-transparent text-muted hover:bg-sunken hover:text-fg"}`}>{mode ? "By task" : "By family"}</button>)}</div>{taskMode ? <div className="flex gap-1 sm:flex-col">{TASKS.map((name) => <button key={name} type="button" role="tab" aria-selected={task === name} disabled={counts.get(name) === 0} onClick={() => setTask(name)} className={`min-h-10 whitespace-nowrap rounded-ui px-2 text-left text-xs ${task === name ? "bg-sunken font-medium text-fg" : "text-muted hover:bg-sunken hover:text-fg"} disabled:cursor-not-allowed disabled:opacity-50`}>{name}<span className="float-right ml-3 text-faint">{counts.get(name) ?? 0}</span></button>)}</div> : <div className="space-y-1"><button type="button" onClick={() => setFamily("All families")} className={`flex min-h-10 w-full items-center justify-between rounded-ui px-2 text-left text-xs ${family === "All families" ? "bg-sunken font-medium text-fg" : "text-muted hover:bg-sunken hover:text-fg"}`}><span>All families</span><span className="text-faint">{filtered.length}</span></button>{familyGroups.map((group) => <button key={group.label} type="button" onClick={() => setFamily(group.label)} className={`flex min-h-10 w-full items-center justify-between rounded-ui px-2 text-left text-xs ${family === group.label ? "bg-sunken font-medium text-fg" : "text-muted hover:bg-sunken hover:text-fg"}`}><span>{group.label}</span><span className="text-faint">{group.models.length}</span></button>)}</div>}</nav>
          <main className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto" aria-label="Model results"><div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-line bg-surface px-4 py-3"><h3 className="mr-auto text-sm font-semibold">{taskMode ? task : "Models"}</h3><Chip on={reasoning} name="reasoning" onToggle={() => setReasoning((v) => !v)}>Reasoning</Chip><Chip on={vision} name="vision" onToggle={() => setVision((v) => !v)}>Vision</Chip><button type="button" aria-label="Sort models" data-sort={sort} onClick={() => setSort((s) => s === "newest" ? "cheapest" : "newest")} className="min-h-9 rounded-ui border border-line px-2 text-xs text-muted hover:bg-sunken hover:text-fg">{sort === "newest" ? "Newest" : "Cheapest"}</button></div>{models.data?.stale && <div className="border-b border-line bg-sunken px-4 py-2 font-sans text-xs text-warn">Catalog may be out of date. <button type="button" className="underline" onClick={() => models.refetch()}>Refresh</button></div>}<div role="status" aria-live="polite" className="sr-only">{status}</div>{models.isLoading ? <div className="flex items-center gap-2 p-6 font-sans text-sm text-muted"><Spinner /> Loading models…</div> : models.error ? <div role="alert" className="m-4 border border-danger/50 bg-danger/10 p-4 font-sans text-sm text-danger">Models could not be loaded.<div className="mt-3 flex gap-2"><Button size="sm" onClick={() => models.refetch()}>Retry</Button><Button size="sm" variant="secondary" onClick={useTyped} disabled={!query.trim()}>Use entered ID</Button></div></div> : unconfigured ? <div className="m-4 space-y-3 font-sans text-sm text-muted"><p>{notConfiguredText(provider)}</p><Button size="sm" variant="secondary" onClick={useTyped} disabled={!query.trim()}>Use entered ID</Button></div> : flat.length === 0 ? <div className="m-4 space-y-3 font-sans text-sm text-muted"><p>{query ? `No models match “${query}” in this category.` : "No models available in this category."}</p>{query && <Button size="sm" onClick={useTyped}>Use “{query}” directly</Button>}</div> : <div id={listId} role="listbox" aria-label="Models">{groups.map((group) => <section key={group.label}><h4 className="border-b border-line px-4 py-2 font-sans text-xs font-semibold text-muted">{group.label}</h4>{group.models.map((model) => <ModelRow key={model.id} model={model} selected={model.id === value} installed={installed} provider={provider} onPick={() => select(model)} />)}</section>)}</div>}</main>
        </div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3"><p className="font-sans text-xs text-muted">{known ? "Select a model to apply it immediately." : "Type a model ID not listed above to use it directly."}</p><div className="flex gap-2">{!known && query.trim() && <Button size="sm" onClick={useTyped}>Use entered ID</Button>}<Button size="sm" variant="secondary" onClick={close}>Cancel</Button></div></footer>
      </section>
    </div>, document.body);

  return <div className="relative"><Input ref={inputRef} role="combobox" aria-expanded={open} aria-haspopup="dialog" aria-controls={open ? dialogId : undefined} aria-autocomplete="none" autoComplete="off" spellCheck={false} id={id} required={required} value={value} className={`font-mono ${className}`} onFocus={() => { if (!suppressFocusOpen.current) openPicker(); }} onClick={openPicker} onChange={(e) => { onChange(e.target.value); setQuery(e.target.value); setOpen(true); }} onKeyDown={(e) => { if (e.key === "ArrowDown" || e.key === "Enter") { e.preventDefault(); openPicker(); } if (e.key === "Escape" && open) { e.preventDefault(); close(); } }} />{!known && !models.isLoading && !unconfigured && <div className="mt-1 font-sans text-[11px] text-faint">Not in the catalog; sent to the provider as typed.</div>}{dialog}</div>;
}

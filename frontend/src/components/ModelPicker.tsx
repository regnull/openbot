import { useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { Api } from "../api/client";
import type { CatalogModel } from "../api/types";
import { filterModels, formatContext, formatCost, groupModels, withSuggested, type ModelSort } from "../lib/modelCatalog";
import { Badge, Input, Spinner } from "./ui";

export interface ModelPickerProps {
  provider: string;
  value: string;
  onChange: (value: string) => void;
  /** Ids to pin at the top: the server's short suggestion list, or the installed models for Ollama. */
  suggested?: string[];
  suggestedLabel?: string;
  id?: string;
  required?: boolean;
  className?: string;
}

const PROVIDER_LABEL: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", openrouter: "OpenRouter", ollama: "Ollama" };
function notConfiguredText(provider: string): string {
  const name = PROVIDER_LABEL[provider] ?? provider;
  return provider === "ollama" ? `${name} is not configured. Set its base URL in Settings.` : `${name} is not configured. Add its API key in Settings.`;
}

const Chip = ({ on, name, onToggle, children }: { on: boolean; name: string; onToggle: () => void; children: React.ReactNode }) => (
  <button type="button" aria-pressed={on} data-chip={name} onMouseDown={(e) => e.preventDefault()} onClick={onToggle}
    className={`rounded-ui border px-1.5 py-0.5 text-[11px] transition-colors ${on ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:text-fg"}`}>
    {children}
  </button>
);

/** A combobox over the provider's catalog. The text is the value: anything typed is sent as the model id,
 *  whether or not the catalog knows it. Rows are grouped by family; typing filters on id, name and family. */
export function ModelPicker({ provider, value, onChange, suggested = [], suggestedLabel = "Suggested", id, required, className = "" }: ModelPickerProps) {
  const models = useQuery({ queryKey: ["models", provider], queryFn: () => Api.getModels(provider), staleTime: 5 * 60_000 });
  const unconfigured = models.data !== undefined && !models.data.configured;
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const [reasoning, setReasoning] = useState(false);
  const [vision, setVision] = useState(false);
  const [sort, setSort] = useState<ModelSort>("newest");
  const listId = useId();
  const all = useMemo(() => withSuggested(models.data?.models ?? [], suggested), [models.data, suggested]);
  const groups = useMemo(() => groupModels(filterModels(all, { text: value, reasoning, vision }), suggested, suggestedLabel, sort),
    [all, value, reasoning, vision, sort, suggested, suggestedLabel]);
  const flat = useMemo(() => groups.flatMap((g) => g.models), [groups]);
  const highlight = Math.min(sel, Math.max(flat.length - 1, 0));
  const known = value === "" || all.some((m) => m.id === value);
  const installed = provider === "ollama" ? new Set(suggested) : null;
  const pick = (m: CatalogModel) => { onChange(m.id); setOpen(false); };

  return (
    <div className="relative">
      <Input role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list" autoComplete="off" spellCheck={false}
        id={id} required={required} value={value} className={`font-mono ${className}`}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setSel(0); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (!open) { if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); } return; }
          if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
          else if (e.key === "Enter") { if (flat[highlight]) { e.preventDefault(); pick(flat[highlight]); } }
          else if (e.key === "Escape" || e.key === "Tab") { setOpen(false); }
        }} />
      {!known && !models.isLoading && !unconfigured && <div className="mt-1 font-sans text-[11px] text-faint">Not in the catalog; sent to the provider as typed.</div>}
      {open && (
        <div id={listId} role="listbox" aria-label="Models"
          className="absolute left-0 right-0 top-full z-10 mt-1 max-h-80 overflow-y-auto rounded-ui border border-line bg-surface py-1 shadow-[0_12px_32px_-12px_rgb(0_0_0/0.45)]">
          {unconfigured ? (
            <div className="px-3 py-2 font-sans text-[13px] text-muted">{notConfiguredText(provider)}</div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-2 pb-1.5 pt-1 font-sans text-[11px] text-faint">
                <Chip on={reasoning} name="reasoning" onToggle={() => setReasoning((v) => !v)}>Reasoning</Chip>
                <Chip on={vision} name="vision" onToggle={() => setVision((v) => !v)}>Vision</Chip>
                <button type="button" data-sort={sort} onMouseDown={(e) => e.preventDefault()} onClick={() => setSort((s) => (s === "newest" ? "cheapest" : "newest"))}
                  className="ml-auto underline underline-offset-2 hover:text-fg">
                  {sort === "newest" ? "newest first" : "cheapest first"}
                </button>
                {(models.data?.stale ?? false) && <span>Catalog updating…</span>}
              </div>
              {models.isLoading && <div className="px-3 py-2"><Spinner /></div>}
              {!models.isLoading && flat.length === 0 && <div className="px-3 py-2 font-sans text-[13px] text-muted">No matching models.</div>}
              {groups.map((g) => (
                <div key={g.label} data-group={g.label}>
                  <div className="px-3 pb-0.5 pt-2 font-sans text-[11px] font-medium uppercase tracking-wide text-faint">{g.label}</div>
                  {g.models.map((m) => {
                    const i = flat.indexOf(m);
                    const cost = formatCost(m);
                    return (
                      <div key={m.id} role="option" aria-selected={i === highlight} onMouseDown={(e) => { e.preventDefault(); pick(m); }} onMouseEnter={() => setSel(i)}
                        className={`cursor-pointer px-3 py-1.5 ${i === highlight ? "bg-sunken" : ""}`}>
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span className="font-mono text-[13px] text-fg">{m.id}</span>
                          {m.name !== m.id && <span className="font-sans text-xs text-muted">{m.name}</span>}
                          {cost && <span className="font-sans text-xs text-faint">{cost}{provider === "ollama" ? " on Ollama Cloud" : ""}</span>}
                          {installed && !installed.has(m.id) && <span className="font-sans text-xs text-faint">not installed</span>}
                        </div>
                        {(m.reasoning || m.effort_levels.length > 0 || m.image_input || m.context != null || m.status === "beta") && (
                          <div className="mt-0.5 flex flex-wrap gap-x-2">
                            {m.reasoning && <Badge>reasoning</Badge>}
                            {m.effort_levels.length > 0 && <Badge tone="green">effort</Badge>}
                            {m.image_input && <Badge>vision</Badge>}
                            {m.context != null && <Badge>{formatContext(m.context)}</Badge>}
                            {m.status === "beta" && <Badge tone="amber">beta</Badge>}
                          </div>
                        )}
                        {m.description && <div className="mt-0.5 font-sans text-xs text-faint">{m.description}</div>}
                      </div>
                    );
                  })}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

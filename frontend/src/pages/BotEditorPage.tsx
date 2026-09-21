import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Api } from "../api/client";
import type { BotInput } from "../api/types";
import { useSaveMutation } from "../lib/saveNotifications";
import { Button, Card, ErrorText, Field, Hint, Input, PageTitle, SectionTitle, Select, Spinner, Textarea } from "../components/ui";
import { ChevronDownIcon, ChevronRightIcon } from "../components/icons";
import { BOT_ICONS, DEFAULT_BOT_ICON } from "../lib/botIcons";
import { groupState, groupTools, toggleGroup, toolLabel, unavailableGrants } from "../lib/toolGroups";
import { supportsWebSearch } from "../lib/webSearch";

function ToolRow({ name, label, description, on, approval, onToggle, onToggleApproval }:
  { name: string; label: string; description: string; on: boolean; approval: boolean; onToggle: () => void; onToggleApproval: () => void }) {
  return (
    <div className="flex items-start gap-3 py-2">
      <input type="checkbox" className="mt-1" checked={on} onChange={onToggle} aria-label={name} />
      <div className="min-w-0 flex-1">
        <div className="text-[13px]">{label}</div>
        <div className="font-sans text-xs text-muted">{description}</div>
      </div>
      {on && <label className="flex shrink-0 items-center gap-1.5 text-xs text-muted"><input type="checkbox" checked={approval} onChange={onToggleApproval} /> needs approval</label>}
    </div>
  );
}

const Toggle = ({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) => (
  <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /> {children}</label>
);

const empty: BotInput = { handle: "", name: "", description: "", icon: DEFAULT_BOT_ICON, instructions: "", provider: "auto", model: "", model_settings: {},
  tool_names: [], approval_tools: [], memory_enabled: true, enabled: true };

export default function BotEditorPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const isNew = !id;
  const bot = useQuery({ queryKey: ["bot", id], queryFn: () => Api.getBot(id!), enabled: !isNew });
  const tools = useQuery({ queryKey: ["tools"], queryFn: Api.listTools });
  const providers = useQuery({ queryKey: ["providers"], queryFn: Api.getProviders });
  const [form, setForm] = useState<BotInput>(empty);
  useEffect(() => { if (bot.data) { const { id: _i, created_at: _c, updated_at: _u, ...rest } = bot.data; setForm(rest); } }, [bot.data]);

  const save = useSaveMutation({
    mutationFn: () => {
      const payload = { ...form, approval_tools: form.approval_tools.filter((t) => form.tool_names.includes(t)) };
      return isNew ? Api.createBot(payload) : Api.updateBot(id!, payload);
    },
    onSuccess: (b) => { qc.invalidateQueries({ queryKey: ["bots"] }); qc.invalidateQueries({ queryKey: ["bot", b.id] }); nav(`/bots/${b.id}?tab=settings`); },
  }, isNew ? "Bot created" : "Bot settings saved");
  const remove = useMutation({ mutationFn: () => Api.deleteBot(id!), onSuccess: () => { qc.invalidateQueries({ queryKey: ["bots"] }); nav("/bots"); } });

  const set = <K extends keyof BotInput>(k: K, v: BotInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const toggleTool = (name: string) => setForm((f) => {
    const on = f.tool_names.includes(name);
    const tool_names = on ? f.tool_names.filter((t) => t !== name) : [...f.tool_names, name];
    const approval_tools = on ? f.approval_tools.filter((t) => t !== name) : f.approval_tools;
    return { ...f, tool_names, approval_tools };
  });
  const toggleApproval = (name: string) => set("approval_tools", form.approval_tools.includes(name) ? form.approval_tools.filter((t) => t !== name) : [...form.approval_tools, name]);
  const isAuto = form.provider === "auto";
  const auto = providers.data?.providers.find((p) => p.id === "auto");
  const prov = providers.data?.providers.find((p) => p.id === form.provider);
  const grouped = groupTools(tools.data?.tools ?? []);
  const unavailable = unavailableGrants(form.tool_names, tools.data?.tools ?? []);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  if (!isNew && bot.isLoading) return <Spinner />;

  return (
    <form className="mx-auto max-w-3xl space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {isNew && <PageTitle>New bot</PageTitle>}
      <Card className="grid gap-4 sm:grid-cols-2">
        <SectionTitle className="sm:col-span-2">Identity</SectionTitle>
        <Field label="Name"><Input value={form.name} onChange={(e) => set("name", e.target.value)} required /></Field>
        <Field label="Handle" hint="Lowercase letters, digits, _ or -. This is the @handle people and other bots use."><Input value={form.handle} onChange={(e) => set("handle", e.target.value)} pattern="[a-z0-9_\-]{2,32}" required /></Field>
        <div className="sm:col-span-2"><Field label="Description" hint="Shown to other bots so they know when to hand work to this one."><Input value={form.description} onChange={(e) => set("description", e.target.value)} /></Field></div>
        <div className="sm:col-span-2"><Field label="Icon">
          <div className="grid grid-cols-8 gap-1 rounded-ui border border-line bg-canvas p-1.5 sm:grid-cols-10 md:grid-cols-12" role="radiogroup" aria-label="Icon">
            {BOT_ICONS.map((icon) => (
              <button
                key={icon.key}
                type="button"
                role="radio"
                aria-checked={form.icon === icon.key}
                aria-label={icon.label}
                title={icon.label}
                onClick={() => set("icon", icon.key)}
                className={`flex h-9 w-9 items-center justify-center rounded-ui border text-lg transition-colors
                  ${form.icon === icon.key
                    ? "border-accent bg-accent/10"
                    : "border-transparent hover:bg-sunken"}`}
              >
                {icon.glyph}
              </button>
            ))}
          </div>
        </Field></div>
        <div className="sm:col-span-2"><Field label="Instructions" hint="The system prompt. Say what the bot is for, how it should work, and when to hand off."><Textarea rows={12} value={form.instructions} onChange={(e) => set("instructions", e.target.value)} className="font-sans text-[13.5px]" /></Field></div>
        <SectionTitle className="sm:col-span-2">Model</SectionTitle>
        <Field label="Provider" hint="Auto picks whichever provider is configured on the server and keeps working if that changes.">
          <Select value={form.provider} onChange={(e) => {
            const value = e.target.value;
            if (value === "auto") { setForm((f) => ({ ...f, provider: "auto", model: "" })); return; }
            const p = providers.data?.providers.find((x) => x.id === value);
            setForm((f) => ({ ...f, provider: value, model: p?.default_model ?? "" }));
          }}>
            <option value="auto">Auto (recommended){auto?.configured ? "" : " (no provider configured)"}</option>
            {providers.data?.providers.filter((p) => p.id !== "auto").map((p) => <option key={p.id} value={p.id}>{p.id}{p.configured ? "" : " (not configured)"}</option>)}
          </Select>
        </Field>
        {isAuto ? (
          <Field label="Model" hint="Chosen automatically from the configured provider.">
            <Input value={auto?.configured ? `auto (currently ${auto.default_model})` : "auto (no provider configured yet)"} disabled />
          </Field>
        ) : (
          <Field label="Model" hint="Pick from the list or type any model id.">
            <Input list="models" value={form.model} onChange={(e) => set("model", e.target.value)} required />
            <datalist id="models">{prov?.models.map((m) => <option key={m} value={m} />)}</datalist>
          </Field>
        )}
        <div className="space-y-2 sm:col-span-2">
          <Toggle checked={form.memory_enabled} onChange={(v) => set("memory_enabled", v)}>Background memory extraction</Toggle>
          {supportsWebSearch(form.provider, auto?.default_model) && <Toggle checked={form.model_settings.web_search === true} onChange={(v) => set("model_settings", { ...form.model_settings, web_search: v })}>Web search <span className="font-sans text-xs text-muted">(provider-hosted; may incur usage charges)</span></Toggle>}
          <Toggle checked={form.enabled} onChange={(v) => set("enabled", v)}>Enabled</Toggle>
        </div>
      </Card>
      <Card className="space-y-3">
        <SectionTitle>Tools</SectionTitle>
        <Hint className="text-xs">Core tools (ask_human, list_bots, memory, history recall) are always available.</Hint>
        <p className="rounded-ui border border-warn/40 border-l-2 border-l-warn bg-warn/[0.06] px-3 py-2 font-sans text-xs leading-relaxed text-fg"><span className="font-mono text-warn">run_shell</span> is not sandboxed. It runs any command as the server user, with access to the whole filesystem and the server environment, including your provider API keys. Only the file tools are confined to the workspace.</p>
        {tools.data?.errors.map((e) => <p key={e.file} className="text-xs text-danger">{e.file}: {e.error}</p>)}
        <div className="divide-y divide-line">
          {grouped.flat.map((t) => <ToolRow key={t.name} name={t.name} label={t.name} description={t.description} on={form.tool_names.includes(t.name)} approval={form.approval_tools.includes(t.name)} onToggle={() => toggleTool(t.name)} onToggleApproval={() => toggleApproval(t.name)} />)}
        </div>
        {grouped.servers.length > 0 && (
          <>
            <SectionTitle className="pt-2">MCP servers</SectionTitle>
            <Hint className="text-xs">Grant a whole server, or expand it and pick tools. Only connected servers list their tools; grants for a server that is disabled or down are kept and shown below so you can remove them.</Hint>
            <div className="divide-y divide-line">
              {grouped.servers.map((g) => {
                const names = g.tools.map((t) => t.name);
                const state = groupState(names, form.tool_names);
                const expanded = !!openGroups[g.server];
                return (
                  <div key={g.server} className="py-2">
                    <div className="flex items-center gap-3">
                      <input type="checkbox" checked={state === "all"} ref={(el) => { if (el) el.indeterminate = state === "some"; }}
                        onChange={() => setForm((f) => ({ ...f, ...toggleGroup(f, names) }))} aria-label={`All ${g.server} tools`} />
                      <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" aria-expanded={expanded} onClick={() => setOpenGroups((o) => ({ ...o, [g.server]: !expanded }))}>
                        <span className="text-[13px]">{g.server}</span>
                        <span className="text-xs text-muted">{state === "all" ? `all ${names.length}` : state === "some" ? `${names.filter((n) => form.tool_names.includes(n)).length} of ${names.length}` : `${names.length}`} tools</span>
                        <span className="ml-auto text-faint">{expanded ? <ChevronDownIcon className="h-3.5 w-3.5" /> : <ChevronRightIcon className="h-3.5 w-3.5" />}</span>
                      </button>
                    </div>
                    {expanded && <div className="ml-6 divide-y divide-line/60">{g.tools.map((t) => <ToolRow key={t.name} name={t.name} label={toolLabel(g.server, t.name)} description={t.description} on={form.tool_names.includes(t.name)} approval={form.approval_tools.includes(t.name)} onToggle={() => toggleTool(t.name)} onToggleApproval={() => toggleApproval(t.name)} />)}</div>}
                  </div>
                );
              })}
            </div>
          </>
        )}
        {unavailable.length > 0 && (
          <>
            <SectionTitle className="pt-2">Granted but currently unavailable</SectionTitle>
            <Hint className="text-xs">These tools are granted to the bot but their server is not connected right now. They come back when it is; untick to remove the grant.</Hint>
            <div className="divide-y divide-line">
              {unavailable.map((n) => <ToolRow key={n} name={n} label={n} description="not available right now" on approval={form.approval_tools.includes(n)} onToggle={() => toggleTool(n)} onToggleApproval={() => toggleApproval(n)} />)}
            </div>
          </>
        )}
      </Card>
      <ErrorText error={save.error ?? remove.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>{isNew ? "Create bot" : "Save"}</Button>
        <Button type="button" variant="secondary" onClick={() => nav("/bots")}>Cancel</Button>
        {!isNew && <Button type="button" variant="danger" className="ml-auto" onClick={() => confirm("Delete this bot?") && remove.mutate()}>Delete bot</Button>}
      </div>
    </form>
  );
}

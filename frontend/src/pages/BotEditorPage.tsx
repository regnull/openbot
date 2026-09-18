import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Api } from "../api/client";
import type { BotInput } from "../api/types";
import BotIcon from "../components/BotIcon";
import { Button, Card, ErrorText, Field, Input, Select, Spinner, Textarea } from "../components/ui";
import { BOT_ICONS, DEFAULT_BOT_ICON } from "../lib/botIcons";
import { groupState, groupTools, toggleGroup, toolLabel, unavailableGrants } from "../lib/toolGroups";

function ToolRow({ name, label, description, on, approval, onToggle, onToggleApproval }:
  { name: string; label: string; description: string; on: boolean; approval: boolean; onToggle: () => void; onToggleApproval: () => void }) {
  return (
    <div className="flex items-start gap-3 py-2">
      <input type="checkbox" className="mt-1" checked={on} onChange={onToggle} aria-label={name} />
      <div className="min-w-0 flex-1">
        <div className="font-mono text-sm">{label}</div>
        <div className="text-xs text-zinc-500">{description}</div>
      </div>
      {on && <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={approval} onChange={onToggleApproval} /> needs approval</label>}
    </div>
  );
}

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

  const save = useMutation({
    mutationFn: () => {
      const payload = { ...form, approval_tools: form.approval_tools.filter((t) => form.tool_names.includes(t)) };
      return isNew ? Api.createBot(payload) : Api.updateBot(id!, payload);
    },
    onSuccess: (b) => { qc.invalidateQueries({ queryKey: ["bots"] }); qc.invalidateQueries({ queryKey: ["bot", b.id] }); nav(`/bots/${b.id}?tab=settings`); },
  });
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
    <form className="mx-auto max-w-3xl space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {isNew && <h1 className="text-xl font-semibold">New bot</h1>}
      <Card className="grid gap-4 sm:grid-cols-2">
        <Field label="Name"><Input value={form.name} onChange={(e) => set("name", e.target.value)} required /></Field>
        <Field label="Handle" hint="lowercase, digits, _ or -; used as @handle"><Input value={form.handle} onChange={(e) => set("handle", e.target.value)} pattern="[a-z0-9_\-]{2,32}" required /></Field>
        <div className="sm:col-span-2"><Field label="Description" hint="Shown to other bots so they know when to hand work to this one"><Input value={form.description} onChange={(e) => set("description", e.target.value)} /></Field></div>
        <Field label="Icon" hint="Choose from the standard bot icons">
          <div className="flex items-center gap-3">
            <BotIcon icon={form.icon} />
            <Select value={form.icon} onChange={(e) => set("icon", e.target.value)}>
              {BOT_ICONS.map((icon) => <option key={icon.key} value={icon.key}>{icon.glyph} {icon.label}</option>)}
            </Select>
          </div>
        </Field>
        <div className="sm:col-span-2"><Field label="Instructions"><Textarea rows={12} value={form.instructions} onChange={(e) => set("instructions", e.target.value)} /></Field></div>
        <Field label="Provider" hint="Auto picks whichever provider is configured on the server and keeps working if that changes">
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
          <Field label="Model" hint="Chosen automatically from the configured provider">
            <Input value={auto?.configured ? `auto (currently ${auto.default_model})` : "auto (no provider configured yet)"} disabled />
          </Field>
        ) : (
          <Field label="Model" hint="Pick from the list or type any model id">
            <Input list="models" value={form.model} onChange={(e) => set("model", e.target.value)} required />
            <datalist id="models">{prov?.models.map((m) => <option key={m} value={m} />)}</datalist>
          </Field>
        )}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.memory_enabled} onChange={(e) => set("memory_enabled", e.target.checked)} /> Background memory extraction</label>
        {(form.provider === "openai" || form.provider === "anthropic" || form.provider === "openrouter") && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.model_settings.web_search === true} onChange={(e) => set("model_settings", { ...form.model_settings, web_search: e.target.checked })} /> Web search <span className="text-xs text-zinc-500">(provider-hosted; may incur usage charges)</span></label>}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Enabled</label>
      </Card>
      <Card className="space-y-2">
        <h2 className="font-semibold">Tools</h2>
        <p className="text-xs text-zinc-500">Core tools (ask_human, start_thread, list_bots, memory, history recall) are always available.</p>
        <p className="text-xs text-amber-600">Warning: <code>run_shell</code> is not sandboxed. It runs any command as the server user, with access to the whole filesystem and the server environment (including your provider API keys). Only the file tools are confined to the workspace.</p>
        {tools.data?.errors.map((e) => <p key={e.file} className="text-xs text-red-600">{e.file}: {e.error}</p>)}
        <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {grouped.flat.map((t) => <ToolRow key={t.name} name={t.name} label={t.name} description={t.description} on={form.tool_names.includes(t.name)} approval={form.approval_tools.includes(t.name)} onToggle={() => toggleTool(t.name)} onToggleApproval={() => toggleApproval(t.name)} />)}
        </div>
        {grouped.servers.length > 0 && (
          <>
            <h3 className="pt-2 text-sm font-medium">MCP servers</h3>
            <p className="text-xs text-zinc-500">Grant a whole server, or expand it and pick tools. Only connected servers list their tools; grants for a server that is disabled or down are kept and shown below so you can remove them.</p>
            <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {grouped.servers.map((g) => {
                const names = g.tools.map((t) => t.name);
                const state = groupState(names, form.tool_names);
                const expanded = !!openGroups[g.server];
                return (
                  <div key={g.server} className="py-2">
                    <div className="flex items-center gap-3">
                      <input type="checkbox" checked={state === "all"} ref={(el) => { if (el) el.indeterminate = state === "some"; }}
                        onChange={() => setForm((f) => ({ ...f, ...toggleGroup(f, names) }))} aria-label={`All ${g.server} tools`} />
                      <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => setOpenGroups((o) => ({ ...o, [g.server]: !expanded }))}>
                        <span className="font-mono text-sm">{g.server}</span>
                        <span className="text-xs text-zinc-500">{state === "all" ? `all ${names.length}` : state === "some" ? `${names.filter((n) => form.tool_names.includes(n)).length} of ${names.length}` : `${names.length}`} tools</span>
                        <span className="ml-auto text-zinc-500">{expanded ? "▾" : "▸"}</span>
                      </button>
                    </div>
                    {expanded && <div className="ml-6 divide-y divide-zinc-100 dark:divide-zinc-800/60">{g.tools.map((t) => <ToolRow key={t.name} name={t.name} label={toolLabel(g.server, t.name)} description={t.description} on={form.tool_names.includes(t.name)} approval={form.approval_tools.includes(t.name)} onToggle={() => toggleTool(t.name)} onToggleApproval={() => toggleApproval(t.name)} />)}</div>}
                  </div>
                );
              })}
            </div>
          </>
        )}
        {unavailable.length > 0 && (
          <>
            <h3 className="pt-2 text-sm font-medium">Granted but currently unavailable</h3>
            <p className="text-xs text-zinc-500">These tools are granted to the bot but their server is not connected right now. They come back when it is; untick to remove the grant.</p>
            <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {unavailable.map((n) => <ToolRow key={n} name={n} label={n} description="not available right now" on approval={form.approval_tools.includes(n)} onToggle={() => toggleTool(n)} onToggleApproval={() => toggleApproval(n)} />)}
            </div>
          </>
        )}
      </Card>
      <ErrorText error={save.error ?? remove.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>{isNew ? "Create" : "Save"}</Button>
        <Button type="button" variant="secondary" onClick={() => nav("/bots")}>Cancel</Button>
        {!isNew && <Button type="button" variant="danger" className="ml-auto" onClick={() => confirm("Delete this bot?") && remove.mutate()}>Delete</Button>}
      </div>
    </form>
  );
}

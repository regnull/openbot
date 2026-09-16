import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Api } from "../api/client";
import type { BotInput } from "../api/types";
import BotIcon from "../components/BotIcon";
import { Button, Card, ErrorText, Field, Input, Select, Spinner, Textarea } from "../components/ui";
import { BOT_ICONS, DEFAULT_BOT_ICON } from "../lib/botIcons";

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
    onSuccess: (b) => { qc.invalidateQueries({ queryKey: ["bots"] }); nav(`/bots/${b.id}`); },
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
  if (!isNew && bot.isLoading) return <Spinner />;

  return (
    <form className="mx-auto max-w-3xl space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <h1 className="text-xl font-semibold">{isNew ? "New bot" : `Edit @${form.handle}`}</h1>
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
            {providers.data?.providers.filter((p) => p.id !== "auto").map((p) => <option key={p.id} value={p.id}>{p.id}{p.configured ? "" : " (no key)"}</option>)}
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
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Enabled</label>
      </Card>
      <Card className="space-y-2">
        <h2 className="font-semibold">Tools</h2>
        <p className="text-xs text-zinc-500">Core tools (ask_human, start_thread, list_bots, memory, history recall) are always available.</p>
        <p className="text-xs text-amber-600">Warning: <code>run_shell</code> is not sandboxed. It runs any command as the server user, with access to the whole filesystem and the server environment (including your provider API keys). Only the file tools are confined to the workspace.</p>
        {tools.data?.errors.map((e) => <p key={e.file} className="text-xs text-red-600">{e.file}: {e.error}</p>)}
        <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {tools.data?.tools.map((t) => {
            const on = form.tool_names.includes(t.name);
            return (
              <div key={t.name} className="flex items-start gap-3 py-2">
                <input type="checkbox" className="mt-1" checked={on} onChange={() => toggleTool(t.name)} />
                <div className="min-w-0 flex-1"><div className="font-mono text-sm">{t.name}</div><div className="text-xs text-zinc-500">{t.description}</div></div>
                {on && <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={form.approval_tools.includes(t.name)} onChange={() => toggleApproval(t.name)} /> needs approval</label>}
              </div>
            );
          })}
        </div>
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

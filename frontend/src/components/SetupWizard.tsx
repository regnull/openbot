import { useSaveMutation } from "../lib/saveNotifications";
import { useState } from "react";
import { Api } from "../api/client";
import type { SetupStatus } from "../api/types";
import { CHAT_CHOICES, KEY_LABEL, initialWizardState, validateWizard, wizardPayload, type EmbeddingChoice, type WizardState } from "../lib/setup";
import { Button, ErrorText, Hint, Input } from "./ui";

/** One entry in the two-step progress list: the current step is filled with the accent, the rest outlined. */
function Step({ n, current, label }: { n: 1 | 2; current: 1 | 2; label: string }) {
  const active = current === n;
  return (
    <li className={`flex items-center gap-2 ${active ? "text-fg" : "text-faint"}`} aria-current={active ? "step" : undefined}>
      <span className={`inline-flex h-5 w-5 items-center justify-center rounded-ui border text-[11px] ${active ? "border-accent bg-accent text-on-accent" : "border-line text-muted"}`}>{n}</span>
      <span>{label}</span>
    </li>
  );
}

/** First-run setup: shown instead of the app until the minimum configuration is met (a chat provider
 *  and an explicit embeddings choice). Everything it collects is saved through the ordinary settings API. */
export default function SetupWizard({ status, onDone }: { status: SetupStatus; onDone: () => void }) {
  const [state, setState] = useState<WizardState>(initialWizardState);
  const [step, setStep] = useState<1 | 2>(status.chat.ok ? 2 : 1);
  const [touched, setTouched] = useState(false);
  const errors = validateWizard(state);
  const save = useSaveMutation({ mutationFn: () => Api.patchSettings(wizardPayload(state)), onSuccess: onDone }, "Settings saved");
  const set = <K extends keyof WizardState>(k: K, v: WizardState[K]) => setState((s) => ({ ...s, [k]: v }));
  const stepOneOk = state.chat === "ollama" ? !errors.ollamaUrl && !errors.ollamaModel : !errors.apiKey;
  const finish = () => { setTouched(true); if (Object.keys(errors).length === 0) save.mutate(); };
  const choice = (selected: boolean) => `block w-full rounded-ui border p-3 text-left transition-colors ${selected ? "border-accent bg-accent/10" : "border-line hover:border-line-strong hover:bg-sunken/60"}`;
  const fieldError = (msg?: string) => touched && msg ? <p className="text-xs text-danger">{msg}</p> : null;

  return (
    <div className="flex min-h-screen items-start justify-center bg-canvas p-6 sm:items-center">
      <div className="w-full max-w-xl space-y-6 rounded-ui border border-line bg-surface p-7">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <img src="/logo-icon.svg" alt="" className="h-5 w-5 rounded-[4px]" aria-hidden="true" />
            <h1 className="text-base font-semibold tracking-tight">Set up OpenBot</h1>
          </div>
          <Hint>Two choices and your bots can work. Everything here is stored encrypted in OpenBot's database and can be changed later under Settings.</Hint>
        </div>
        <ol className="flex gap-5 text-xs">
          <Step n={1} current={step} label="Chat provider" />
          <Step n={2} current={step} label="Memory search" />
        </ol>

        {step === 1 && (
          <section className="space-y-3">
            <Hint>Which model provider should bots use? Pick one now; more can be added in Settings.</Hint>
            <div className="grid gap-2">
              {CHAT_CHOICES.map((c) => (
                <button key={c.id} type="button" className={choice(state.chat === c.id)} onClick={() => set("chat", c.id)} aria-pressed={state.chat === c.id}>
                  <div className="text-[13px] font-medium">{c.label}</div>
                  <div className="font-sans text-xs text-muted">{c.hint}</div>
                </button>
              ))}
            </div>
            {state.chat === "ollama" ? (
              <div className="space-y-2">
                <Input value={state.ollamaUrl} placeholder="Ollama base URL" onChange={(e) => set("ollamaUrl", e.target.value)} />
                {fieldError(errors.ollamaUrl)}
                <Input value={state.ollamaModel} placeholder="Model, for example llama3.1 or qwen3" onChange={(e) => set("ollamaModel", e.target.value)} />
                {fieldError(errors.ollamaModel)}
                <Hint className="text-xs">The model must already be pulled (<code>ollama pull &lt;model&gt;</code>) and should support tool calling.</Hint>
              </div>
            ) : (
              <div className="space-y-2">
                <Input type="password" value={state.apiKey} placeholder={`${KEY_LABEL[state.chat]} API key`} autoComplete="off" onChange={(e) => set("apiKey", e.target.value)} />
                {fieldError(errors.apiKey)}
                {state.chat === "openrouter" && (
                  <>
                    <Input value={state.botModel} placeholder="Default model, for example z-ai/glm-5.3-flash" onChange={(e) => set("botModel", e.target.value)} />
                    <Hint className="text-xs">The OpenRouter model every bot uses unless it pins its own. Cheap and capable is a good start.</Hint>
                  </>
                )}
              </div>
            )}
            <div className="flex justify-end">
              <Button onClick={() => { setTouched(true); if (stepOneOk) { setTouched(false); setStep(2); } }}>Continue</Button>
            </div>
          </section>
        )}

        {step === 2 && (
          <section className="space-y-3">
            <Hint>Bots remember things between runs. Semantic search over those memories needs an embedding model. You can turn it off; memory then works by recency only.</Hint>
            <div className="grid gap-2">
              {([
                { id: "openrouter", label: "OpenRouter: openai/text-embedding-3-small", hint: "Good quality, low cost, through your OpenRouter key." },
                { id: "openai", label: "OpenAI text-embedding-3-small", hint: "The same model billed to an OpenAI API key." },
                { id: "ollama", label: "Ollama nomic-embed-text (local)", hint: "Runs on this machine; pull the model first." },
                { id: "none", label: "No semantic search", hint: "Skip embeddings for now. Can be enabled later in Settings." },
              ] as { id: EmbeddingChoice; label: string; hint: string }[]).map((c) => (
                <button key={c.id} type="button" className={choice(state.embeddings === c.id)} onClick={() => set("embeddings", c.id)} aria-pressed={state.embeddings === c.id}>
                  <div className="text-[13px] font-medium">{c.label}</div>
                  <div className="font-sans text-xs text-muted">{c.hint}</div>
                </button>
              ))}
            </div>
            {state.embeddings === "openrouter" && state.chat !== "openrouter" && (
              <div className="space-y-1">
                <Input type="password" value={state.openrouterKeyForEmbeddings} placeholder="OpenRouter API key" autoComplete="off" onChange={(e) => set("openrouterKeyForEmbeddings", e.target.value)} />
                {fieldError(errors.openrouterKeyForEmbeddings)}
              </div>
            )}
            {state.embeddings === "openai" && state.chat !== "openai" && (
              <div className="space-y-1">
                <Input type="password" value={state.openaiKeyForEmbeddings} placeholder="OpenAI API key" autoComplete="off" onChange={(e) => set("openaiKeyForEmbeddings", e.target.value)} />
                {fieldError(errors.openaiKeyForEmbeddings)}
              </div>
            )}
            {state.embeddings === "ollama" && (
              <div className="space-y-1">
                {state.chat !== "ollama" && <Input value={state.ollamaUrl} placeholder="Ollama base URL" onChange={(e) => set("ollamaUrl", e.target.value)} />}
                {fieldError(errors.ollamaUrl)}
                <Input value={state.ollamaEmbeddingModel} placeholder="Embedding model" onChange={(e) => set("ollamaEmbeddingModel", e.target.value)} />
              </div>
            )}
            <ErrorText error={save.error} />
            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setStep(1)}>Back</Button>
              <Button onClick={finish} disabled={save.isPending}>{save.isPending ? "Saving…" : "Finish"}</Button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

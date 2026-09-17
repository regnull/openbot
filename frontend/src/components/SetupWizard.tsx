import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Api } from "../api/client";
import type { SetupStatus } from "../api/types";
import { CHAT_CHOICES, KEY_LABEL, initialWizardState, validateWizard, wizardPayload, type EmbeddingChoice, type WizardState } from "../lib/setup";
import { Button, ErrorText, Input } from "./ui";

/** First-run setup: shown instead of the app until the minimum configuration is met (a chat provider
 *  and an explicit embeddings choice). Everything it collects is saved through the ordinary settings API. */
export default function SetupWizard({ status, onDone }: { status: SetupStatus; onDone: () => void }) {
  const [state, setState] = useState<WizardState>(initialWizardState);
  const [step, setStep] = useState<1 | 2>(status.chat.ok ? 2 : 1);
  const [touched, setTouched] = useState(false);
  const errors = validateWizard(state);
  const save = useMutation({ mutationFn: () => Api.patchSettings(wizardPayload(state)), onSuccess: onDone });
  const set = <K extends keyof WizardState>(k: K, v: WizardState[K]) => setState((s) => ({ ...s, [k]: v }));
  const stepOneOk = state.chat === "ollama" ? !errors.ollamaUrl && !errors.ollamaModel : !errors.apiKey;
  const finish = () => { setTouched(true); if (Object.keys(errors).length === 0) save.mutate(); };
  const choice = (selected: boolean) => `block w-full rounded-lg border p-3 text-left ${selected ? "border-zinc-900 bg-zinc-50 dark:border-zinc-100 dark:bg-zinc-800" : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/60"}`;

  return (
    <div className="min-h-screen bg-zinc-50 p-6 dark:bg-zinc-950">
      <div className="mx-auto max-w-xl space-y-6 rounded-xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <div>
          <h1 className="text-xl font-semibold">Set up OpenBot</h1>
          <p className="mt-1 text-sm text-zinc-500">Two choices and your bots can work. Everything here is stored encrypted in OpenBot's database and can be changed later under Settings.</p>
        </div>
        <ol className="flex gap-4 text-xs">
          <li className={step === 1 ? "font-medium" : "text-zinc-500"}>1. Chat provider</li>
          <li className={step === 2 ? "font-medium" : "text-zinc-500"}>2. Memory search</li>
        </ol>

        {step === 1 && (
          <section className="space-y-3">
            <p className="text-sm">Which model provider should bots use? Pick one now; more can be added in Settings.</p>
            <div className="grid gap-2">
              {CHAT_CHOICES.map((c) => (
                <button key={c.id} type="button" className={choice(state.chat === c.id)} onClick={() => set("chat", c.id)}>
                  <div className="text-sm font-medium">{c.label}</div>
                  <div className="text-xs text-zinc-500">{c.hint}</div>
                </button>
              ))}
            </div>
            {state.chat === "ollama" ? (
              <div className="space-y-2">
                <Input value={state.ollamaUrl} placeholder="Ollama base URL" onChange={(e) => set("ollamaUrl", e.target.value)} />
                {touched && errors.ollamaUrl && <p className="text-xs text-red-600">{errors.ollamaUrl}</p>}
                <Input value={state.ollamaModel} placeholder="Model, for example llama3.1 or qwen3" onChange={(e) => set("ollamaModel", e.target.value)} />
                {touched && errors.ollamaModel && <p className="text-xs text-red-600">{errors.ollamaModel}</p>}
                <p className="text-xs text-zinc-500">The model must already be pulled (<code>ollama pull &lt;model&gt;</code>) and should support tool calling.</p>
              </div>
            ) : (
              <div className="space-y-2">
                <Input type="password" value={state.apiKey} placeholder={`${KEY_LABEL[state.chat]} API key`} autoComplete="off" onChange={(e) => set("apiKey", e.target.value)} />
                {touched && errors.apiKey && <p className="text-xs text-red-600">{errors.apiKey}</p>}
                {state.chat === "openrouter" && (
                  <>
                    <Input value={state.botModel} placeholder="Default model, for example z-ai/glm-5.3-flash" onChange={(e) => set("botModel", e.target.value)} />
                    <p className="text-xs text-zinc-500">The OpenRouter model every bot uses unless it pins its own. Cheap and capable is a good start.</p>
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
            <p className="text-sm">Bots remember things between runs. Semantic search over those memories needs an embedding model. You can turn it off; memory then works by recency only.</p>
            <div className="grid gap-2">
              {([
                { id: "openai", label: "OpenAI text-embedding-3-small", hint: "Good quality, low cost. Uses an OpenAI API key." },
                { id: "ollama", label: "Ollama nomic-embed-text (local)", hint: "Runs on this machine; pull the model first." },
                { id: "none", label: "No semantic search", hint: "Skip embeddings for now. Can be enabled later in Settings." },
              ] as { id: EmbeddingChoice; label: string; hint: string }[]).map((c) => (
                <button key={c.id} type="button" className={choice(state.embeddings === c.id)} onClick={() => set("embeddings", c.id)}>
                  <div className="text-sm font-medium">{c.label}</div>
                  <div className="text-xs text-zinc-500">{c.hint}</div>
                </button>
              ))}
            </div>
            {state.embeddings === "openai" && state.chat !== "openai" && (
              <div className="space-y-1">
                <Input type="password" value={state.openaiKeyForEmbeddings} placeholder="OpenAI API key" autoComplete="off" onChange={(e) => set("openaiKeyForEmbeddings", e.target.value)} />
                {touched && errors.openaiKeyForEmbeddings && <p className="text-xs text-red-600">{errors.openaiKeyForEmbeddings}</p>}
              </div>
            )}
            {state.embeddings === "ollama" && (
              <div className="space-y-1">
                {state.chat !== "ollama" && <Input value={state.ollamaUrl} placeholder="Ollama base URL" onChange={(e) => set("ollamaUrl", e.target.value)} />}
                {touched && errors.ollamaUrl && <p className="text-xs text-red-600">{errors.ollamaUrl}</p>}
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

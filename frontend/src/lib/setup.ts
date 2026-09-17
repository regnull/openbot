export type ChatChoice = "openrouter" | "openai" | "anthropic" | "xai" | "ollama";
export type EmbeddingChoice = "openrouter" | "openai" | "ollama" | "none";

export interface WizardState {
  chat: ChatChoice;
  apiKey: string;
  ollamaUrl: string;
  ollamaModel: string;
  botModel: string;
  embeddings: EmbeddingChoice;
  openaiKeyForEmbeddings: string;
  openrouterKeyForEmbeddings: string;
  ollamaEmbeddingModel: string;
}

export const CHAT_CHOICES: { id: ChatChoice; label: string; hint: string }[] = [
  { id: "openrouter", label: "OpenRouter", hint: "One key for most models. The default for bots on the auto provider." },
  { id: "openai", label: "OpenAI", hint: "GPT models; the same key can power embeddings." },
  { id: "anthropic", label: "Anthropic", hint: "Claude models." },
  { id: "xai", label: "xAI", hint: "Grok models." },
  { id: "ollama", label: "Ollama (local)", hint: "A model server on this machine. No key, no cost, needs a capable model." },
];

export const KEY_LABEL: Record<Exclude<ChatChoice, "ollama">, string> = { openrouter: "OpenRouter", openai: "OpenAI", anthropic: "Anthropic", xai: "xAI" };

export const initialWizardState = (): WizardState => ({
  chat: "openrouter", apiKey: "", ollamaUrl: "http://localhost:11434", ollamaModel: "llama3.1", botModel: "z-ai/glm-5.3-flash",
  embeddings: "none", openaiKeyForEmbeddings: "", openrouterKeyForEmbeddings: "", ollamaEmbeddingModel: "nomic-embed-text",
});

export interface WizardErrors { apiKey?: string; ollamaUrl?: string; ollamaModel?: string; openaiKeyForEmbeddings?: string; openrouterKeyForEmbeddings?: string }

export function validateWizard(s: WizardState): WizardErrors {
  const errors: WizardErrors = {};
  if (s.chat === "ollama") {
    if (!s.ollamaUrl.trim()) errors.ollamaUrl = "Enter the Ollama base URL";
    if (!s.ollamaModel.trim()) errors.ollamaModel = "Enter a model name";
  } else if (!s.apiKey.trim()) {
    errors.apiKey = `Paste your ${KEY_LABEL[s.chat]} API key`;
  }
  if (s.embeddings === "openai" && s.chat !== "openai" && !s.openaiKeyForEmbeddings.trim()) {
    errors.openaiKeyForEmbeddings = "OpenAI embeddings need an OpenAI API key";
  }
  if (s.embeddings === "openrouter" && s.chat !== "openrouter" && !s.openrouterKeyForEmbeddings.trim()) {
    errors.openrouterKeyForEmbeddings = "OpenRouter embeddings need an OpenRouter API key";
  }
  if (s.embeddings === "ollama" && s.chat !== "ollama" && !s.ollamaUrl.trim()) {
    errors.ollamaUrl = "Ollama embeddings need the Ollama base URL";
  }
  return errors;
}

/** One PATCH /settings body from the wizard's choices. */
export function wizardPayload(s: WizardState): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (s.chat === "ollama") {
    body.ollama_base_url = s.ollamaUrl.trim();
    body.ollama_model = s.ollamaModel.trim();
  } else {
    body[`${s.chat}_api_key`] = s.apiKey.trim();
    if (s.chat === "openrouter" && s.botModel.trim()) body.bot_model = s.botModel.trim();
  }
  if (s.embeddings === "openrouter") {
    if (s.chat !== "openrouter") body.openrouter_api_key = s.openrouterKeyForEmbeddings.trim();
    body.embedding_model = "openrouter:openai/text-embedding-3-small";
    body.embedding_dims = 1536;
  } else if (s.embeddings === "openai") {
    if (s.chat !== "openai") body.openai_api_key = s.openaiKeyForEmbeddings.trim();
    body.embedding_model = "openai:text-embedding-3-small";
    body.embedding_dims = 1536;
  } else if (s.embeddings === "ollama") {
    if (s.chat !== "ollama") body.ollama_base_url = s.ollamaUrl.trim();
    body.embedding_model = `ollama:${s.ollamaEmbeddingModel.trim()}`;
    body.embedding_dims = 768;
  } else {
    body.embedding_model = "";
  }
  return body;
}

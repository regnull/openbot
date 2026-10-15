import { describe, expect, it } from "vitest";
import { validateWizard, wizardPayload, type WizardState } from "./setup";

const base: WizardState = {
  chat: "openrouter", apiKey: "", ollamaUrl: "http://localhost:11434", ollamaModel: "llama3.1", botModel: "z-ai/glm-5.3-flash",
  embeddings: "none", openaiKeyForEmbeddings: "", openrouterKeyForEmbeddings: "", ollamaEmbeddingModel: "nomic-embed-text",
};

describe("validateWizard", () => {
  it("requires a key for hosted providers, a URL and model for Ollama, and an OpenAI key for OpenAI embeddings", () => {
    expect(validateWizard(base)).toEqual({ apiKey: "Paste your OpenRouter API key" });
    expect(validateWizard({ ...base, apiKey: "sk-or" })).toEqual({});
    expect(validateWizard({ ...base, chat: "ollama", ollamaUrl: "" })).toEqual({ ollamaUrl: "Enter the Ollama base URL" });
    expect(validateWizard({ ...base, chat: "ollama", ollamaModel: " " })).toEqual({ ollamaModel: "Enter a model name" });
    expect(validateWizard({ ...base, apiKey: "sk-or", embeddings: "openai" })).toEqual({ openaiKeyForEmbeddings: "OpenAI embeddings need an OpenAI API key" });
    expect(validateWizard({ ...base, chat: "openai", apiKey: "sk-oa", embeddings: "openai" })).toEqual({});
    expect(validateWizard({ ...base, apiKey: "sk-or", embeddings: "ollama", ollamaUrl: "" })).toEqual({ ollamaUrl: "Ollama embeddings need the Ollama base URL" });
  });

  it("asks for an OpenRouter key for OpenRouter embeddings only when chat does not already provide one", () => {
    expect(validateWizard({ ...base, apiKey: "sk-or", embeddings: "openrouter" })).toEqual({});
    expect(validateWizard({ ...base, chat: "anthropic", apiKey: "sk-ant", embeddings: "openrouter" }))
      .toEqual({ openrouterKeyForEmbeddings: "OpenRouter embeddings need an OpenRouter API key" });
    expect(validateWizard({ ...base, chat: "anthropic", apiKey: "sk-ant", embeddings: "openrouter", openrouterKeyForEmbeddings: "sk-or2" })).toEqual({});
  });
});

describe("wizardPayload", () => {
  it("builds one settings PATCH from the choices", () => {
    expect(wizardPayload({ ...base, apiKey: "sk-or" })).toEqual({ openrouter_api_key: "sk-or", bot_model: "z-ai/glm-5.3-flash", embedding_model: "" });
    expect(wizardPayload({ ...base, chat: "anthropic", apiKey: "sk-ant", embeddings: "openai", openaiKeyForEmbeddings: "sk-oa" }))
      .toEqual({ anthropic_api_key: "sk-ant", openai_api_key: "sk-oa", embedding_model: "openai:text-embedding-3-small", embedding_dims: 1536 });
    expect(wizardPayload({ ...base, chat: "openai", apiKey: "sk-oa", embeddings: "openai" }))
      .toEqual({ openai_api_key: "sk-oa", embedding_model: "openai:text-embedding-3-small", embedding_dims: 1536 });
    expect(wizardPayload({ ...base, chat: "ollama", embeddings: "ollama" }))
      .toEqual({ ollama_base_url: "http://localhost:11434", ollama_model: "llama3.1", embedding_model: "ollama:nomic-embed-text", embedding_dims: 768 });
  });

  it("reuses the OpenRouter chat key for OpenRouter embeddings, or sends the separate one", () => {
    expect(wizardPayload({ ...base, apiKey: "sk-or", embeddings: "openrouter" }))
      .toEqual({ openrouter_api_key: "sk-or", bot_model: "z-ai/glm-5.3-flash", embedding_model: "openrouter:openai/text-embedding-3-small", embedding_dims: 1536 });
    expect(wizardPayload({ ...base, chat: "anthropic", apiKey: "sk-ant", embeddings: "openrouter", openrouterKeyForEmbeddings: "sk-or2" }))
      .toEqual({ anthropic_api_key: "sk-ant", openrouter_api_key: "sk-or2", embedding_model: "openrouter:openai/text-embedding-3-small", embedding_dims: 1536 });
  });
});

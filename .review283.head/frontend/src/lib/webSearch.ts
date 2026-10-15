const HOSTED_SEARCH_PROVIDERS = new Set(["openai", "anthropic", "openrouter"]);

/** Whether the bot editor should offer provider-hosted web search.
 *  For "auto" bots the checkbox follows the provider auto currently resolves to, which the providers
 *  endpoint reports as `default_model` in the form "<provider>/<model>". */
export function supportsWebSearch(provider: string, autoDefaultModel?: string): boolean {
  if (provider === "auto") {
    const resolved = (autoDefaultModel ?? "").split("/")[0];
    return HOSTED_SEARCH_PROVIDERS.has(resolved);
  }
  return HOSTED_SEARCH_PROVIDERS.has(provider);
}

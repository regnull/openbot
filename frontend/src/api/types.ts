export type ActorKind = "bot" | "human" | "external";
export interface Actor { id: string; kind: ActorKind; handle: string; name: string; description: string; enabled: boolean; webhook_url: string | null; created_at: string; updated_at: string; }
export interface Bot { id: string; handle: string; name: string; description: string; icon: string; enabled: boolean; active: boolean; instructions: string; provider: string; model: string; model_settings: Record<string, unknown>; tool_names: string[]; approval_tools: string[]; memory_enabled: boolean; created_at: string; updated_at: string; }
export type BotInput = Omit<Bot, "id" | "created_at" | "updated_at" | "active">;
export interface Participant { actor_id: string; kind: ActorKind; handle: string; name: string; }
export interface Thread { id: string; title: string; kind: "chat" | "direct"; created_by_actor_id: string | null; default_bot_actor_id: string | null; default_bot_handle: string | null; working_directory: string | null; external_ref: string | null; created_at: string; updated_at: string; last_message_at: string | null; participants: Participant[]; }
/** One image attached to a message (mirrors the backend Attachment schema); lives in Message.metadata.attachments. */
export interface MessageAttachment { url: string; name?: string | null; }
export interface Message { id: string; thread_id: string; sender_actor_id: string | null; sender_kind: string; sender_name: string; content: string; mentions: string[]; hop: number; run_id: string | null; metadata: Record<string, unknown>; created_at: string; }
export interface Interrupt { kind: "question" | "approval"; question?: string; actions?: { name: string; args: Record<string, unknown> }[]; }
export interface Run { id: string; actor_id: string; thread_id: string; status: string; interrupt: Interrupt | null; error: string | null; langsmith_run_id: string | null; prompt_tokens?: number | null; completion_tokens?: number | null; cache_read_tokens?: number | null; total_tokens?: number | null; model_calls?: number | null; created_at: string; started_at: string | null; finished_at: string | null; }
export interface RunEvent { id: string; run_id: string; seq: number; type: string; payload: Record<string, any>; created_at: string; }
export interface RunDetail extends Run { events: RunEvent[]; }
/** A bot with queued, unpicked mail in this thread (see the backend WaiterOut schema). */
export interface Waiter { actor_id: string; handle: string | null; name: string | null; position: number; count: number; queue_len: number; }
export interface ThreadDetail extends Thread { messages: Message[]; has_more: boolean; runs: Run[]; waiters?: Waiter[]; }
export interface DirectoryEntry { name: string; path: string; }
export interface DirectoryListing { path: string; parent: string | null; entries: DirectoryEntry[]; }
export interface ThreadUsage { model_calls: number; prompt_tokens: number; completion_tokens: number; cache_read_tokens: number; }
export interface InboxItem { id: string; actor_id: string; thread_id: string; kind: "message" | "question" | "resume"; message_id: string | null; run_id: string | null; payload: Record<string, any>; status: string; attempts: number; last_error: string | null; created_at: string; processed_at: string | null; message: Message | null; }
export interface BotInboxItem extends InboxItem { thread_kind: "chat" | "direct"; run_status: string | null; reply: Message | null; }
export interface BotMemory { key: string; content: string; created_at: string | null; updated_at: string | null; }
/** What POST /bots/{id}/purge did. */
export interface PurgeResult { cancelled_runs: number; purged_items: number; }
export interface ToolInfo { name: string; description: string; source: string; args_schema: Record<string, unknown>; }
export interface ProviderInfo { id: string; configured: boolean; models: string[]; default_model: string; }
export interface ProvidersOut { providers: ProviderInfo[]; embedding_model: string; embeddings_configured: boolean; }
export interface BusEvent { event: string; thread_id: string | null; data: any; }
export interface McpServer { name: string; transport: "stdio" | "http"; status: "connected" | "connecting" | "authorizing" | "needs_auth" | "disconnected" | "error" | "disabled"; enabled: boolean; oauth: boolean; url: string | null; error: string | null; tools: string[]; source: "file" | "db"; authorization_url: string | null; command: string | null; args: string[]; cwd: string | null; env: Record<string, string>; headers: Record<string, string>; }
export interface McpServerInput { name?: string; url?: string | null; headers?: Record<string, string>; command?: string | null; args?: string[]; env?: Record<string, string>; cwd?: string | null; enabled?: boolean; }
export interface McpConnectResult { status: string; authorization_url: string | null; }
export interface SetupStatus { complete: boolean; chat: { ok: boolean; providers: string[] }; embeddings: { ok: boolean; model: string; reason: string | null }; missing: string[]; }
export interface AppSetting { key: string; group: string; label: string; description: string; type: "int" | "float" | "bool" | "str" | "list" | "secret"; value: unknown; default: unknown; overridden: boolean; secret: boolean; is_set: boolean; }

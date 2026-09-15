export type ActorKind = "bot" | "human" | "external";
export interface Actor { id: string; kind: ActorKind; handle: string; name: string; description: string; enabled: boolean; webhook_url: string | null; created_at: string; updated_at: string; }
export interface Bot { id: string; handle: string; name: string; description: string; enabled: boolean; instructions: string; provider: string; model: string; model_settings: Record<string, unknown>; tool_names: string[]; approval_tools: string[]; memory_enabled: boolean; created_at: string; updated_at: string; }
export type BotInput = Omit<Bot, "id" | "created_at" | "updated_at">;
export interface Participant { actor_id: string; kind: ActorKind; handle: string; name: string; }
export interface Thread { id: string; title: string; created_by_actor_id: string | null; default_bot_actor_id: string | null; default_bot_handle: string | null; external_ref: string | null; created_at: string; updated_at: string; last_message_at: string | null; participants: Participant[]; }
export interface Message { id: string; thread_id: string; sender_actor_id: string | null; sender_kind: string; sender_name: string; content: string; mentions: string[]; hop: number; run_id: string | null; metadata: Record<string, unknown>; created_at: string; }
export interface Interrupt { kind: "question" | "approval"; question?: string; actions?: { name: string; args: Record<string, unknown> }[]; }
export interface Run { id: string; actor_id: string; thread_id: string; status: string; interrupt: Interrupt | null; error: string | null; langsmith_run_id: string | null; created_at: string; started_at: string | null; finished_at: string | null; }
export interface RunEvent { id: string; run_id: string; seq: number; type: string; payload: Record<string, any>; created_at: string; }
export interface RunDetail extends Run { events: RunEvent[]; }
export interface ThreadDetail extends Thread { messages: Message[]; has_more: boolean; runs: Run[]; }
export interface InboxItem { id: string; actor_id: string; thread_id: string | null; kind: "message" | "question" | "resume"; message_id: string | null; run_id: string | null; payload: Record<string, any>; status: string; attempts: number; last_error: string | null; created_at: string; processed_at: string | null; message: Message | null; }
export interface ToolInfo { name: string; description: string; source: string; args_schema: Record<string, unknown>; }
export interface ProviderInfo { id: string; configured: boolean; models: string[]; default_model: string; }
export interface ProvidersOut { providers: ProviderInfo[]; embedding_model: string; embeddings_configured: boolean; }
export interface BusEvent { event: string; thread_id: string | null; data: any; }

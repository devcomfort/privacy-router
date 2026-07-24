/** API contracts matching the FastAPI routes under server/api/routes/. */

export interface KeyOut {
	id: string;
	name: string;
	prefix: string;
	is_active: boolean;
	last_used_at: string | null;
	created_at: string;
}

export interface KeyCreated {
	id: string;
	name: string;
	api_key: string;
	message: string;
}

export interface KeyUpdate {
	name?: string;
	is_active?: boolean;
}

export interface BulkKeyToggle {
	ids: string[];
	is_active: boolean;
}

export interface BulkActionResult {
	updated: number;
	ids: string[];
	errors: string[];
}

export interface RuntimeCapabilities {
	mode: 'dev' | 'serve';
	default_model: string;
	model_roles: {
		decision: string;
		local: string;
		external: string;
	};
	model_costs: Record<string, number>;
	demo: {
		authentication: 'session' | 'bearer';
		session_available: boolean;
	};
}


export interface ProviderOut {
	id: string;
	name: string;
	api_base: string | null;
	has_key: boolean;
	source: 'env' | 'none';
	api_key_env: string | null;
}

export interface ProviderListResponse {
	providers: ProviderOut[];
}


export interface ModelOut {
	id: string;
	model_id: string;
	provider_id: string;
	display_name: string | null;
	params: string | null;
	location: 'local' | 'external';
	tier: 'small' | 'middle' | 'large';
	cost_per_1m_tokens: number;
	api_base_override: string | null;
	is_active: boolean;
	created_at: string;
}

export interface ModelCreate {
	model_id: string;
	provider_id: string;
	display_name?: string | null;
	params?: string | null;
	location: 'local' | 'external';
	tier: 'small' | 'middle' | 'large';
	cost_per_1m_tokens: number;
	api_base_override?: string | null;
}

export type ModelUpdate = Partial<Omit<ModelCreate, 'model_id'>>;

export interface ModelValidationResult {
	valid: true;
	model_id: string;
	provider_id: string;
	location: 'local' | 'external';
	tier: 'small' | 'middle' | 'large';
	api_base: string | null;
}

export interface SettingsModel {
	model_id: string;
	display_name: string | null;
	provider_id: string;
	location: 'local' | 'external';
	tier: 'small' | 'middle' | 'large';
	cost_per_1m_tokens: number;
	api_base: string | null;
}

export interface AgentConfig {
	model: string;
	api_base?: string | null;
	temperature?: number;
	max_tokens?: number;
	config?: {
		temperature?: number;
		max_tokens?: number;
	};
}

export interface ProfileSummary {
	description: string;
	decision?: string | null;
	local?: string | null;
	external?: string | null;
}

export interface ProfileListResponse {
	active: string;
	available: Record<string, ProfileSummary>;
}

export interface RouterSettings {
	decision: AgentConfig;
	local: AgentConfig;
	external: AgentConfig;
	models: SettingsModel[];
	profiles: ProfileListResponse;
}

export type SettingsUpdate = Partial<Pick<RouterSettings, 'decision' | 'local' | 'external'>>;

export interface ProfileActivationResult {
	status: string;
	active_profile: string;
	decision: AgentConfig;
	local: AgentConfig;
	external: AgentConfig;
}

export interface PublicModel {
	id: string;
	object: 'model';
	created: number;
	owned_by: string;
}

export interface ModelListResponse {
	object: 'list';
	data: PublicModel[];
}

export interface ModelInvocation {
	id: string;
	component: string;
	model: string;
	provider: string | null;
	prompt_tokens: number;
	completion_tokens: number;
	total_tokens: number;
	cost_usd: number;
	latency_ms: number;
	success: boolean;
	error_type: string | null;
	created_at: string;
}

export interface TelemetryRequest {
	id: string;
	endpoint: string;
	input_redacted: Record<string, unknown>;
	is_sensitive: boolean;
	records_count: number;
	policy_action: string | null;
	route: string | null;
	model_used: string | null;
	latency_ms: number;
	status: string;
	status_code: number;
	created_at: string;
	expires_at: string;
	usage: {
		prompt_tokens: number;
		completion_tokens: number;
		total_tokens: number;
		cost_usd: number;
		model_calls: number;
	};
	invocations: ModelInvocation[];
}

export interface TelemetryExport {
	schema_version: '1.0';
	privacy_level: 'redacted';
	exported_at: string;
	requests: TelemetryRequest[];
}

export interface TelemetryRetention {
	raw_ttl_hours: number;
	automatic_purge_interval_seconds: number;
	export_privacy_level: 'redacted';
	encrypted_payloads_exported: false;
}

export interface TelemetryPurgeResult {
	scope: 'expired' | 'before' | 'all';
	deleted: {
		request_traces: number;
		model_invocations: number;
	};
}

export interface ChatMessage {
	role: 'user' | 'assistant' | 'system';
	content: string;
}

export interface ChatCompletionRequest {
	model: string;
	messages: ChatMessage[];
}

export interface PipelineRecord {
	index?: number;
	category: string;
	span: string;
	confidence: number;
	is_essential?: boolean;
	reasoning?: string;
}

export interface MaskingPlaceholder {
	uid: string;
	category: string;
	confidence: number;
	is_essential: boolean;
}

export interface PrivacyRouterMeta {
	is_sensitive: boolean;
	extraction_records: PipelineRecord[];
	policy_action: string;
	route: string;
	model_used: string;
	masked_text?: string;
	masking_session_id?: string;
	placeholder_map?: MaskingPlaceholder[];
}

export interface ChatCompletionResponse {
	id: string;
	object: string;
	created: number;
	model: string;
	choices: {
		index: number;
		message: ChatMessage;
		finish_reason: string;
	}[];
	usage: {
		prompt_tokens: number;
		completion_tokens: number;
		total_tokens: number;
	};
	privacy_router?: PrivacyRouterMeta;
}

export interface ClassifyRequest {
	text: string;
}

export interface ClassifyResponse {
	is_sensitive: boolean;
	records: PipelineRecord[];
	policy_action: string;
	route: {
		endpoint: string;
		requires_masking: boolean;
		description: string;
	};
	decision?: string;
}

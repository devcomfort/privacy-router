<script lang="ts">
	import { onMount, tick } from 'svelte';
	import type { ChatMessage, PrivacyRouterMeta } from '$lib/types';
	import { ApiError, chat, demoAuth, models as modelsApi, runtime as runtimeApi } from '$lib/api';
	import { Button, Checkbox, Input, LangToggle, Select } from '$lib/components/ui';
	import { ChatBubble, ChatInput } from '$lib/components/chat';
	import { t } from '$lib/i18n';

	interface ChatEntry {
		message: ChatMessage;
		meta: PrivacyRouterMeta | null;
	}

	interface DemoError {
		key: string;
		status?: number;
	}

	type RequestPhase = 'analyzing' | 'processing' | 'generating' | 'verifying';


	const categoryKeys: Record<string, string> = {
		ACQUISITION_TARGET: 'demo.category.acquisition_target',
		API_CREDENTIAL: 'demo.category.api_credential',
		COMPETITIVE_LEAD_TIME: 'demo.category.competitive_lead_time',
		COMPETITOR_NAME: 'demo.category.competitor_name',
		EMAIL_ADDRESS: 'demo.category.email_address',
		FABRICATION_PROCESS_DECISION: 'demo.category.fabrication_process_decision',
		INSTITUTION_NAME: 'demo.category.institution_name',
		INTERNAL_COST_DISCOUNT: 'demo.category.internal_cost_discount',
		INTERNAL_PROJECT_NAME: 'demo.category.internal_project_name',
		INTERNAL_STRATEGY_RATIONALE: 'demo.category.internal_strategy_rationale',
		INTERNAL_URL: 'demo.category.internal_url',
		MEDICAL_DIAGNOSIS: 'demo.category.medical_diagnosis',
		PATENT_FILING_TIMELINE: 'demo.category.patent_filing_timeline',
		PERSON_NAME: 'demo.category.person_name',
		PERSONAL_IDENTIFIER_NUMBER: 'demo.category.personal_identifier_number',
		PROJECT_BUDGET_AMOUNT: 'demo.category.project_budget_amount',
		PROJECT_LABOR_BUDGET_AMOUNT: 'demo.category.project_labor_budget_amount',
		RESIDENT_REGISTRATION_NUMBER: 'demo.category.resident_registration_number',
		SALARY_INFORMATION: 'demo.category.salary_information',
		SENSITIVE_DATA: 'demo.category.sensitive_data',
		SUPPLIER_SELECTION_DECISION: 'demo.category.supplier_selection_decision',
		UNPUBLISHED_BENCHMARK_RESULT: 'demo.category.unpublished_benchmark_result',
		UNPUBLISHED_RESEARCH_CONCEPT: 'demo.category.unpublished_research_concept',
		UNPUBLISHED_RESEARCH_METHODOLOGY: 'demo.category.unpublished_research_methodology'
	};
	const defaultModel = { value: 'privacy-router', label: 'Privacy Router' };

	let messages = $state<ChatEntry[]>([]);
	let loading = $state(false);
	let rerunning = $state(false);
	let apiKey = $state('');
	let selectedModel = $state(defaultModel.value);
	let models = $state([defaultModel]);
	let modelLoading = $state(true);
	let modelLoadFailed = $state(false);
	let keylessDemo = $state(false);
	let keylessDemoModel = $state<string | null>(null);
	let runtimeLoading = $state(true);
	let requestError = $state<DemoError | null>(null);
	let lastRequest = $state<ChatMessage[] | null>(null);
	let lastResponseIndex = $state<number | null>(null);
	let conversationViewport = $state<HTMLDivElement | null>(null);
	let streaming = $state(true);
	let requestPhase = $state<RequestPhase | null>(null);
	let streamStarted = $state(false);

	let latestMeta = $derived(
		lastResponseIndex === null ? null : (messages[lastResponseIndex]?.meta ?? null)
	);

	$effect(() => {
		messages.length;
		messages.at(-1)?.message.content;
		loading;
		requestError;
		void tick().then(() => {
			conversationViewport?.scrollTo({
				top: conversationViewport.scrollHeight,
				behavior: 'smooth'
			});
		});
	});

	onMount(() => {
		void initializeDemo();
	});

	async function initializeDemo() {
		try {
			const capabilities = await runtimeApi.get();
			if (capabilities.demo.session_available) {
				keylessDemoModel = capabilities.default_model;
				selectedModel = capabilities.default_model;
				await demoAuth.create();
				keylessDemo = true;
			}
		} catch {
			keylessDemo = false;
			keylessDemoModel = null;
		} finally {
			runtimeLoading = false;
			void loadModels();
		}
	}

	function modelOption(modelId: string) {
		return {
			value: modelId,
			label: modelId === 'privacy-router'
				? 'Privacy Router'
				: modelId.replace(/^privacy-router\//, '')
		};
	}

	async function loadModels() {
		modelLoading = true;
		modelLoadFailed = false;
		try {
			const response = await modelsApi.list();
			const visibleModels = keylessDemoModel
				? response.data.filter((model) => model.id === keylessDemoModel)
				: response.data;
			const seen = new Set<string>();
			const nextModels = visibleModels
				.filter((model) => {
					if (seen.has(model.id)) return false;
					seen.add(model.id);
					return true;
				})
				.map((model) => modelOption(model.id));
			const fallbackModel = keylessDemoModel
				? modelOption(keylessDemoModel)
				: defaultModel;
			models = nextModels.length > 0 ? nextModels : [fallbackModel];
			if (!models.some((model) => model.value === selectedModel)) {
				selectedModel = models[0].value;
			}
		} catch {
			modelLoadFailed = true;
			const fallbackModel = keylessDemoModel
				? modelOption(keylessDemoModel)
				: defaultModel;
			models = [fallbackModel];
			selectedModel = fallbackModel.value;
		} finally {
			modelLoading = false;
		}
	}

	function normalizeError(error: unknown): DemoError {
		if (error instanceof ApiError) {
			if (error.status === 401 || error.status === 403) {
				return { key: 'demo.error.auth', status: error.status };
			}
			if (error.status === 400 || error.status === 422) {
				return { key: 'demo.error.request', status: error.status };
			}
			return { key: 'demo.error.service', status: error.status };
		}
		return { key: 'demo.error.network' };
	}

	function phaseKey(): string {
		if (requestPhase === 'analyzing') return 'demo.phase.analyzing';
		if (requestPhase === 'generating') return 'demo.phase.generating';
		if (requestPhase === 'verifying') return 'demo.phase.verifying';
		return 'demo.phase.processing';
	}

	function requiresBufferedRelease(meta: PrivacyRouterMeta): boolean {
		return meta.route === 'local_api' || meta.policy_action === 'selective_mask';
	}

	async function runRequest(requestMessages: ChatMessage[], replaceIndex: number | null = null) {
		if (loading) return;
		const requestedModel = selectedModel;
		const requestedApiKey = keylessDemo ? undefined : (apiKey || undefined);
		const requestedStreaming = streaming;
		lastRequest = requestMessages.map((message) => ({ ...message }));
		requestError = null;
		loading = true;
		rerunning = replaceIndex !== null;
		requestPhase = requestedStreaming ? 'analyzing' : 'processing';
		streamStarted = false;

		let streamIndex: number | null = null;
		let previousEntry: ChatEntry | null = null;

		try {
			if (requestedStreaming) {
				const pendingEntry: ChatEntry = {
					message: { role: 'assistant', content: '' },
					meta: null
				};
				if (replaceIndex !== null && messages[replaceIndex]?.message.role === 'assistant') {
					streamIndex = replaceIndex;
					previousEntry = messages[replaceIndex] ?? null;
					messages = messages.map((entry, index) => index === replaceIndex ? pendingEntry : entry);
				} else {
					messages = [...messages, pendingEntry];
					streamIndex = messages.length - 1;
				}
				lastResponseIndex = streamIndex;

				await chat.completionsStream(
					{ model: requestedModel, messages: requestMessages },
					requestedApiKey,
					{
						onMeta: (meta) => {
							if (streamIndex === null) return;
							requestPhase = requiresBufferedRelease(meta) ? 'verifying' : 'generating';
							messages = messages.map((entry, index) =>
								index === streamIndex ? { ...entry, meta } : entry
							);
						},
						onContent: (content) => {
							if (streamIndex === null) return;
							streamStarted = true;
							messages = messages.map((entry, index) =>
								index === streamIndex
									? {
										...entry,
										message: {
											...entry.message,
											content: `${entry.message.content}${content}`
										}
									}
									: entry
							);
						}
					}
				);
				return;
			}

			const data = await chat.completions(
				{ model: requestedModel, messages: requestMessages },
				requestedApiKey
			);
			const assistantMessage = data.choices?.[0]?.message;
			if (!assistantMessage) throw new Error('Missing assistant message');

			const entry: ChatEntry = {
				message: assistantMessage,
				meta: data.privacy_router ?? null
			};
			if (replaceIndex !== null && messages[replaceIndex]?.message.role === 'assistant') {
				messages = messages.map((message, index) => index === replaceIndex ? entry : message);
				lastResponseIndex = replaceIndex;
			} else {
				messages = [...messages, entry];
				lastResponseIndex = messages.length - 1;
			}
		} catch (error) {
			if (requestedStreaming && streamIndex !== null) {
				if (replaceIndex !== null && previousEntry) {
					messages = messages.map((entry, index) =>
						index === replaceIndex ? previousEntry as ChatEntry : entry
					);
					lastResponseIndex = replaceIndex;
				} else {
					messages = messages.filter((_, index) => index !== streamIndex);
					lastResponseIndex = null;
				}
			}
			requestError = normalizeError(error);
		} finally {
			loading = false;
			rerunning = false;
			requestPhase = null;
			streamStarted = false;
		}
	}

	async function handleSend(text: string) {
		const userMessage: ChatMessage = { role: 'user', content: text };
		const requestMessages = [...messages.map((entry) => entry.message), userMessage];
		messages = [...messages, { message: userMessage, meta: null }];
		lastResponseIndex = null;
		await runRequest(requestMessages);
	}

	async function handleRerun() {
		if (!lastRequest) return;
		await runRequest(lastRequest, lastResponseIndex);
		await tick();
		document.getElementById('demo-message')?.focus();
	}

	function categoryLabel(category: string): string {
		const translationKey = categoryKeys[category];
		return translationKey ? $t(translationKey) : category.replaceAll('_', ' ').toLowerCase();
	}

	function decisionKey(meta: PrivacyRouterMeta): string {
		if (!meta.is_sensitive) return 'demo.decision.safe';
		if (meta.route === 'local_api') return 'demo.decision.local';
		if (meta.policy_action === 'selective_mask') return 'demo.decision.masked';
		if (meta.policy_action === 'block') return 'demo.decision.blocked';
		return 'demo.decision.external';
	}

	function policyKey(action: string): string {
		if (action === 'selective_mask') return 'demo.policy.masked';
		if (action === 'block') return 'demo.policy.blocked';
		return 'demo.policy.allowed';
	}
</script>

<svelte:head>
	<title>{$t('demo.title')} — Privacy Router</title>
</svelte:head>

<div class="min-h-dvh bg-slate-950 text-slate-200">
	<header class="border-b border-slate-800/80 bg-slate-950/95 px-4 py-4 sm:px-6">
		<div class="mx-auto flex max-w-6xl items-center justify-between gap-4">
			<a
				href="/"
				class="rounded-md text-sm text-slate-400 transition hover:text-white focus:outline-none focus:ring-2 focus:ring-blue-500/60"
			>
				{$t('nav.back')}
			</a>
			<div class="flex items-center gap-3">
				<span class="hidden text-xs font-medium uppercase tracking-[0.18em] text-slate-400 sm:inline">
					{$t('demo.header.eyebrow')}
				</span>
				<LangToggle />
			</div>
		</div>
	</header>

	<main class="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-10">
		<div class="mb-7 max-w-3xl">
			<p class="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">
				{$t('demo.header.eyebrow')}
			</p>
			<h1 class="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
				{$t('demo.title')}
			</h1>
			<p class="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
				{$t('demo.description')}
			</p>
		</div>

		<section
			class="mb-6 rounded-2xl border border-slate-800 bg-slate-900/55 p-4 shadow-xl shadow-black/10 sm:p-5"
			aria-labelledby="request-settings-title"
		>
			<div class="mb-4 flex flex-wrap items-start justify-between gap-3">
				<div>
					<h2 id="request-settings-title" class="text-sm font-semibold text-white">
						{$t('demo.settings.title')}
					</h2>
					<p class="mt-1 text-xs leading-5 text-slate-400">
						{$t(keylessDemo ? 'demo.settings.dev_description' : 'demo.settings.description')}
					</p>
				</div>
				{#if lastRequest}
					<Button
						variant="secondary"
						size="sm"
						onclick={handleRerun}
						disabled={loading || !selectedModel}
					>
						{rerunning ? $t('demo.rerunning') : $t('demo.rerun')}
					</Button>
				{/if}
			</div>

			<div class="grid gap-4 sm:grid-cols-2">
				<div class="space-y-2">
					<Select
						id="demo-model"
						bind:value={selectedModel}
						options={models}
						label={$t(keylessDemo ? 'demo.model.local_label' : 'demo.model.label')}
						disabled={loading || modelLoading}
					/>
					<p class="text-xs text-slate-400">
						{modelLoading
							? $t('demo.model.loading')
							: $t(keylessDemo ? 'demo.model.local_hint' : 'demo.model.hint')}
					</p>
					{#if modelLoadFailed}
						<div class="flex items-start gap-2 text-xs" role="alert">
							<span class="text-amber-300">{$t('demo.model.error')}</span>
							<button
								type="button"
								class="shrink-0 rounded text-blue-300 underline decoration-blue-400/40 underline-offset-2 hover:text-blue-200 focus:outline-none focus:ring-2 focus:ring-blue-500/60"
								onclick={loadModels}
							>
								{$t('demo.retry')}
							</button>
						</div>
					{/if}
				</div>
				<div class="space-y-4">
					{#if keylessDemo}
						<div class="rounded-lg border border-emerald-400/20 bg-emerald-400/10 px-3 py-2.5 text-sm text-emerald-200" role="status">
							{$t('demo.apikey.dev_session')}
						</div>
					{:else}
						<Input
							id="demo-api-key"
							bind:value={apiKey}
							label={$t('demo.apikey.label')}
							placeholder={$t('demo.apikey.placeholder')}
							type="password"
							autocomplete="off"
							disabled={loading || runtimeLoading}
						/>
					{/if}
					<div class="space-y-1.5">
						<Checkbox
							bind:checked={streaming}
							label={$t('demo.streaming.label')}
							disabled={loading}
						/>
						<p class="text-xs leading-5 text-slate-400">{$t('demo.streaming.hint')}</p>
					</div>
				</div>
			</div>
		</section>

		<div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(19rem,0.75fr)]">
			<section
				class="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/45 shadow-xl shadow-black/10"
				aria-labelledby="conversation-title"
				aria-busy={loading}
			>
				<div class="flex items-center justify-between border-b border-slate-800 px-4 py-3 sm:px-5">
					<div>
						<h2 id="conversation-title" class="text-sm font-semibold text-white">
							{$t('demo.conversation.title')}
						</h2>
						<p class="mt-0.5 text-xs text-slate-400">{$t('demo.conversation.description')}</p>
					</div>
					<span class="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400">
						{$t('demo.conversation.protected')}
					</span>
				</div>

				<div
					bind:this={conversationViewport}
					class="h-[45dvh] min-h-64 max-h-[32rem] overflow-y-auto px-4 py-5 sm:h-[50dvh] sm:min-h-[25rem] sm:px-5"
					aria-live="polite"
				>
					<div class="space-y-5">
						{#if messages.length === 0}
							<div class="mx-auto max-w-sm py-20 text-center">
								<div class="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-slate-700 bg-slate-900 text-sm font-semibold text-blue-300">
									PR
								</div>
								<p class="text-sm font-medium text-slate-300">{$t('demo.empty')}</p>
								<p class="mt-2 text-xs leading-5 text-slate-400">{$t('demo.empty.hint')}</p>
							</div>
						{/if}

						{#each messages as entry, index (index)}
							{#if entry.message.role !== 'assistant' || entry.message.content}
								<ChatBubble message={entry.message} meta={entry.meta} />
							{/if}
						{/each}

						{#if loading && !streamStarted}
							<div class="flex gap-3" role="status">
								<div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-semibold text-slate-300" aria-hidden="true">
									A
								</div>
								<div class="flex items-center gap-3 rounded-2xl bg-slate-800 px-4 py-3">
									<div class="flex gap-1.5" aria-hidden="true">
										<span class="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400"></span>
										<span class="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400 [animation-delay:150ms]"></span>
										<span class="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400 [animation-delay:300ms]"></span>
									</div>
									<span class="text-xs text-slate-300">{$t(phaseKey())}</span>
								</div>
							</div>
						{/if}

						{#if requestError}
							<div class="rounded-xl border border-red-400/25 bg-red-400/10 p-3" role="alert">
								<p class="text-sm font-medium text-red-200">
									{$t(requestError.key)}
									{#if requestError.status}
										<span class="font-normal text-red-300/70">({requestError.status})</span>
									{/if}
								</p>
								<div class="mt-2 flex items-center gap-3">
									{#if lastRequest}
										<button
											type="button"
											class="rounded text-xs font-medium text-red-100 underline decoration-red-300/40 underline-offset-2 hover:text-white focus:outline-none focus:ring-2 focus:ring-red-400/60"
											onclick={handleRerun}
											disabled={loading}
										>
											{$t('demo.retry')}
										</button>
									{/if}
									<span class="text-xs text-red-300/70">{$t('demo.error.no_sensitive_data')}</span>
								</div>
							</div>
						{/if}
					</div>
				</div>

				<div class="border-t border-slate-800 bg-slate-950/35 p-4 sm:p-5">
					<ChatInput onsend={handleSend} disabled={loading || !selectedModel} />
				</div>
			</section>

			<aside
				class="rounded-2xl border border-slate-800 bg-slate-900/55 shadow-xl shadow-black/10 lg:sticky lg:top-6"
				aria-labelledby="decision-title"
			>
				<div class="border-b border-slate-800 px-4 py-3 sm:px-5">
					<p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
						{$t('demo.decision.eyebrow')}
					</p>
					<h2 id="decision-title" class="mt-1 text-sm font-semibold text-white">
						{$t('demo.decision.title')}
					</h2>
				</div>

				{#if latestMeta}
					<div class="space-y-5 p-4 sm:p-5">
						<div
							class={`rounded-xl border p-3 ${
								latestMeta.is_sensitive
									? 'border-amber-400/25 bg-amber-400/10'
									: 'border-emerald-400/20 bg-emerald-400/10'
							}`}
						>
							<p
								class="text-sm font-semibold"
								class:text-amber-200={latestMeta.is_sensitive}
								class:text-emerald-200={!latestMeta.is_sensitive}
							>
								{latestMeta.is_sensitive ? $t('demo.meta.sensitive') : $t('demo.meta.safe')}
							</p>
							<p class="mt-1 text-xs leading-5 text-slate-300">
								{$t(decisionKey(latestMeta))}
							</p>
						</div>

						<dl class="grid gap-3">
							<div class="rounded-xl border border-slate-800 bg-slate-950/35 p-3">
								<dt class="text-[11px] uppercase tracking-wide text-slate-400">{$t('demo.meta.model')}</dt>
								<dd class="mt-1 break-all text-sm font-medium text-slate-200">{latestMeta.model_used}</dd>
							</div>
							<div class="grid grid-cols-2 gap-3">
								<div class="rounded-xl border border-slate-800 bg-slate-950/35 p-3">
									<dt class="text-[11px] uppercase tracking-wide text-slate-400">{$t('demo.meta.route')}</dt>
									<dd class="mt-1 text-sm font-medium text-slate-200">
										{latestMeta.route === 'local_api' ? $t('demo.meta.route.local') : $t('demo.meta.route.external')}
									</dd>
								</div>
								<div class="rounded-xl border border-slate-800 bg-slate-950/35 p-3">
									<dt class="text-[11px] uppercase tracking-wide text-slate-400">{$t('demo.meta.action')}</dt>
									<dd class="mt-1 text-sm font-medium text-slate-200">{$t(policyKey(latestMeta.policy_action))}</dd>
								</div>
							</div>
						</dl>

						<div>
							<div class="mb-3 flex items-center justify-between gap-3">
								<h3 class="text-sm font-semibold text-white">{$t('demo.evidence.title')}</h3>
								<span class="text-xs tabular-nums text-slate-400">
									{latestMeta.extraction_records.length}
								</span>
							</div>
							{#if latestMeta.extraction_records.length > 0}
								<ul class="space-y-2">
									{#each latestMeta.extraction_records as record}
										<li class="rounded-xl border border-slate-800 bg-slate-950/35 p-3">
											<div class="flex items-start justify-between gap-3">
												<p class="min-w-0 break-all font-mono text-xs font-semibold text-slate-200">
													{categoryLabel(record.category)}
												</p>
												<span class="shrink-0 text-xs tabular-nums text-slate-400">
													{Math.round(record.confidence * 100)}%
												</span>
											</div>
											<div
												class="mt-2 h-1 overflow-hidden rounded-full bg-slate-800"
												role="progressbar"
												aria-label={`${categoryLabel(record.category)} ${$t('demo.evidence.confidence')}`}
												aria-valuemin="0"
												aria-valuemax="100"
												aria-valuenow={Math.round(record.confidence * 100)}
											>
												<div
													class="h-full rounded-full bg-blue-400"
													style={`width: ${Math.round(record.confidence * 100)}%`}
												></div>
											</div>
											<p class="mt-2 text-xs leading-5 text-slate-400">
												{record.is_essential ? $t('demo.evidence.essential') : $t('demo.evidence.maskable')}
											</p>
										</li>
									{/each}
								</ul>
							{:else}
								<p class="rounded-xl border border-dashed border-slate-800 p-3 text-xs leading-5 text-slate-400">
									{$t('demo.evidence.none')}
								</p>
							{/if}
						</div>

						{#if latestMeta.masked_text}
							<details class="group rounded-xl border border-slate-800 bg-slate-950/35">
								<summary class="cursor-pointer list-none px-3 py-2.5 text-xs font-medium text-slate-300 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500/60">
									{$t('demo.masked.title')}
									<span class="float-right text-slate-400 transition group-open:rotate-45" aria-hidden="true">+</span>
								</summary>
								<div class="border-t border-slate-800 p-3">
									<p class="mb-2 text-[11px] leading-4 text-slate-400">{$t('demo.masked.description')}</p>
									<pre class="max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-2 text-[11px] leading-5 text-slate-400">{latestMeta.masked_text}</pre>
								</div>
							</details>
						{/if}
					</div>
				{:else}
					<div class="p-5">
						<p class="rounded-xl border border-dashed border-slate-800 px-4 py-10 text-center text-xs leading-5 text-slate-400">
							{$t('demo.decision.empty')}
						</p>
					</div>
				{/if}
			</aside>
		</div>
	</main>
</div>

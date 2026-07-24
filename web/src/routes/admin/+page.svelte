<script lang="ts">
	import type {
		KeyOut,
		KeyCreated,
		ModelCreate,
		ModelOut,
		ProviderOut,
		ProfileListResponse,
		RouterSettings,
		SettingsUpdate,
		TelemetryExport,
		TelemetryRetention
	} from '$lib/types';
	import {
		adminAuth,
		keys as keysApi,
		models as modelsApi,
		profiles as profilesApi,
		providers as providersApi,
		runtime as runtimeApi,
		settings as settingsApi,
		telemetry as telemetryApi
	} from '$lib/api';
	import { Alert, Button, Card, LangToggle, Modal, Select } from '$lib/components/ui';
	import {
		BulkActionBar,
		CreateKeyModal,
		KeyList,
		RenameKeyModal,
		ShowKeyModal,
		TelemetryDashboard
	} from '$lib/components/admin';
	import { locale, t } from '$lib/i18n';
	import { onDestroy, onMount } from 'svelte';
	import { get } from 'svelte/store';

	type AdminSection = 'overview' | 'models' | 'providers' | 'keys' | 'settings' | 'data';
	type AlertVariant = 'success' | 'error' | 'warning';

	const navItems: { id: AdminSection; key: string }[] = [
		{ id: 'overview', key: 'admin.nav.overview' },
		{ id: 'models', key: 'admin.nav.models' },
		{ id: 'providers', key: 'admin.nav.providers' },
		{ id: 'keys', key: 'admin.nav.keys' },
		{ id: 'settings', key: 'admin.nav.settings' },
		{ id: 'data', key: 'admin.nav.data' }
	];

	const emptyModel: ModelCreate = {
		model_id: '',
		provider_id: 'openrouter',
		display_name: '',
		params: '',
		location: 'external',
		tier: 'small',
		cost_per_1m_tokens: 0,
		api_base_override: ''
	};

	onDestroy(adminAuth.clear);

	let activeSection = $state<AdminSection>('overview');
	let adminPassword = $state('');
	let authenticated = $state(false);
	let authenticating = $state(false);
	let sessionRestoring = $state(true);
	let demoMode = $state(false);
	let busyAction = $state('');
	let keys = $state<KeyOut[]>([]);
	let settings = $state<RouterSettings | null>(null);
	let registryModels = $state<ModelOut[]>([]);
	let providers = $state<ProviderOut[]>([]);
	let profileState = $state<ProfileListResponse | null>(null);
	let telemetryData = $state<TelemetryExport | null>(null);
	let retention = $state<TelemetryRetention | null>(null);
	let selectedIds = $state<Set<string>>(new Set());
	let modelDraft = $state<ModelCreate>({ ...emptyModel });
	let decisionModel = $state('');
	let localModel = $state('');
	let externalModel = $state('');
	let selectedProfile = $state('');

	let createOpen = $state(false);
	let showKeyOpen = $state(false);
	let createdKey = $state('');
	let renameOpen = $state(false);
	let renameKeyId = $state('');
	let renameCurrentName = $state('');
	let bulkDeleteConfirm = $state(false);
	let deleteModelConfirm = $state<ModelOut | null>(null);
	let purgeAllConfirm = $state(false);

	let alerts = $state<{ id: number; message: string; variant: AlertVariant }[]>([]);
	let alertCounter = $state(0);

	let localModelOptions = $derived(
		(settings?.models ?? [])
			.filter((model) => model.location === 'local')
			.map((model) => ({ value: model.model_id, label: model.display_name ?? model.model_id }))
	);
	let externalModelOptions = $derived(
		(settings?.models ?? [])
			.filter((model) => model.location === 'external')
			.map((model) => ({ value: model.model_id, label: model.display_name ?? model.model_id }))
	);
	let profileOptions = $derived(
		Object.keys(profileState?.available ?? {}).map((name) => ({
			value: name,
			label: profileState?.available[name]?.description || name
		}))
	);
	let providerOptions = $derived(
		providers.map((provider) => ({ value: provider.id, label: provider.name }))
	);
	let activeModels = $derived(registryModels.filter((model) => model.is_active));

	function showAlert(message: string, variant: AlertVariant = 'success') {
		const id = ++alertCounter;
		alerts = [...alerts, { id, message, variant }];
		setTimeout(() => {
			alerts = alerts.filter((alert) => alert.id !== id);
		}, 5000);
	}

	function errorMessage(error: unknown): string {
		return error instanceof Error ? error.message : String(error);
	}

	function applySettings(next: RouterSettings) {
		settings = next;
		decisionModel = next.decision.model;
		localModel = next.local.model;
		externalModel = next.external.model;
	}

	async function loadAdminData() {
		applySettings(await settingsApi.get());
		await loadOptionalData();
	}

	async function restoreAdminSession() {
		try {
			const capabilities = await runtimeApi.get();
			if (capabilities.mode === 'dev') {
				demoMode = true;
				return;
			}
			if (await adminAuth.restore()) {
				await loadAdminData();
				authenticated = true;
			}
		} catch (error) {
			adminAuth.clear();
			showAlert(errorMessage(error), 'error');
		} finally {
			sessionRestoring = false;
		}
	}

	onMount(() => {
		void restoreAdminSession();
	});

	async function loadOptionalData() {
		const results = await Promise.allSettled([
			keysApi.list(),
			modelsApi.adminList(),
			providersApi.list(),
			profilesApi.list(),
			telemetryApi.retention(),
			telemetryApi.dashboard()
		]);
		const [keysResult, modelsResult, providersResult, profilesResult, retentionResult, telemetryResult] =
			results;

		if (keysResult.status === 'fulfilled') keys = keysResult.value;
		if (modelsResult.status === 'fulfilled') registryModels = modelsResult.value;
		if (providersResult.status === 'fulfilled') providers = providersResult.value.providers;
		if (profilesResult.status === 'fulfilled') {
			profileState = profilesResult.value;
			selectedProfile = profilesResult.value.active;
		}
		if (retentionResult.status === 'fulfilled') retention = retentionResult.value;
		if (telemetryResult.status === 'fulfilled') telemetryData = telemetryResult.value;

		if (providers.length && !providers.some((provider) => provider.id === modelDraft.provider_id)) {
			modelDraft.provider_id = providers[0].id;
		}
		if (results.some((result) => result.status === 'rejected')) {
			showAlert(get(t)('admin.load.partial'), 'warning');
		}
	}

	async function handleUnlock() {
		const password = adminPassword;
		if (!password || authenticating) return;
		authenticating = true;
		try {
			await adminAuth.login(password);
			await loadAdminData();
			authenticated = true;
			adminPassword = '';
		} catch (error) {
			adminAuth.clear();
			authenticated = false;
			showAlert(errorMessage(error), 'error');
		} finally {
			authenticating = false;
		}
	}

	async function handleSignOut() {
		try {
			await adminAuth.logout();
		} catch (error) {
			showAlert(errorMessage(error), 'error');
			return;
		}
		authenticated = false;
		adminPassword = '';
		createdKey = '';
		keys = [];
		settings = null;
		registryModels = [];
		providers = [];
		profileState = null;
		telemetryData = null;
		retention = null;
		selectedIds = new Set();
		alerts = [];
		activeSection = 'overview';
	}

	function handleToggleSelect(id: string, checked: boolean) {
		const next = new Set(selectedIds);
		checked ? next.add(id) : next.delete(id);
		selectedIds = next;
	}

	function handleToggleSelectAll(checked: boolean) {
		selectedIds = checked ? new Set(keys.map((key) => key.id)) : new Set();
	}

	async function handleToggleActive(id: string) {
		const key = keys.find((item) => item.id === id);
		if (!key) return;
		try {
			await keysApi.update(id, { is_active: !key.is_active });
			keys = keys.map((item) => (item.id === id ? { ...item, is_active: !item.is_active } : item));
			showAlert(`${key.name} ${get(t)(key.is_active ? 'alert.toggle_deactivated' : 'alert.toggle_activated')}`);
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		}
	}

	async function handleRenew(id: string) {
		try {
			const result = await keysApi.renew(id);
			createdKey = result.api_key;
			showKeyOpen = true;
			keys = await keysApi.list();
			showAlert(get(t)('alert.key_renewed'));
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		}
	}

	async function handleDelete(id: string) {
		try {
			await keysApi.delete(id);
			keys = keys.filter((key) => key.id !== id);
			selectedIds = new Set([...selectedIds].filter((selected) => selected !== id));
			showAlert(get(t)('alert.key_deleted'));
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		}
	}

	function handleRename(id: string, currentName: string) {
		renameKeyId = id;
		renameCurrentName = currentName;
		renameOpen = true;
	}

	async function handleCopyPrefix(prefix: string, button: HTMLButtonElement) {
		try {
			await navigator.clipboard.writeText(`${prefix}…`);
			const previous = button.textContent;
			button.textContent = get(t)('common.copied');
			setTimeout(() => (button.textContent = previous), 1500);
		} catch {
			showAlert(get(t)('alert.copy_failed'), 'error');
		}
	}

	async function handleBulkToggle(isActive: boolean) {
		try {
			const result = await keysApi.bulkToggle([...selectedIds], isActive);
			keys = keys.map((key) => (selectedIds.has(key.id) ? { ...key, is_active: isActive } : key));
			selectedIds = new Set();
			showAlert(`${result.updated} ${get(t)(isActive ? 'alert.keys_activated' : 'alert.keys_deactivated')}`);
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		}
	}

	async function handleBulkDelete() {
		try {
			const result = await keysApi.bulkDelete([...selectedIds]);
			keys = keys.filter((key) => !selectedIds.has(key.id));
			selectedIds = new Set();
			bulkDeleteConfirm = false;
			showAlert(`${result.updated} ${get(t)('alert.keys_bulk_deleted')}`);
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		}
	}

	function handleKeyCreated(data: KeyCreated) {
		createdKey = data.api_key;
		showKeyOpen = true;
		void keysApi.list().then((nextKeys) => (keys = nextKeys)).catch((error) => showAlert(errorMessage(error), 'error'));
		showAlert(get(t)('alert.key_created'));
	}

	async function refreshModelsAndSettings() {
		const [nextModels, nextSettings] = await Promise.all([modelsApi.adminList(), settingsApi.get()]);
		registryModels = nextModels;
		applySettings(nextSettings);
	}

	async function handleCreateModel() {
		if (!modelDraft.model_id.trim() || busyAction) return;
		busyAction = 'create-model';
		try {
			const payload: ModelCreate = {
				...modelDraft,
				model_id: modelDraft.model_id.trim(),
				display_name: modelDraft.display_name?.trim() || null,
				params: modelDraft.params?.trim() || null,
				api_base_override: modelDraft.api_base_override?.trim() || null
			};
			await modelsApi.validate(payload);
			await modelsApi.create(payload);
			await refreshModelsAndSettings();
			modelDraft = { ...emptyModel, provider_id: providers[0]?.id ?? 'openrouter' };
			showAlert(get(t)('alert.model_created'));
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		} finally {
			busyAction = '';
		}
	}

	async function handleModelActivation(model: ModelOut) {
		busyAction = `model-${model.id}`;
		try {
			if (model.is_active) await modelsApi.delete(model.id);
			else await modelsApi.activate(model.id);
			await refreshModelsAndSettings();
			showAlert(get(t)(model.is_active ? 'alert.model_deactivated' : 'alert.model_activated'));
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		} finally {
			busyAction = '';
			deleteModelConfirm = null;
		}
	}


	async function handleActivateProfile() {
		if (!selectedProfile || selectedProfile === profileState?.active) return;
		busyAction = 'profile';
		try {
			await profilesApi.activate(selectedProfile);
			const [nextProfiles, nextSettings] = await Promise.all([profilesApi.list(), settingsApi.get()]);
			profileState = nextProfiles;
			applySettings(nextSettings);
			showAlert(get(t)('alert.profile_activated'));
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		} finally {
			busyAction = '';
		}
	}

	async function handleSaveSettings() {
		const update: SettingsUpdate = {};
		if (localModelOptions.some((option) => option.value === decisionModel)) update.decision = { model: decisionModel };
		if (localModelOptions.some((option) => option.value === localModel)) update.local = { model: localModel };
		if (externalModelOptions.some((option) => option.value === externalModel)) update.external = { model: externalModel };
		if (!Object.keys(update).length) {
			showAlert(get(t)('admin.settings.no_compatible_models'), 'warning');
			return;
		}
		busyAction = 'settings';
		try {
			await settingsApi.save(update);
			applySettings(await settingsApi.get());
			showAlert(get(t)('alert.settings_saved'));
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		} finally {
			busyAction = '';
		}
	}

	async function refreshTelemetry() {
		telemetryData = await telemetryApi.dashboard();
	}

	async function handleDownload(format: 'json' | 'csv') {
		busyAction = `download-${format}`;
		try {
			const { blob, filename } = await telemetryApi.download(format);
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;
			link.download = filename;
			link.click();
			URL.revokeObjectURL(url);
			showAlert(get(t)('alert.export_ready'));
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		} finally {
			busyAction = '';
		}
	}

	async function handlePurge(scope: 'expired' | 'all') {
		busyAction = `purge-${scope}`;
		try {
			const result = await telemetryApi.purge({ scope, confirm: scope === 'all' });
			await refreshTelemetry();
			purgeAllConfirm = false;
			showAlert(
				`${result.deleted.request_traces} ${get(t)('admin.data.requests_deleted')}`
			);
		} catch (error) {
			showAlert(errorMessage(error), 'error');
		} finally {
			busyAction = '';
		}
	}

	function formatDate(value: string | null): string {
		if (!value) return get(t)('common.never');
		const parsed = new Date(value);
		if (Number.isNaN(parsed.getTime())) return value;
		return new Intl.DateTimeFormat(get(locale) === 'ko' ? 'ko-KR' : 'en-US', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		}).format(parsed);
	}



</script>

<svelte:head>
	<title>{$t('admin.title')} — Privacy Router</title>
</svelte:head>

<div class="min-h-dvh bg-slate-950 text-slate-200">
	<header class="border-b border-slate-800/80 bg-slate-950/95 px-4 py-4 sm:px-6">
		<div class="mx-auto flex max-w-7xl items-center justify-between gap-4">
			<a href="/" class="rounded-md text-sm text-slate-400 transition hover:text-white focus:outline-none focus:ring-2 focus:ring-blue-500/60">
				{$t('nav.back')}
			</a>
			<div class="flex items-center gap-3">
				{#if authenticated}
					<span class="hidden items-center gap-2 text-xs text-slate-400 sm:inline-flex">
						<span class="h-2 w-2 rounded-full bg-emerald-400"></span>
						{$t('admin.status.connected')}
					</span>
					<Button variant="secondary" size="sm" onclick={() => void handleSignOut()}>{$t('admin.auth.sign_out')}</Button>
				{/if}
				<LangToggle />
			</div>
		</div>
	</header>

	<div class="fixed right-4 top-20 z-50 w-[min(24rem,calc(100vw-2rem))] space-y-2" aria-live="polite">
		{#each alerts as alert (alert.id)}
			<Alert variant={alert.variant} onclose={() => (alerts = alerts.filter((item) => item.id !== alert.id))}>
				{alert.message}
			</Alert>
		{/each}
	</div>

	{#if sessionRestoring}
		<main class="grid min-h-[calc(100dvh-73px)] place-items-center px-4">
			<p class="text-sm text-slate-400">{$t('admin.auth.restoring')}</p>
		</main>
	{:else if demoMode}
		<main class="grid min-h-[calc(100dvh-73px)] place-items-center px-4 py-12">
			<Card class="w-full max-w-xl p-8 text-center">
				<p class="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">{$t('admin.auth.eyebrow')}</p>
				<h1 class="mt-3 text-2xl font-semibold tracking-tight text-white">{$t('admin.dev.title')}</h1>
				<p class="mx-auto mt-4 max-w-md text-sm leading-6 text-slate-400">{$t('admin.dev.description')}</p>
				<a
					href="/demo"
					class="mt-6 inline-flex rounded-lg bg-blue-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/60"
				>
					{$t('admin.dev.action')}
				</a>
			</Card>
		</main>
	{:else if !authenticated}
		<main class="mx-auto grid min-h-[calc(100dvh-73px)] max-w-6xl place-items-center px-4 py-12 sm:px-6">
			<div class="grid w-full items-center gap-10 lg:grid-cols-[1fr_28rem]">
				<div class="max-w-xl">
					<p class="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">{$t('admin.auth.eyebrow')}</p>
					<h1 class="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{$t('admin.auth.title')}</h1>
					<p class="mt-4 max-w-lg text-sm leading-6 text-slate-400">{$t('admin.auth.description')}</p>
					<div class="mt-8 grid gap-3 sm:grid-cols-3">
						{#each ['admin.auth.capability.models', 'admin.auth.capability.keys', 'admin.auth.capability.telemetry'] as key}
							<div class="rounded-xl border border-slate-800 bg-slate-900/45 px-4 py-3 text-xs leading-5 text-slate-400">{$t(key)}</div>
						{/each}
					</div>
				</div>
				<Card>
					<form class="space-y-5 p-6" onsubmit={(event) => { event.preventDefault(); void handleUnlock(); }}>
						<div class="space-y-2">
							<label for="admin-password" class="block text-sm font-medium text-slate-200">{$t('admin.auth.label')}</label>
							<input
								id="admin-password"
								type="password"
								bind:value={adminPassword}
								autocomplete="current-password"
								spellcheck="false"
								aria-describedby="admin-password-storage"
								placeholder={$t('admin.auth.placeholder')}
								class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
							/>
							<p id="admin-password-storage" class="text-xs leading-5 text-slate-400">{$t('admin.auth.memory_only')}</p>
						</div>
						<div class="grid">
							<Button type="submit" disabled={!adminPassword || authenticating}>
								{authenticating ? $t('admin.auth.submitting') : $t('admin.auth.submit')}
							</Button>
						</div>
					</form>
				</Card>
			</div>
		</main>
	{:else}
		<div class="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[14rem_minmax(0,1fr)] lg:py-8">
			<aside class="min-w-0 lg:sticky lg:top-6 lg:self-start">
				<div class="mb-5 px-2">
					<p class="text-xs font-semibold uppercase tracking-[0.18em] text-blue-400">{$t('admin.eyebrow')}</p>
					<h1 class="mt-2 text-xl font-semibold text-white">{$t('admin.title')}</h1>
					<p class="mt-1 text-xs leading-5 text-slate-400">{$t('admin.subtitle')}</p>
				</div>
				<nav class="flex gap-2 overflow-x-auto pb-2 lg:flex-col" aria-label={$t('admin.navigation')}>
					{#each navItems as item}
						<button
							type="button"
							class={`shrink-0 rounded-lg px-3 py-2 text-left text-sm transition focus:outline-none focus:ring-2 focus:ring-blue-500/60 ${activeSection === item.id ? 'bg-blue-500/15 text-blue-200' : 'text-slate-400 hover:bg-slate-900'}`}
							aria-current={activeSection === item.id ? 'page' : undefined}
							onclick={() => (activeSection = item.id)}
						>
							{$t(item.key)}
						</button>
					{/each}
				</nav>
			</aside>

			<main class="min-w-0 space-y-6">
				<Alert variant="warning">{$t('admin.warning')}</Alert>

				{#if activeSection === 'overview'}
					<section aria-labelledby="overview-title" class="space-y-6">
						<div>
							<p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{$t('admin.overview.eyebrow')}</p>
							<h2 id="overview-title" class="mt-2 text-2xl font-semibold tracking-tight text-white">{$t('admin.overview.title')}</h2>
							<p class="mt-2 text-sm text-slate-400">{$t('admin.overview.description')}</p>
						</div>
						<TelemetryDashboard data={telemetryData} />
					</section>
				{:else if activeSection === 'models'}
					<section aria-labelledby="models-title" class="space-y-6">
						<div class="flex flex-wrap items-end justify-between gap-4"><div><p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{$t('admin.models.eyebrow')}</p><h2 id="models-title" class="mt-2 text-2xl font-semibold text-white">{$t('admin.models.title')}</h2><p class="mt-2 text-sm text-slate-400">{$t('admin.models.description')}</p></div><span class="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">{activeModels.length} {$t('admin.models.active_count')}</span></div>
						<Card>
							<form class="space-y-5 p-5 sm:p-6" onsubmit={(event) => { event.preventDefault(); void handleCreateModel(); }}>
								<div><h3 class="font-semibold text-white">{$t('admin.models.add')}</h3><p class="mt-1 text-xs leading-5 text-slate-400">{$t('admin.models.add_description')}</p></div>
								<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
									<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.models.model_id')}</span><input bind:value={modelDraft.model_id} required placeholder="openrouter/vendor/model" class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:border-blue-500 focus:outline-none" /></label>
									<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.models.display_name')}</span><input bind:value={modelDraft.display_name} placeholder="Model name" class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:border-blue-500 focus:outline-none" /></label>
									<Select bind:value={modelDraft.provider_id} options={providerOptions} label={$t('admin.models.provider')} disabled={!providerOptions.length} />
									<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.models.location')}</span><select bind:value={modelDraft.location} class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"><option value="external">{$t('admin.models.external')}</option><option value="local">{$t('admin.models.local')}</option></select></label>
									<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.models.tier')}</span><select bind:value={modelDraft.tier} class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"><option value="small">Small</option><option value="middle">Middle</option><option value="large">Large</option></select></label>
									<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.models.cost')}</span><input type="number" min="0" step="0.0001" bind:value={modelDraft.cost_per_1m_tokens} class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" /></label>
									<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.models.params')}</span><input bind:value={modelDraft.params} placeholder="26B" class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:border-blue-500 focus:outline-none" /></label>
									<label class="space-y-1.5 text-xs font-medium text-slate-300 md:col-span-2"><span>{$t('admin.models.api_base')}</span><input type="url" bind:value={modelDraft.api_base_override} placeholder="https://api.example.com/v1" class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:border-blue-500 focus:outline-none" /></label>
								</div>
								<div class="flex justify-end"><Button type="submit" disabled={!modelDraft.model_id.trim() || !providerOptions.length || Boolean(busyAction)}>{busyAction === 'create-model' ? $t('admin.models.adding') : $t('admin.models.add')}</Button></div>
							</form>
						</Card>
						<div class="grid gap-4 xl:grid-cols-2">
							{#each registryModels as model (model.id)}
								<Card class={model.is_active ? '' : 'opacity-65'}><div class="p-5"><div class="flex items-start justify-between gap-4"><div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><h3 class="truncate font-semibold text-white">{model.display_name ?? model.model_id}</h3><span class={`rounded-full border px-2 py-0.5 text-[11px] ${model.is_active ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300' : 'border-slate-700 text-slate-400'}`}>{model.is_active ? $t('admin.models.active') : $t('admin.models.inactive')}</span></div><p class="mt-1 break-all font-mono text-xs text-slate-400">{model.model_id}</p></div><Button variant={model.is_active ? 'danger' : 'secondary'} size="sm" onclick={() => model.is_active ? (deleteModelConfirm = model) : void handleModelActivation(model)} disabled={busyAction === `model-${model.id}`}>{model.is_active ? $t('admin.models.deactivate') : $t('admin.models.activate')}</Button></div><dl class="mt-5 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4"><div><dt class="text-slate-400">{$t('admin.models.provider')}</dt><dd class="mt-1 text-slate-300">{model.provider_id}</dd></div><div><dt class="text-slate-400">{$t('admin.models.location')}</dt><dd class="mt-1 text-slate-300">{model.location}</dd></div><div><dt class="text-slate-400">{$t('admin.models.tier')}</dt><dd class="mt-1 text-slate-300">{model.tier}</dd></div><div><dt class="text-slate-400">{$t('admin.models.cost_short')}</dt><dd class="mt-1 tabular-nums text-slate-300">${model.cost_per_1m_tokens.toFixed(4)}</dd></div></dl></div></Card>
							{/each}
						</div>
					</section>
				{:else if activeSection === 'providers'}
					<section aria-labelledby="providers-title" class="space-y-6">
						<div><p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{$t('admin.providers.eyebrow')}</p><h2 id="providers-title" class="mt-2 text-2xl font-semibold text-white">{$t('admin.providers.title')}</h2><p class="mt-2 text-sm text-slate-400">{$t('admin.providers.description')}</p></div>
						<div class="grid gap-4 xl:grid-cols-2">
							{#each providers as provider (provider.id)}
								<Card>
									<div class="p-5">
										<div class="flex items-start justify-between gap-3">
											<div>
												<h3 class="font-semibold text-white">{provider.name}</h3>
												<p class="mt-1 font-mono text-xs text-slate-400">{provider.id}</p>
											</div>
											<span class={`rounded-full border px-2 py-0.5 text-[11px] ${provider.has_key ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300' : 'border-amber-400/20 bg-amber-400/10 text-amber-300'}`}>
												{provider.has_key ? $t('admin.providers.ready') : $t('admin.providers.missing')}
											</span>
										</div>
										<dl class="mt-4 space-y-2 text-xs">
											<div class="flex justify-between gap-4">
												<dt class="text-slate-400">{$t('admin.providers.source')}</dt>
												<dd class="text-slate-300">{provider.source}</dd>
											</div>
											<div class="flex justify-between gap-4">
												<dt class="text-slate-400">{$t('admin.providers.environment')}</dt>
												<dd class="font-mono text-slate-300">{provider.api_key_env ?? '—'}</dd>
											</div>
											<div class="flex justify-between gap-4">
												<dt class="text-slate-400">{$t('admin.providers.endpoint')}</dt>
												<dd class="max-w-[70%] truncate font-mono text-slate-300" title={provider.api_base ?? ''}>{provider.api_base ?? '—'}</dd>
											</div>
										</dl>
										<p class="mt-5 text-xs leading-5 text-slate-400">{$t('admin.providers.env_hint')}</p>
									</div>
								</Card>
							{/each}
						</div>
					</section>
				{:else if activeSection === 'keys'}
					<section aria-labelledby="keys-title" class="space-y-4">
						<div class="flex flex-wrap items-end justify-between gap-4"><div><p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{$t('admin.keys.eyebrow')}</p><h2 id="keys-title" class="mt-2 text-2xl font-semibold text-white">{$t('admin.keys.title')}</h2><p class="mt-2 text-sm text-slate-400">{$t('admin.keys.description')}</p></div><Button onclick={() => (createOpen = true)}>+ {$t('admin.keys.create')}</Button></div>
						<BulkActionBar selectedCount={selectedIds.size} onActivate={() => handleBulkToggle(true)} onDeactivate={() => handleBulkToggle(false)} onDelete={() => (bulkDeleteConfirm = true)} onClear={() => (selectedIds = new Set())} />
						<KeyList {keys} {selectedIds} onToggleSelect={handleToggleSelect} onToggleSelectAll={handleToggleSelectAll} onToggleActive={handleToggleActive} onRenew={handleRenew} onDelete={handleDelete} onRename={handleRename} onCopyPrefix={handleCopyPrefix} />
					</section>
				{:else if activeSection === 'settings'}
					<section aria-labelledby="settings-title" class="space-y-6">
						<div><p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{$t('admin.settings.eyebrow')}</p><h2 id="settings-title" class="mt-2 text-2xl font-semibold text-white">{$t('admin.settings.title')}</h2><p class="mt-2 max-w-3xl text-sm leading-6 text-slate-400">{$t('admin.settings.description')}</p></div>
						<Card><div class="space-y-4 p-5 sm:p-6"><div><h3 class="font-semibold text-white">{$t('admin.settings.profile')}</h3><p class="mt-1 text-xs text-slate-400">{$t('admin.settings.profile_description')}</p></div><div class="flex flex-col gap-3 sm:flex-row sm:items-end"><div class="min-w-0 flex-1"><Select bind:value={selectedProfile} options={profileOptions} label={$t('admin.settings.active_profile')} disabled={profileOptions.length < 2} /></div><Button variant="secondary" onclick={handleActivateProfile} disabled={!selectedProfile || selectedProfile === profileState?.active || busyAction === 'profile'}>{$t('admin.settings.activate_profile')}</Button></div></div></Card>
						<Card><div class="space-y-5 p-5 sm:p-6"><div><h3 class="font-semibold text-white">{$t('admin.settings.assignments')}</h3><p class="mt-1 text-xs leading-5 text-slate-400">{$t('admin.settings.assignments_description')}</p></div>{#if !localModelOptions.length}<Alert variant="warning">{$t('admin.settings.no_local_models')}</Alert>{/if}<div class="grid gap-4 lg:grid-cols-3"><Select bind:value={decisionModel} options={localModelOptions} label={$t('admin.settings.decision')} disabled={!localModelOptions.length} /><Select bind:value={localModel} options={localModelOptions} label={$t('admin.settings.local_generation')} disabled={!localModelOptions.length} /><Select bind:value={externalModel} options={externalModelOptions} label={$t('admin.settings.external_generation')} disabled={!externalModelOptions.length} /></div><div class="flex justify-end"><Button onclick={handleSaveSettings} disabled={busyAction === 'settings'}>{busyAction === 'settings' ? $t('admin.settings.saving') : $t('admin.settings.save')}</Button></div></div></Card>
					</section>
				{:else}
					<section aria-labelledby="data-title" class="space-y-6">
						<div><p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{$t('admin.data.eyebrow')}</p><h2 id="data-title" class="mt-2 text-2xl font-semibold text-white">{$t('admin.data.title')}</h2><p class="mt-2 text-sm text-slate-400">{$t('admin.data.description')}</p></div>
						<div class="grid gap-4 sm:grid-cols-3"><Card><div class="p-5"><p class="text-xs uppercase tracking-wide text-slate-400">{$t('admin.data.retention')}</p><p class="mt-3 text-2xl font-semibold text-white">{retention?.raw_ttl_hours ?? '—'}<span class="ml-1 text-sm font-normal text-slate-400">{$t('admin.data.hours')}</span></p></div></Card><Card><div class="p-5"><p class="text-xs uppercase tracking-wide text-slate-400">{$t('admin.data.privacy_level')}</p><p class="mt-3 text-lg font-semibold text-white">{retention?.export_privacy_level ?? '—'}</p></div></Card><Card><div class="p-5"><p class="text-xs uppercase tracking-wide text-slate-400">{$t('admin.data.last_export')}</p><p class="mt-3 text-sm font-medium text-white">{telemetryData ? formatDate(telemetryData.exported_at) : '—'}</p></div></Card></div>
						<Card><div class="space-y-5 p-5 sm:p-6"><div><h3 class="font-semibold text-white">{$t('admin.data.export')}</h3><p class="mt-1 text-xs leading-5 text-slate-400">{$t('admin.data.export_description')}</p></div><div class="flex flex-wrap gap-3"><Button variant="secondary" onclick={() => handleDownload('json')} disabled={Boolean(busyAction)}>{$t('admin.data.export_json')}</Button><Button variant="secondary" onclick={() => handleDownload('csv')} disabled={Boolean(busyAction)}>{$t('admin.data.export_csv')}</Button><Button variant="secondary" onclick={() => void refreshTelemetry()} disabled={Boolean(busyAction)}>{$t('admin.data.refresh')}</Button></div></div></Card>
						<Card><div class="space-y-5 p-5 sm:p-6"><div><h3 class="font-semibold text-white">{$t('admin.data.retention_actions')}</h3><p class="mt-1 text-xs leading-5 text-slate-400">{$t('admin.data.retention_description')}</p></div><div class="flex flex-wrap gap-3"><Button variant="secondary" onclick={() => handlePurge('expired')} disabled={Boolean(busyAction)}>{$t('admin.data.purge_expired')}</Button><Button variant="danger" onclick={() => (purgeAllConfirm = true)} disabled={Boolean(busyAction)}>{$t('admin.data.purge_all')}</Button></div></div></Card>
					</section>
				{/if}
			</main>
		</div>
	{/if}
</div>

{#if authenticated}
	<CreateKeyModal bind:open={createOpen} onclose={() => (createOpen = false)} oncreated={handleKeyCreated} />
	<ShowKeyModal bind:open={showKeyOpen} onclose={() => { showKeyOpen = false; createdKey = ''; }} apiKey={createdKey} />
	<RenameKeyModal bind:open={renameOpen} onclose={() => (renameOpen = false)} keyId={renameKeyId} currentName={renameCurrentName} onsaved={() => keysApi.list().then((nextKeys) => (keys = nextKeys))} />

	<Modal bind:open={bulkDeleteConfirm} onclose={() => (bulkDeleteConfirm = false)} title={$t('admin.keys.delete_confirm')}>
		<p class="text-sm text-slate-400">{selectedIds.size} {$t('admin.keys.delete_confirm_msg')}</p>
		{#snippet footer()}
			<Button variant="secondary" onclick={() => (bulkDeleteConfirm = false)}>{$t('common.cancel')}</Button>
			<Button variant="danger" onclick={handleBulkDelete}>{$t('common.delete')}</Button>
		{/snippet}
	</Modal>

	{#if deleteModelConfirm}
		<Modal open={true} onclose={() => (deleteModelConfirm = null)} title={$t('admin.models.deactivate_title')}>
			<p class="text-sm leading-6 text-slate-400">
				{$t('admin.models.deactivate_description')}
				<span class="font-mono text-slate-200">{deleteModelConfirm.model_id}</span>
			</p>
			{#snippet footer()}
				<Button variant="secondary" onclick={() => (deleteModelConfirm = null)}>{$t('common.cancel')}</Button>
				<Button variant="danger" onclick={() => deleteModelConfirm && handleModelActivation(deleteModelConfirm)}>{$t('admin.models.deactivate')}</Button>
			{/snippet}
		</Modal>
	{/if}

	<Modal bind:open={purgeAllConfirm} onclose={() => (purgeAllConfirm = false)} title={$t('admin.data.purge_confirm_title')}>
		<p class="text-sm leading-6 text-slate-400">{$t('admin.data.purge_confirm_description')}</p>
		{#snippet footer()}
			<Button variant="secondary" onclick={() => (purgeAllConfirm = false)}>{$t('common.cancel')}</Button>
			<Button variant="danger" onclick={() => handlePurge('all')}>{$t('admin.data.purge_all')}</Button>
		{/snippet}
	</Modal>
{/if}

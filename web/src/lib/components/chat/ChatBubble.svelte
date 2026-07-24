<script lang="ts">
	import type { ChatMessage, PrivacyRouterMeta } from '$lib/types';
	import { t } from '$lib/i18n';

	interface Props {
		message: ChatMessage;
		meta?: PrivacyRouterMeta | null;
	}

	let { message, meta }: Props = $props();
	let isUser = $derived(message.role === 'user');
</script>

<article class="flex gap-3" class:flex-row-reverse={isUser}>
	<div
		class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
		class:bg-blue-600={isUser}
		class:bg-slate-800={!isUser}
		class:text-white={isUser}
		class:text-slate-300={!isUser}
		aria-hidden="true"
	>
		{isUser ? 'U' : 'A'}
	</div>
	<div class="min-w-0 max-w-[88%] space-y-2 sm:max-w-[80%]">
		<p class="sr-only">{isUser ? $t('demo.message.you') : $t('demo.message.assistant')}</p>
		<div
			class="whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-sm leading-relaxed"
			class:bg-blue-600={isUser}
			class:text-white={isUser}
			class:bg-slate-800={!isUser}
			class:text-slate-200={!isUser}
		>
			{message.content}
		</div>
		{#if meta}
			<div class="flex flex-wrap gap-1.5" aria-label={$t('demo.meta.summary')}>
				<span
					class={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
						meta.is_sensitive
							? 'border-amber-400/30 bg-amber-400/10 text-amber-300'
							: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300'
					}`}
				>
					{meta.is_sensitive ? $t('demo.meta.sensitive') : $t('demo.meta.safe')}
				</span>
				<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-0.5 text-xs text-slate-400">
					{meta.route === 'local_api' ? $t('demo.meta.route.local') : $t('demo.meta.route.external')}
				</span>
				<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-0.5 text-xs text-slate-400">
					{meta.policy_action.includes('mask')
						? $t('demo.policy.masked')
						: meta.policy_action.includes('block') || meta.policy_action.includes('reject')
							? $t('demo.policy.blocked')
							: $t('demo.policy.allowed')}
				</span>
			</div>
		{/if}
	</div>
</article>

<script lang="ts">
	import type { KeyOut } from '$lib/types';
	import { Badge, Checkbox, Button } from '$lib/components/ui';
	import { t } from '$lib/i18n';

	interface Props {
		keys: KeyOut[];
		selectedIds: Set<string>;
		onToggleSelect: (id: string, checked: boolean) => void;
		onToggleSelectAll: (checked: boolean) => void;
		onToggleActive: (id: string) => void;
		onRenew: (id: string) => void;
		onDelete: (id: string) => void;
		onRename: (id: string, currentName: string) => void;
		onCopyPrefix: (prefix: string, btn: HTMLButtonElement) => void;
	}

	let {
		keys,
		selectedIds,
		onToggleSelect,
		onToggleSelectAll,
		onToggleActive,
		onRenew,
		onDelete,
		onRename,
		onCopyPrefix
	}: Props = $props();

	let allSelected = $derived(keys.length > 0 && keys.every((k) => selectedIds.has(k.id)));
</script>

{#if keys.length === 0}
	<div class="rounded-xl border border-dashed border-slate-700 p-8 text-center text-slate-400">
		{$t("admin.keys.empty")}
	</div>
{:else}
	<div class="overflow-x-auto rounded-xl border border-slate-800">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-slate-800 bg-slate-900/80">
					<th class="px-4 py-3 text-left">
						<Checkbox
							checked={allSelected}
							onchange={onToggleSelectAll}
						/>
					</th>
					<th class="px-4 py-3 text-left font-medium text-slate-400">{$t("admin.keys.name")}</th>
					<th class="px-4 py-3 text-left font-medium text-slate-400">{$t("admin.keys.prefix")}</th>
					<th class="px-4 py-3 text-left font-medium text-slate-400">{$t("admin.keys.status")}</th>
					<th class="px-4 py-3 text-left font-medium text-slate-400">{$t("admin.keys.last_used")}</th>
					<th class="px-4 py-3 text-right font-medium text-slate-400">{$t("admin.keys.actions")}</th>
				</tr>
			</thead>
			<tbody>
				{#each keys as key (key.id)}
					<tr class="border-b border-slate-800/50 hover:bg-slate-800/30 transition">
						<td class="px-4 py-3">
							<Checkbox
								checked={selectedIds.has(key.id)}
								onchange={(checked) => onToggleSelect(key.id, checked)}
							/>
						</td>
						<td class="px-4 py-3">
							<button
								class="text-left font-medium text-white hover:text-blue-400 transition cursor-pointer"
								onclick={() => onRename(key.id, key.name)}
							>
								{key.name}
							</button>
						</td>
						<td class="px-4 py-3">
							<div class="flex items-center gap-2">
								<code class="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400 font-mono">
									{key.prefix}…
								</code>
								<button
									class="text-slate-400 hover:text-white transition text-xs cursor-pointer"
									onclick={(e) => onCopyPrefix(key.prefix, e.currentTarget as HTMLButtonElement)}
									title="{$t('admin.keys.copy_prefix')}"
								>
									📋
								</button>
							</div>
						</td>
						<td class="px-4 py-3">
							{#if key.is_active}
								<Badge variant="success">{$t("admin.keys.active")}</Badge>
							{:else}
								<Badge variant="default">{$t("admin.keys.inactive")}</Badge>
							{/if}
						</td>
						<td class="px-4 py-3 text-xs text-slate-400">
							{key.last_used_at ? new Date(key.last_used_at).toLocaleString('ko-KR') : '—'}
						</td>
						<td class="px-4 py-3">
							<div class="flex justify-end gap-1">
								<Button variant="ghost" size="sm" onclick={() => onToggleActive(key.id)}>
									{key.is_active ? $t("admin.keys.deactivate") : $t("admin.keys.activate")}
								</Button>
								<Button variant="ghost" size="sm" onclick={() => onRenew(key.id)}>
									{$t("admin.keys.renew")}
								</Button>
								<Button variant="ghost" size="sm" onclick={() => onDelete(key.id)}>{$t("common.delete")}
								</Button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

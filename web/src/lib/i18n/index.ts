import { writable, derived } from 'svelte/store';
import en from './en.json';
import ko from './ko.json';

export type Locale = 'en' | 'ko';

const translations: Record<Locale, Record<string, string>> = { en, ko };

export const locale = writable<Locale>(
	typeof localStorage !== 'undefined'
		? (localStorage.getItem('locale') as Locale) ?? 'en'
		: 'en'
);

locale.subscribe((val) => {
	if (typeof localStorage !== 'undefined') localStorage.setItem('locale', val);
});

export const t = derived(locale, ($locale) => {
	return (key: string): string => translations[$locale][key] ?? translations['en'][key] ?? key;
});

export function toggleLocale() {
	locale.update((l) => (l === 'en' ? 'ko' : 'en'));
}

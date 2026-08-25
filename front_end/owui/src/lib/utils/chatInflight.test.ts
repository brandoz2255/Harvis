import { describe, it, expect, beforeEach } from 'vitest';
import {
	setInflight,
	getInflight,
	clearInflight,
	hasInflight,
	touchInflight,
	inflightEpoch
} from './chatInflight';
import { get as getStore } from 'svelte/store';

describe('chatInflight', () => {
	beforeEach(() => {
		clearInflight('a');
		clearInflight('b');
		inflightEpoch.set({});
	});

	it('stores and returns live history by chat id', () => {
		const history = { messages: { m1: { id: 'm1' } }, currentId: 'm1' };
		setInflight('a', { history, responseMessageId: 'm1' });
		expect(hasInflight('a')).toBe(true);
		expect(getInflight('a')?.history).toBe(history);
		expect(getInflight('a')?.responseMessageId).toBe('m1');
		expect(getInflight('b')).toBeUndefined();
	});

	it('preserves controller across partial updates', () => {
		const history = { messages: {}, currentId: null };
		const controller = new AbortController();
		setInflight('a', { history, responseMessageId: 'r1', controller });
		setInflight('a', { history, responseMessageId: 'r1' });
		expect(getInflight('a')?.controller).toBe(controller);
		setInflight('a', { history, responseMessageId: 'r1', controller: null });
		expect(getInflight('a')?.controller).toBeNull();
	});

	it('clears registry and epoch', () => {
		const history = { messages: {}, currentId: null };
		setInflight('a', { history, responseMessageId: 'r1' });
		touchInflight('a');
		expect(getStore(inflightEpoch).a).toBeGreaterThan(0);
		clearInflight('a');
		expect(hasInflight('a')).toBe(false);
		expect(getStore(inflightEpoch).a).toBeUndefined();
	});

	it('bumps epoch on touch', () => {
		touchInflight('a');
		touchInflight('a');
		expect(getStore(inflightEpoch).a).toBe(2);
	});

	it('ignores empty chat ids', () => {
		setInflight('', { history: {}, responseMessageId: 'x' });
		expect(hasInflight('')).toBe(false);
	});

	it('preserves history after marking done so a return can still adopt it', () => {
		const history = { messages: { m1: { id: 'm1', content: 'hi' } }, currentId: 'm1' };
		setInflight('a', { history, responseMessageId: 'm1' });
		setInflight('a', { history, responseMessageId: 'm1', done: true });
		expect(getInflight('a')?.history).toBe(history);
		expect(getInflight('a')?.done).toBe(true);
	});
});

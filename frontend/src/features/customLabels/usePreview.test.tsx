import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import type { SlotRule } from './scopeMerge';
import { useLabelizerPreview, type PreviewResult } from './usePreview';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const RULES: SlotRule[] = [
  { id: 'r1', name: 'R1', isActive: true, targetSlot: 'custom_label_0',
    matchField: 'id', valueTemplate: 'x', fallbackTemplate: '' },
];
const RESULT: PreviewResult = {
  total: 10,
  rules: { r1: { matched: 5, labeled: 4, sample: ['a1'] } },
  slots: { custom_label_0: { labeled: 4, coverage: 40, rules: ['r1'] } },
};

function Probe(props: { rules: SlotRule[]; slotIds?: Record<string, string>; enabled?: boolean }) {
  const state = useLabelizerPreview({
    enabled: props.enabled ?? true,
    feedSourceId: 1,
    rules: props.rules,
    slotIds: props.slotIds ?? {},
  });
  return (
    <div>
      <span data-testid="pending">{String(state.isPending)}</span>
      <span data-testid="errors">{state.errors?.join('|') ?? ''}</span>
      <span data-testid="unavailable">{String(state.unavailable)}</span>
      <span data-testid="total">{state.result?.total ?? ''}</span>
    </div>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('useLabelizerPreview', () => {
  it('fires one debounced preview request and renders the result', async () => {
    let calls = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        return jsonResponse(RESULT);
      }
      return jsonResponse({});
    });
    render(<Probe rules={RULES} slotIds={{ r1: 'a,b' }} />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('10'),
      { timeout: 2500 },
    )).toBeTruthy();
    expect(calls).toBe(1);
  });

  it('sends no request when disabled', async () => {
    const calls: string[] = [];
    stubFetch((url) => {
      calls.push(url);
      return jsonResponse({});
    });
    render(<Probe rules={RULES} enabled={false} />);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(calls.some((u) => u.includes('/preview'))).toBe(false);
    expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('');
  });

  it('surfaces 422 validation errors', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({ errors: ['slotRules[0]: targetSlot must be one of ...'] }, 422);
      }
      return jsonResponse({});
    });
    render(<Probe rules={RULES} />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="errors"]')?.textContent)
        .toContain('targetSlot'),
      { timeout: 2500 },
    )).toBeTruthy();
  });

  it('discards stale responses (newest draft wins)', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return new Promise<Response>((resolve) => {
          const body = { total: 1, rules: {}, slots: {} };
          // every response resolves slowly; the hook's sequence guard must
          // still end up consistent because each tick bumps seq
          setTimeout(() => resolve(jsonResponse(body)), 50);
        });
      }
      return jsonResponse({});
    });
    const { rerender } = render(<Probe rules={RULES} />);
    await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('1'),
      { timeout: 2500 },
    );
    // draft changes -> new debounced call; stale (slow) first response must be dropped
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({ total: 2, rules: {}, slots: {} });
      }
      return jsonResponse({});
    });
    rerender(<Probe rules={[{ ...RULES[0], valueTemplate: 'y' }]} />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('2'),
      { timeout: 2500 },
    )).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('2');
  });
});

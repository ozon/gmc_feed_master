import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
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

// Changes its own draft on click — rerender() remounts in this RTL setup,
// so prop-driven draft changes need a stateful harness to stay mounted.
function DraftProbe() {
  const [draft, setDraft] = useState<SlotRule[]>(RULES);
  const state = useLabelizerPreview({
    enabled: true,
    feedSourceId: 1,
    rules: draft,
    slotIds: {},
  });
  return (
    <div>
      <button onClick={() => setDraft([{ ...RULES[0], valueTemplate: 'y' }])}>
        change draft
      </button>
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
    let calls = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        if (calls === 1) {
          // first response is slow: it resolves only AFTER the second
          // request has started and been applied — so the guard is load-bearing
          return new Promise<Response>((resolve) => {
            setTimeout(() => resolve(jsonResponse({ total: 1, rules: {}, slots: {} })), 1500);
          });
        }
        return jsonResponse({ total: 2, rules: {}, slots: {} });
      }
      return jsonResponse({});
    });
    render(<DraftProbe />);
    // let the first debounced request start, then change the draft so a
    // second request begins while the first is still in flight — the harness
    // must change its own state (rerender remounts in this RTL setup and
    // would never exercise the per-instance guard)
    await new Promise((resolve) => setTimeout(resolve, 700));
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
    expect(await waitFor(
      () => expect(screen.getByTestId('total').textContent).toBe('2'),
      { timeout: 2500 },
    )).toBeTruthy();
    // the slow FIRST response resolves now — the guard must discard it
    await new Promise((resolve) => setTimeout(resolve, 2000));
    expect(screen.getByTestId('total').textContent).toBe('2');
    expect(calls).toBe(2);
  }, 10000);
});

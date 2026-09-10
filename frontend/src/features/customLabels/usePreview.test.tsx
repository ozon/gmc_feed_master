import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import i18n from '../../i18n';
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
  labeledAny: 7,
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
      <span data-testid="labeledany">{state.result?.labeledAny ?? ''}</span>
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
      <span data-testid="errors">{state.errors?.join('|') ?? ''}</span>
      <span data-testid="total">{state.result?.total ?? ''}</span>
    </div>
  );
}

function EnabledProbe() {
  const [enabled, setEnabled] = useState(true);
  const state = useLabelizerPreview({
    enabled,
    feedSourceId: 1,
    rules: RULES,
    slotIds: {},
  });
  return (
    <div>
      <button onClick={() => setEnabled(false)}>disable</button>
      <span data-testid="total">{state.result?.total ?? ''}</span>
      <span data-testid="errors">{state.errors?.join('|') ?? ''}</span>
    </div>
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
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
      { timeout: 5000 },
    )).toBeTruthy();
    expect(calls).toBe(1);
    expect(
      document.querySelector('[data-testid="labeledany"]')?.textContent,
    ).toBe('7');
  });

  it('sends no request when disabled', async () => {
    const calls: string[] = [];
    stubFetch((url) => {
      calls.push(url);
      return jsonResponse({});
    });
    render(<Probe rules={RULES} enabled={false} />);
    await act(async () => { vi.advanceTimersByTime(600); });
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
      { timeout: 5000 },
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
    // advance past debounce → first fetch fires
    await act(async () => { vi.advanceTimersByTime(600); });
    expect(calls).toBe(1);
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
    // advance past debounce → second fetch fires (resolves immediately)
    await act(async () => { vi.advanceTimersByTime(600) });
    expect(await waitFor(
      () => expect(screen.getByTestId('total').textContent).toBe('2'),
      { timeout: 5000 },
    )).toBeTruthy();
    // advance past the slow first response → guard discards it
    await act(async () => { vi.advanceTimersByTime(1500) });
    expect(screen.getByTestId('total').textContent).toBe('2');
    expect(calls).toBe(2);
  }, 10000);

  it('clears a previous 422 error when a new request starts', async () => {
    let calls = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        if (calls === 1) return jsonResponse({ errors: ['bad rule'] }, 422);
        return new Promise<Response>((resolve) => {
          setTimeout(() => resolve(jsonResponse(RESULT)), 800);
        });
      }
      return jsonResponse({});
    });
    render(<DraftProbe />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="errors"]')?.textContent)
        .toBe('bad rule'),
      { timeout: 5000 },
    )).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
    // the second request has started and is still in flight — the stale
    // 422 must already be cleared at request start
    expect(await waitFor(() => expect(calls).toBe(2), { timeout: 5000 })).toBeTruthy();
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="errors"]')?.textContent).toBe(''),
      { timeout: 5000 },
    )).toBeTruthy();
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('10'),
      { timeout: 5000 },
    )).toBeTruthy();
  }, 10000);

  it('clears the previous result when the request is rejected with 422', async () => {
    let calls = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        return calls === 1 ? jsonResponse(RESULT) : jsonResponse({ errors: ['nope'] }, 422);
      }
      return jsonResponse({});
    });
    render(<DraftProbe />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('10'),
      { timeout: 5000 },
    )).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /change draft/i }));
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe(''),
      { timeout: 5000 },
    )).toBeTruthy();
    expect(document.querySelector('[data-testid="errors"]')?.textContent).toBe('nope');
  }, 10000);

  it('discards in-flight responses once the preview is disabled', async () => {
    let calls = 0;
    let release!: (response: Response) => void;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      }
      return jsonResponse({});
    });
    render(<EnabledProbe />);
    await waitFor(() => expect(calls).toBe(1), { timeout: 5000 });
    await userEvent.click(screen.getByRole('button', { name: /disable/i }));
    act(() => release(jsonResponse(RESULT)));
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(screen.getByTestId('total').textContent).toBe('');
  }, 10000);

  it('uses a localized fallback when a 422 carries no errors or detail', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({}, 422);
      }
      return jsonResponse({});
    });
    await i18n.loadNamespaces(['customLabels']);
    await i18n.changeLanguage('de');
    try {
      render(<Probe rules={RULES} />);
      expect(await waitFor(
        () => expect(document.querySelector('[data-testid="errors"]')?.textContent)
          .toBe('Die Regeln sind ungültig.'),
        { timeout: 5000 },
      )).toBeTruthy();
    } finally {
      await i18n.changeLanguage('en');
    }
  }, 10000);
});

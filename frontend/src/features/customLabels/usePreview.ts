import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError, apiPost } from '../../api/client';
import type { SlotRule } from './scopeMerge';

export type PreviewRuleStats = { matched: number; labeled: number; sample: string[] };

export type PreviewResult = {
  total: number;
  labeledAny?: number;
  rules: Record<string, PreviewRuleStats>;
  slots: Record<string, { labeled: number; coverage: number; rules: string[] }>;
};

export type PreviewState = {
  result: PreviewResult | null;
  isPending: boolean;
  errors: string[] | null;
  unavailable: boolean;
};

const DEBOUNCE_MS = 500;

/**
 * Live preview of draft rules+values against the feed's staged products.
 * Mirrors the FilterUI live-preview pattern: debounced tick, apiPost, local
 * state; only the newest response is applied (sequence guard).
 */
export function useLabelizerPreview(input: {
  enabled: boolean;
  feedSourceId: number | undefined;
  rules: SlotRule[];
  slotIds: Record<string, string>;
}): PreviewState {
  const { enabled, feedSourceId, rules, slotIds } = input;
  const { t } = useTranslation('customLabels');
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [errors, setErrors] = useState<string[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);

  const draftKey = JSON.stringify({ rules, slotIds });

  const payloadRef = useRef({ feedSourceId, rules, slotIds });
  payloadRef.current = { feedSourceId, rules, slotIds };

  useEffect(() => () => {
    seq.current++;
  }, []);

  useEffect(() => {
    if (!enabled) {
      seq.current++;
      setResult(null);
      setErrors(null);
      setUnavailable(false);
      setIsPending(false);
      return;
    }
    const timer = setTimeout(() => setTick((n) => n + 1), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [enabled, draftKey]);

  useEffect(() => {
    if (!enabled || tick === 0) return;
    const mySeq = ++seq.current;
    const { feedSourceId, rules, slotIds } = payloadRef.current;
    setIsPending(true);
    setErrors(null);
    void apiPost<PreviewResult>('/plugins/custom_labels/preview', {
      feed_source_id: feedSourceId,
      rules,
      slotIds,
      sample_size: 5,
    })
      .then((res) => {
        if (mySeq !== seq.current) return;
        setResult(res);
        setErrors(null);
        setUnavailable(false);
        setIsPending(false);
      })
      .catch((err: unknown) => {
        if (mySeq !== seq.current) return;
        if (err instanceof ApiError && err.status === 422) {
          setErrors(err.errors ?? [err.detail ?? t('previewInvalidRules')]);
          setResult(null);
          setUnavailable(false);
        } else {
          setUnavailable(true);
        }
        setIsPending(false);
      });
  }, [tick, enabled, t]);

  return { result, isPending, errors, unavailable };
}

import { useEffect, useRef, type RefObject } from 'react';

export const ROW_HEIGHT = 34;
export const VIEWPORT_ROWS = 10;
export const OVERSCAN = 5;

/** [start, end) slice of rows to render for a scrollTop, fixed-row windowing. */
export function windowRange(scrollTop: number, totalRows: number): [number, number] {
  const firstRow = Math.floor(scrollTop / ROW_HEIGHT);
  const first = Math.min(totalRows, Math.max(0, firstRow - OVERSCAN));
  const last = Math.min(totalRows, firstRow + VIEWPORT_ROWS + OVERSCAN);
  return [first, Math.max(first, last)];
}

export function availabilityColor(
  availability: string | null | undefined,
): 'green' | 'red' | 'gray' {
  if (availability === 'in_stock') return 'green';
  if (availability === 'out_of_stock') return 'red';
  return 'gray';
}

/**
 * Bidirectional scrollTop sync between the values textarea and the preview
 * viewport. A guard flag (released on the next animation frame) stops the
 * programmatic set on the target from re-triggering the handler.
 */
export function useSyncedScroll(
  textareaRef: RefObject<HTMLTextAreaElement | null>,
  previewRef: RefObject<HTMLDivElement | null>,
  onScrollTopChange: (top: number) => void,
): void {
  const callbackRef = useRef(onScrollTopChange);
  callbackRef.current = onScrollTopChange;
  useEffect(() => {
    const textarea = textareaRef.current;
    const preview = previewRef.current;
    if (!textarea || !preview) return;
    let syncing = false;
    const release = () => requestAnimationFrame(() => { syncing = false; });
    const onTextareaScroll = () => {
      if (syncing) return;
      syncing = true;
      preview.scrollTop = textarea.scrollTop;
      callbackRef.current(textarea.scrollTop);
      release();
    };
    const onPreviewScroll = () => {
      if (syncing) return;
      syncing = true;
      textarea.scrollTop = preview.scrollTop;
      callbackRef.current(preview.scrollTop);
      release();
    };
    textarea.addEventListener('scroll', onTextareaScroll);
    preview.addEventListener('scroll', onPreviewScroll);
    return () => {
      textarea.removeEventListener('scroll', onTextareaScroll);
      preview.removeEventListener('scroll', onPreviewScroll);
    };
  }, [textareaRef, previewRef]);
}

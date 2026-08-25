# Task 7 Report

## Status

DONE

## Summary

Implemented `HttpFetcher` in `backend/app/ingest/fetch.py` with `FetchError`,
60 s default timeout, 500 MB default size limit, streaming accumulation, and
optional Basic Auth. Tests in `backend/tests/test_fetch.py` use
`httpx.MockTransport` via an injectable `_client` test seam.

## Files changed

- `backend/app/ingest/fetch.py` — `FetchError`, `HttpFetcher.fetch(url,
  basic_auth=None, _client=None)`; streams response, aborts over `max_bytes`,
  wraps timeout/HTTP errors into `FetchError`, non-200 raises with status.
- `backend/tests/test_fetch.py` — 6 tests: success bytes, timeout, 404, 500,
  size limit, Basic Auth header.

## Verification

From `backend/`:

```text
uv run pytest tests/test_fetch.py -x -q
6 passed, 1 warning in 0.02s
```

## Concerns

- `fetch()` accepts an extra `_client` keyword (test seam for MockTransport);
  spec signature is `fetch(url, basic_auth=None)` — the seam is additive and
  defaults to None, preserving the spec'd call shape.
- Only HTTP 200 is accepted (not 2xx range); spec says "non-2xx raises", so
  redirects are not followed explicitly — httpx follows redirects by default
  only when configured; default client does not follow redirects.

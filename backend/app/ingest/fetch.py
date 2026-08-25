from __future__ import annotations

import httpx


class FetchError(Exception):
    pass


class HttpFetcher:
    def __init__(self, timeout: float = 60.0, max_bytes: int = 500 * 1024 * 1024):
        self.timeout = timeout
        self.max_bytes = max_bytes

    async def fetch(
        self,
        url: str,
        basic_auth: tuple[str, str] | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> bytes:
        auth = httpx.BasicAuth(*basic_auth) if basic_auth else None
        own_client = _client is None
        if own_client:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
            )
        else:
            client = _client

        try:
            async with client.stream("GET", url, auth=auth) as response:
                if response.status_code != 200:
                    raise FetchError(
                        f"HTTP {response.status_code} from {url}"
                    )

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise FetchError(
                            f"Response size limit exceeded: {self.max_bytes} bytes"
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise FetchError(f"timeout fetching {url}") from exc
        except FetchError:
            raise
        except httpx.HTTPError as exc:
            raise FetchError(f"HTTP error fetching {url}: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()

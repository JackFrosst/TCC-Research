import time

import httpx

from ..config import Settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    settings: Settings,
    **kwargs,
) -> httpx.Response:
    last_response: httpx.Response | None = None
    for attempt in range(settings.academic_max_retries + 1):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.RequestError:
            if attempt >= settings.academic_max_retries:
                raise
        else:
            last_response = response
            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt >= settings.academic_max_retries:
                return response
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(min(float(retry_after), 30))
                continue
        time.sleep(settings.academic_retry_backoff_seconds * (2**attempt))
    assert last_response is not None
    return last_response

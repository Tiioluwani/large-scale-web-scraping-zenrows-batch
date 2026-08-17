"""
DIY comparison (no Zenrows involved).

Plain asyncio/aiohttp scraper hitting the same Cloudflare-protected URL as
01_cloudflare_target.py, with retry logic, a concurrency semaphore, and
basic error tracking. This is not expected to clear Cloudflare's managed
challenge - that's the point: it exists to show a real line count and
complexity comparison against the Batch API version.
"""
import asyncio
import pathlib
import time
from dataclasses import dataclass
from typing import List, Optional

import aiohttp

TARGET_URLS = [
    "https://www.scrapingcourse.com/cloudflare-challenge",
] * 5  # repeated so the concurrency/retry machinery actually gets exercised

MAX_CONCURRENCY = 3
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5
REQUEST_TIMEOUT_S = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FetchResult:
    url: str
    success: bool = False
    status_code: Optional[int] = None
    attempts: int = 0
    error: Optional[str] = None
    elapsed: float = 0.0


async def fetch_with_retries(session, url, semaphore, results):
    async with semaphore:
        started = time.time()
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S),
                ) as resp:
                    await resp.text()
                    result = FetchResult(
                        url=url,
                        success=resp.status == 200,
                        status_code=resp.status,
                        attempts=attempt,
                        elapsed=time.time() - started,
                    )
                    if resp.status != 200:
                        result.error = f"non-200 status: {resp.status}"
                    results.append(result)
                    return
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)

        results.append(
            FetchResult(
                url=url,
                success=False,
                attempts=MAX_RETRIES,
                error=str(last_exc),
                elapsed=time.time() - started,
            )
        )


async def run():
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results: List[FetchResult] = []
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_with_retries(session, url, semaphore, results) for url in TARGET_URLS]
        await asyncio.gather(*tasks)
    return results


def main():
    started = time.time()
    results = asyncio.run(run())
    elapsed = time.time() - started

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"Fetched {len(results)} URLs in {elapsed:.1f}s")
    print(f"Successful: {len(successful)}  Failed: {len(failed)}")
    for r in failed:
        print(f"  FAILED url={r.url} attempts={r.attempts} status={r.status_code} error={r.error}")

    print(
        "\nExpected outcome: Cloudflare's managed challenge blocks a plain "
        "HTTP client, so most or all attempts should fail here even with "
        "retries - that's the comparison point against 01_cloudflare_target.py."
    )

    line_count = len(pathlib.Path(__file__).read_text(encoding="utf-8").splitlines())
    print(f"\n06_diy_comparison.py line count: {line_count}")


if __name__ == "__main__":
    main()

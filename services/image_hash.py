from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from io import BytesIO

import httpx
import imagehash
from PIL import Image


@dataclass(frozen=True)
class ImageFingerprint:
    md5: str
    phash: str


_URL_CACHE: dict[str, ImageFingerprint] = {}
_URL_LOCKS: dict[str, asyncio.Lock] = {}


async def fingerprint_urls(urls: list[str]) -> dict[str, ImageFingerprint]:
    unique_urls = list(dict.fromkeys(urls))
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_headers()) as client:
        fingerprints = await asyncio.gather(*(fingerprint_url(url, client) for url in unique_urls))
    return dict(zip(unique_urls, fingerprints, strict=True))


async def fingerprint_url(url: str, client: httpx.AsyncClient | None = None) -> ImageFingerprint:
    if url in _URL_CACHE:
        return _URL_CACHE[url]

    lock = _URL_LOCKS.setdefault(url, asyncio.Lock())
    async with lock:
        if url in _URL_CACHE:
            return _URL_CACHE[url]
        image_bytes = await _download_bytes(url, client)
        fingerprint = fingerprint_bytes(image_bytes)
        _URL_CACHE[url] = fingerprint
        return fingerprint


def fingerprint_bytes(image_bytes: bytes) -> ImageFingerprint:
    md5 = hashlib.md5(image_bytes).hexdigest()
    with Image.open(BytesIO(image_bytes)) as image:
        phash = str(imagehash.phash(image.convert("RGB")))
    return ImageFingerprint(md5=md5, phash=phash)


def phash_distance(left: str, right: str) -> int:
    return int(imagehash.hex_to_hash(left) - imagehash.hex_to_hash(right))


def clear_fingerprint_cache() -> None:
    _URL_CACHE.clear()
    _URL_LOCKS.clear()


async def _download_bytes(url: str, client: httpx.AsyncClient | None = None) -> bytes:
    if client is not None:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_headers()) as owned_client:
        response = await owned_client.get(url)
        response.raise_for_status()
        return response.content


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }

from io import BytesIO

import httpx
import pytest
from PIL import Image

from services.image_hash import clear_fingerprint_cache, fingerprint_bytes, fingerprint_url, phash_distance


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    clear_fingerprint_cache()
    yield
    clear_fingerprint_cache()


@pytest.mark.asyncio
async def test_fingerprint_url_downloads_same_url_once(respx_mock):
    route = respx_mock.get("https://example.test/option.png").mock(
        return_value=httpx.Response(200, content=_png_bytes("red"))
    )

    first = await fingerprint_url("https://example.test/option.png")
    second = await fingerprint_url("https://example.test/option.png")

    assert first == second
    assert route.call_count == 1


def test_fingerprint_bytes_sets_md5_and_phash():
    fingerprint = fingerprint_bytes(_png_bytes("blue"))

    assert len(fingerprint.md5) == 32
    assert len(fingerprint.phash) == 16
    assert phash_distance("0000000000000000", "000000000000000f") == 4


def _png_bytes(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (24, 24), color=color).save(output, format="PNG")
    return output.getvalue()

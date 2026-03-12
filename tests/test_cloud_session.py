import pytest

from zepp_life_mcp.adapters.cloud_session import CloudSessionAdapter


def test_decode_band_summary_from_dict_and_base64():
    adapter = CloudSessionAdapter(app_token="t1", user_id="u1")
    assert adapter._decode_band_summary({"stp": {"ttl": 1}}) == {"stp": {"ttl": 1}}


def test_parse_heart_rate_bytes():
    adapter = CloudSessionAdapter(app_token="t1", user_id="u1")
    import base64

    samples = adapter._parse_heart_rate_data(
        base64.b64encode(bytes([0, 60, 61, 255, 254, 30])).decode()
    )
    assert samples == [(1, 60), (2, 61), (5, 30)]


@pytest.mark.asyncio
async def test_get_user_info_requires_client():
    adapter = CloudSessionAdapter(app_token="t1", user_id="u1")
    assert await adapter._get_user_info() is None

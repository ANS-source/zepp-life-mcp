from datetime import datetime

from zepp_life_mcp.models import BodyMeasurement, DailyActivity, HeartRateSample
from zepp_life_mcp.services.query_service import QueryService
from zepp_life_mcp.storage import Database


def test_storage_and_query_roundtrip(tmp_path):
    db = Database(tmp_path / "test.db")

    activity = DailyActivity(
        id="a1",
        provider="zepp_life",
        source_type="cloud_session",
        user_id="u1",
        date="2022-02-13",
        steps=1000,
        distance_m=900,
        active_kcal=60,
    )
    hr = HeartRateSample(
        id="hr1",
        provider="zepp_life",
        source_type="cloud_session",
        user_id="u1",
        timestamp=datetime(2022, 2, 13, 12, 0, 0),
        bpm=72,
        sample_type="passive",
    )
    body = BodyMeasurement(
        id="w1",
        provider="zepp_life",
        source_type="cloud_session",
        user_id="u1",
        timestamp=datetime(2022, 2, 13, 7, 0, 0),
        weight_kg=90.5,
        bmi=26.0,
    )

    db.insert_daily_activity(activity)
    db.insert_heart_rate_sample(hr)
    db.insert_body_measurement(body)

    query = QueryService(db, "u1")
    assert len(query.get_daily_summaries("2022-02-13", "2022-02-13")) == 1
    assert len(query.get_heart_rate_samples("2022-02-13", "2022-02-13")) == 1
    assert len(query.get_body_measurements("2022-02-13", "2022-02-13")) == 1

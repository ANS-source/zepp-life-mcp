"""Cloud session adapter for direct API access to Zepp Life."""

import base64
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import httpx

from zepp_life_mcp.adapters.base import DataAdapter
from zepp_life_mcp.models import (
    BodyMeasurement,
    DailyActivity,
    HeartRateSample,
    ReadinessSample,
    SleepSession,
    SleepStage,
    StressSample,
    Workout,
)

logger = logging.getLogger(__name__)

# Basal metabolism estimate observed in the Zepp app for this specific user/profile
# (not a generic formula). The cloud API exposes no basal/total calorie field, only
# active calories. Recalculate manually if body weight changes significantly.
BMR_CONSTANT_KCAL = 2022


def _score_or_none(value: Any) -> int | None:
    """Coerce a 0-100 score field to int, or None if missing/sentinel/out-of-range.

    Zepp uses 255 (and other out-of-range values) as sentinels for "not computed"
    on these fields, and the API sometimes returns them as strings rather than
    numbers, so coerce first and only then check the valid range.
    """
    if value is None:
        return None
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 100:
        return None
    return score


class CloudSessionAdapter(DataAdapter):
    """Adapter for accessing Zepp Life cloud APIs."""

    ZEPP_API_BASE = "https://api-mifit.huami.com"
    ZEPP_AUTH_BASE = "https://account.huami.com"
    ZEPP_USER_API = "https://api-user.huami.com"
    ZEPP_WEIGHT_API = "https://api-mifit.zepp.com"

    def __init__(
        self,
        app_token: str | None = None,
        user_id: str | None = None,
        region: str = "eu",
    ):
        self.app_token = app_token
        self.user_id = user_id
        self.region = region
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._available_types: list[str] = []

    async def connect(self) -> bool:
        if not self.app_token:
            logger.error("No app_token provided")
            return False

        self._client = httpx.AsyncClient(
            base_url=self.ZEPP_API_BASE,
            headers={
                "apptoken": self.app_token,
                "appPlatform": "web",
                "appname": "com.xiaomi.hm.health",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        try:
            user_info = await self._get_user_info()
            if user_info:
                self.user_id = user_info.get("user_id") or self.user_id
                self._connected = True
                self._available_types = await self._discover_data_types()
                logger.info(f"Connected to Zepp API as user {self.user_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")

        return False

    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    def get_user_id(self) -> str | None:
        return self.user_id

    def get_available_data_types(self) -> list[str]:
        return self._available_types.copy()

    def _parse_band_data(self, data: dict) -> Any:
        """Parse band data from API response."""
        try:
            if "data" in data:
                encoded = data["data"]
                if isinstance(encoded, (list, dict)):
                    return encoded
                decoded = base64.b64decode(encoded)
                return json.loads(decoded)
        except Exception as e:
            logger.error(f"Failed to parse band data: {e}")

        return data

    def _decode_band_summary(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            return json.loads(base64.b64decode(value))
        except Exception:
            return {}

    def _iter_band_summary_entries(self, payload: Any) -> list[tuple[str, dict[str, Any]]]:
        entries: list[tuple[str, dict[str, Any]]] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                date_str = str(item.get("date_time") or item.get("date") or "")
                summary = self._decode_band_summary(item.get("summary"))
                if date_str and summary:
                    entries.append((date_str, summary))
        elif isinstance(payload, dict):
            for date_str, day_data in payload.items():
                if isinstance(day_data, dict):
                    entries.append((str(date_str), day_data))
        return entries

    def _parse_heart_rate_data(self, encoded_data: str) -> list[tuple[int, int]]:
        try:
            decoded = base64.b64decode(encoded_data)
            hr_values: list[tuple[int, int]] = []
            for i, value in enumerate(decoded):
                if value not in (255, 254, 0) and 30 <= value <= 240:
                    hr_values.append((i, value))
            return hr_values
        except Exception as e:
            logger.error(f"Failed to parse heart rate data: {e}")
            return []

    async def _iter_events(
        self,
        event_type: str,
        sub_type: str,
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> AsyncIterator[dict]:
        """Iterate raw event items for an eventType/subType within a timestamp range.

        Without pagination this API only returns the account's oldest 20 events, so
        this jumps straight to start_ts_ms via the `next` cursor and pages forward
        until the window is covered, instead of crawling from the beginning.
        """
        if not self._client:
            return
            yield

        cursor = start_ts_ms
        seen_cursors: set[int] = set()

        while True:
            try:
                response = await self._client.get(
                    f"{self.ZEPP_WEIGHT_API}/v2/users/me/events",
                    params={"eventType": event_type, "subType": sub_type, "next": cursor},
                )
            except Exception as e:
                logger.error(f"Error fetching {event_type} events: {e}")
                return

            if response.status_code != 200:
                logger.error(f"Failed to fetch {event_type} events: {response.status_code}")
                return

            body = response.json()
            items = body.get("items", [])

            for item in items:
                ts = item.get("timestamp", 0)
                if start_ts_ms <= ts <= end_ts_ms:
                    yield item

            next_cursor = body.get("next")
            reached_end = bool(items) and items[-1].get("timestamp", 0) >= end_ts_ms
            if not items or not next_cursor or next_cursor in seen_cursors or reached_end:
                return

            seen_cursors.add(next_cursor)
            cursor = next_cursor

    async def _get_user_info(self) -> dict | None:
        if not self._client:
            return None

        try:
            response = await self._client.get(
                "/v1/sport/run/history.json",
                params={"limit": 1},
            )
            if response.status_code == 200:
                return {"user_id": self.user_id, "valid": True}
        except Exception as e:
            logger.error(f"Failed to validate token: {e}")

        return None

    async def _discover_data_types(self) -> list[str]:
        types = []

        try:
            response = await self._client.get(
                "/v1/data/band_data.json",
                params={
                    "query_type": "summary",
                    "device_type": "android_phone",
                    "userid": self.user_id,
                    "from_date": "2020-01-01",
                    "to_date": datetime.now().strftime("%Y-%m-%d"),
                },
            )
            if response.status_code == 200:
                data = response.json()
                parsed = self._parse_band_data(data)
                for _, day_data in self._iter_band_summary_entries(parsed):
                    if day_data.get("stp"):
                        types.append("daily_activity")
                    if day_data.get("slp"):
                        types.append("sleep")
                    break
        except Exception as e:
            logger.warning(f"Failed to discover daily_activity/sleep availability: {e}")

        try:
            response = await self._client.get(
                "/v1/sport/run/history.json",
                params={"limit": 1},
            )
            if response.status_code == 200:
                types.append("workouts")
        except Exception as e:
            logger.warning(f"Failed to discover workouts availability: {e}")

        try:
            response = await self._client.get(
                "/v1/data/band_data.json",
                params={
                    "query_type": "detail",
                    "device_type": "android_phone",
                    "userid": self.user_id,
                    "from_date": "2020-01-01",
                    "to_date": datetime.now().strftime("%Y-%m-%d"),
                },
            )
            if response.status_code == 200:
                for item in response.json().get("data", []):
                    if self._parse_heart_rate_data(item.get("data_hr", "")):
                        types.append("heart_rate")
                        break
        except Exception as e:
            logger.warning(f"Failed to discover heart_rate availability: {e}")

        try:
            url = f"{self.ZEPP_WEIGHT_API}/users/{self.user_id}/members/-1/weightRecords?limit=1"
            response = await self._client.get(url)
            if response.status_code == 200:
                types.append("body_measurements")
        except Exception as e:
            logger.warning(f"Failed to discover body_measurements availability: {e}")

        try:
            response = await self._client.get(
                f"{self.ZEPP_WEIGHT_API}/v2/users/me/events",
                params={"eventType": "readiness", "subType": "watch_score"},
            )
            if response.status_code == 200 and response.json().get("items"):
                types.append("readiness")
        except Exception as e:
            logger.warning(f"Failed to discover readiness availability: {e}")

        try:
            response = await self._client.get(
                f"{self.ZEPP_WEIGHT_API}/v2/users/me/events",
                params={"eventType": "all_day_stress", "subType": "all_day_stress"},
            )
            if response.status_code == 200 and response.json().get("items"):
                types.append("stress")
        except Exception as e:
            logger.warning(f"Failed to discover stress availability: {e}")

        return list(set(types))

    async def iter_daily_activity(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[DailyActivity]:
        if not self._client or not self.is_connected():
            return
            yield

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)
            start_date = start_dt.strftime("%Y-%m-%d")

        try:
            response = await self._client.get(
                "/v1/data/band_data.json",
                params={
                    "query_type": "summary",
                    "device_type": "android_phone",
                    "userid": self.user_id,
                    "from_date": start_date,
                    "to_date": end_date,
                },
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch activity: {response.status_code}")
                return

            data = response.json()
            parsed_data = self._parse_band_data(data)

            for date_str, day_data in self._iter_band_summary_entries(parsed_data):
                steps_data = day_data.get("stp", {})
                if steps_data:
                    active_kcal = steps_data.get("cal", 0)
                    yield DailyActivity(
                        id=f"cloud_{date_str}",
                        provider="zepp_life",
                        source_type="cloud_session",
                        user_id=self.user_id or "unknown",
                        date=date_str,
                        steps=steps_data.get("ttl", 0),
                        distance_m=steps_data.get("dis", 0),
                        active_kcal=active_kcal,
                        total_kcal=active_kcal + BMR_CONSTANT_KCAL,
                    )

        except Exception as e:
            logger.error(f"Error fetching activity: {e}")

    async def iter_sleep_sessions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[SleepSession]:
        if not self._client or not self.is_connected():
            return
            yield

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)
            start_date = start_dt.strftime("%Y-%m-%d")

        try:
            response = await self._client.get(
                "/v1/data/band_data.json",
                params={
                    "query_type": "summary",
                    "device_type": "android_phone",
                    "userid": self.user_id,
                    "from_date": start_date,
                    "to_date": end_date,
                },
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch sleep: {response.status_code}")
                return

            data = response.json()
            parsed_data = self._parse_band_data(data)

            for date_str, day_data in self._iter_band_summary_entries(parsed_data):
                sleep_data = day_data.get("slp", {})
                if not sleep_data:
                    continue

                start_ts = sleep_data.get("st")
                end_ts = sleep_data.get("ed")
                asleep_minutes = sleep_data.get("dp", 0) + sleep_data.get("lt", 0)

                if not start_ts or not end_ts or (end_ts <= start_ts and asleep_minutes <= 0):
                    continue

                start_dt = datetime.fromtimestamp(start_ts)
                end_dt = datetime.fromtimestamp(end_ts)
                duration = int((end_dt - start_dt).total_seconds() / 60)
                if duration < 0:
                    duration = asleep_minutes

                stages = []
                stage_data = sleep_data.get("stage", [])
                rem_minutes = 0
                awake_minutes = 0
                wake_count = 0
                for stage in stage_data:
                    mode = stage.get("mode")
                    if mode == 5:
                        stage_type = "deep"
                    elif mode == 4:
                        stage_type = "light"
                    elif mode == 8:
                        stage_type = "rem"
                    else:
                        stage_type = "awake"
                    stage_stop = stage.get("stop", stage.get("end", 0))
                    stage_start = stage.get("start", 0)
                    stage_duration = max(0, stage_stop - stage_start + 1) if stage_stop >= stage_start else 0

                    if stage_type == "rem":
                        rem_minutes += stage_duration
                    elif stage_type == "awake":
                        wake_count += 1
                        awake_minutes += stage_duration

                    if stage_duration:
                        stages.append(SleepStage(stage=stage_type, minutes=stage_duration))

                total_duration = max(duration, asleep_minutes)
                yield SleepSession(
                    id=f"cloud_sleep_{date_str}",
                    provider="zepp_life",
                    source_type="cloud_session",
                    user_id=self.user_id or "unknown",
                    sleep_id=f"sleep_{date_str}",
                    start_at=start_dt,
                    end_at=end_dt,
                    duration_minutes=total_duration,
                    time_asleep_minutes=asleep_minutes,
                    time_awake_minutes=awake_minutes,
                    sleep_score=_score_or_none(sleep_data.get("ss")),
                    rem_minutes=rem_minutes,
                    wake_count=wake_count,
                    stages=stages,
                )

        except Exception as e:
            logger.error(f"Error fetching sleep: {e}")

    async def iter_heart_rate(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[HeartRateSample]:
        if not self._client or not self.is_connected():
            return
            yield

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)
            start_date = start_dt.strftime("%Y-%m-%d")

        try:
            response = await self._client.get(
                "/v1/data/band_data.json",
                params={
                    "query_type": "detail",
                    "device_type": "android_phone",
                    "userid": self.user_id,
                    "from_date": start_date,
                    "to_date": end_date,
                },
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch heart rate: {response.status_code}")
                return

            data = response.json()

            for item in data.get("data", []):
                date_str = item.get("date_time", "")
                hr_data = item.get("data_hr", "")

                if hr_data:
                    hr_values = self._parse_heart_rate_data(hr_data)
                    base_time = datetime.strptime(date_str, "%Y-%m-%d")

                    for minute, bpm in hr_values:
                        timestamp = base_time + timedelta(minutes=minute)
                        yield HeartRateSample(
                            id=f"cloud_hr_{date_str}_{minute}",
                            provider="zepp_life",
                            source_type="cloud_session",
                            user_id=self.user_id or "unknown",
                            timestamp=timestamp,
                            bpm=bpm,
                            sample_type="passive",
                        )

        except Exception as e:
            logger.error(f"Error fetching heart rate: {e}")

    async def iter_resting_heart_rate(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[HeartRateSample]:
        """Iterate over resting heart rate samples derived from nightly sleep summaries."""
        if not self._client or not self.is_connected():
            return
            yield

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)
            start_date = start_dt.strftime("%Y-%m-%d")

        try:
            response = await self._client.get(
                "/v1/data/band_data.json",
                params={
                    "query_type": "summary",
                    "device_type": "android_phone",
                    "userid": self.user_id,
                    "from_date": start_date,
                    "to_date": end_date,
                },
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch resting heart rate: {response.status_code}")
                return

            data = response.json()
            parsed_data = self._parse_band_data(data)

            for date_str, day_data in self._iter_band_summary_entries(parsed_data):
                sleep_data = day_data.get("slp", {})
                rhr = sleep_data.get("rhr")
                if not rhr or rhr <= 0:
                    continue

                wake_ts = sleep_data.get("ed")
                timestamp = (
                    datetime.fromtimestamp(wake_ts)
                    if wake_ts
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                yield HeartRateSample(
                    id=f"cloud_rhr_{date_str}",
                    provider="zepp_life",
                    source_type="cloud_session",
                    user_id=self.user_id or "unknown",
                    timestamp=timestamp,
                    bpm=rhr,
                    sample_type="resting",
                )

        except Exception as e:
            logger.error(f"Error fetching resting heart rate: {e}")

    async def iter_readiness(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[ReadinessSample]:
        """Iterate over daily readiness/recovery scores."""
        if not self._client or not self.is_connected():
            return
            yield

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)
            start_date = start_dt.strftime("%Y-%m-%d")

        start_ts_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts_ms = (
            int((datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp() * 1000)
            - 1
        )

        async for item in self._iter_events("readiness", "watch_score", start_ts_ms, end_ts_ms):
            value = item.get("value", {})
            ts = item.get("timestamp", 0)
            if not ts:
                continue
            timestamp = datetime.fromtimestamp(ts / 1000)
            date_str = timestamp.strftime("%Y-%m-%d")

            yield ReadinessSample(
                id=f"cloud_readiness_{date_str}",
                provider="zepp_life",
                source_type="cloud_session",
                user_id=self.user_id or "unknown",
                timestamp=timestamp,
                readiness_score=_score_or_none(value.get("rdnsScore")),
                physical_score=_score_or_none(value.get("phyScore")),
                mental_score=_score_or_none(value.get("mentScore")),
                rhr_score=_score_or_none(value.get("rhrScore")),
                ahi_score=_score_or_none(value.get("ahiScore")),
                afib_score=_score_or_none(value.get("afibScore")),
                skin_temp_score=_score_or_none(value.get("skinTempScore")),
                sleep_hrv=value.get("sleepHRV"),
                hrv_score=_score_or_none(value.get("hrvScore")),
                hrv_baseline=value.get("hrvBaseline"),
            )

    async def iter_stress(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[StressSample]:
        """Iterate over daily stress score aggregates."""
        if not self._client or not self.is_connected():
            return
            yield

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)
            start_date = start_dt.strftime("%Y-%m-%d")

        start_ts_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts_ms = (
            int((datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp() * 1000)
            - 1
        )

        async for item in self._iter_events(
            "all_day_stress", "all_day_stress", start_ts_ms, end_ts_ms
        ):
            value = item.get("value", {})
            avg_stress = value.get("avgStress")
            if avg_stress is None:
                continue
            avg_stress = int(avg_stress)

            ts = item.get("timestamp", 0)
            if not ts:
                continue
            timestamp = datetime.fromtimestamp(ts / 1000)
            date_str = timestamp.strftime("%Y-%m-%d")

            if avg_stress < 30:
                level = "low"
            elif avg_stress < 60:
                level = "medium"
            else:
                level = "high"

            min_stress = value.get("minStress")
            max_stress = value.get("maxStress")

            yield StressSample(
                id=f"cloud_stress_{date_str}",
                provider="zepp_life",
                source_type="cloud_session",
                user_id=self.user_id or "unknown",
                timestamp=timestamp,
                stress_score=avg_stress,
                level=level,
                min_stress=int(min_stress) if min_stress is not None else None,
                max_stress=int(max_stress) if max_stress is not None else None,
            )

    async def iter_workouts(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[Workout]:
        if not self._client or not self.is_connected():
            return
            yield

        try:
            response = await self._client.get(
                "/v1/sport/run/history.json",
                params={"limit": 100},
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch workouts: {response.status_code}")
                return

            data = response.json()

            for item in data.get("data", {}).get("summary", []):
                start_time = item.get("start_time")
                end_time = item.get("end_time")
                run_time = item.get("run_time", 0)
                end_ts = int(float(end_time)) if end_time else None
                duration_sec = int(float(run_time)) if run_time else 0
                start_ts = (
                    int(float(start_time))
                    if start_time
                    else (end_ts - duration_sec if end_ts else None)
                )

                if start_ts:
                    workout_date = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d")

                    if start_date and workout_date < start_date:
                        continue
                    if end_date and workout_date > end_date:
                        continue

                duration_min = int(float(run_time)) // 60 if run_time else 0

                yield Workout(
                    id=f"cloud_{item.get('trackid')}",
                    provider="zepp_life",
                    source_type="cloud_session",
                    user_id=self.user_id or "unknown",
                    workout_id=str(item.get("trackid")),
                    activity_type=str(item.get("type", "unknown")),
                    start_at=datetime.fromtimestamp(start_ts) if start_ts else datetime.now(),
                    end_at=datetime.fromtimestamp(end_ts) if end_ts else datetime.now(),
                    duration_minutes=duration_min,
                    distance_m=float(item.get("dis", 0)) if item.get("dis") else None,
                    calories_kcal=float(item.get("calorie", 0)) if item.get("calorie") else None,
                    avg_heart_rate_bpm=int(float(item.get("avg_heart_rate")))
                    if item.get("avg_heart_rate")
                    else None,
                    max_heart_rate_bpm=int(float(item.get("max_heart_rate")))
                    if item.get("max_heart_rate")
                    else None,
                )

        except Exception as e:
            logger.error(f"Error fetching workouts: {e}")

    async def iter_body_measurements(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[BodyMeasurement]:
        if not self._client or not self.is_connected():
            return
            yield

        try:
            url = f"{self.ZEPP_WEIGHT_API}/users/{self.user_id}/members/-1/weightRecords"
            params = {"limit": 200}

            response = await self._client.get(url, params=params)

            if response.status_code != 200:
                logger.error(f"Failed to fetch weight: {response.status_code}")
                return

            data = response.json()

            for item in data.get("items", []):
                record_time = item.get("generatedTime")
                if record_time:
                    record_date = datetime.fromtimestamp(record_time).strftime("%Y-%m-%d")

                    if start_date and record_date < start_date:
                        continue
                    if end_date and record_date > end_date:
                        continue

                summary = item.get("summary", {})

                yield BodyMeasurement(
                    id=f"cloud_weight_{item.get('id', record_time)}",
                    provider="zepp_life",
                    source_type="cloud_session",
                    user_id=self.user_id or "unknown",
                    timestamp=datetime.fromtimestamp(record_time)
                    if record_time
                    else datetime.now(),
                    weight_kg=summary.get("weight", 0),
                    bmi=summary.get("bmi"),
                    body_fat_pct=summary.get("fatRate"),
                    muscle_mass_kg=summary.get("muscleRate"),
                    water_pct=summary.get("bodyWaterRate"),
                    bone_mass_kg=summary.get("boneMass"),
                    visceral_fat_score=int(summary.get("visceralFat", 0))
                    if summary.get("visceralFat")
                    else None,
                    basal_metabolism_kcal=int(summary.get("metabolism", 0))
                    if summary.get("metabolism")
                    else None,
                    metabolic_age=int(summary.get("muscleAge", 0))
                    if summary.get("muscleAge")
                    else None,
                )

        except Exception as e:
            logger.error(f"Error fetching weight: {e}")

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
            self._connected = False

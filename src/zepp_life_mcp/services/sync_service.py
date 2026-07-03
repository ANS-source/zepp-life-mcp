"""Sync service for importing data from adapters to database."""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from zepp_life_mcp.adapters.base import DataAdapter
from zepp_life_mcp.storage import Database

logger = logging.getLogger(__name__)


class SyncService:
    """Service for synchronizing data from adapters to local database."""

    def __init__(self, adapter: DataAdapter, db: Database):
        """Initialize sync service.

        Args:
            adapter: Data source adapter
            db: Database instance
        """
        self.adapter = adapter
        self.db = db

    async def _iterate_records(self, records: Any) -> AsyncIterator[Any]:
        if hasattr(records, "__aiter__"):
            async for record in records:
                yield record
            return

        for record in records:
            yield record

    async def sync_data_type(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronize a specific data type.

        Args:
            data_type: Type of data to sync (daily_activity, sleep, workouts, body_measurements)
            start_date: Start date (YYYY-MM-DD), defaults to 30 days ago
            end_date: End date (YYYY-MM-DD), defaults to today
            force_full: Force full sync ignoring last sync state

        Returns:
            Dict with sync statistics
        """
        if not self.adapter.is_connected():
            raise RuntimeError("Adapter not connected")

        # Get last sync state for incremental sync
        last_record_ts = None
        if not force_full:
            state = self.db.get_sync_state(data_type)
            if state and state.get("last_record_timestamp"):
                last_record_ts = datetime.fromisoformat(state["last_record_timestamp"])

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            if last_record_ts:
                start_date = last_record_ts.strftime("%Y-%m-%d")
            elif self.adapter.__class__.__name__ == "CloudSessionAdapter":
                start_date = "2020-01-01"
            else:
                start = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)
                start_date = start.strftime("%Y-%m-%d")

        added = 0
        updated = 0
        skipped = 0
        last_ts = None

        # Sync based on data type
        if data_type == "daily_activity":
            records = self.adapter.iter_daily_activity(start_date, end_date)
            async for activity in self._iterate_records(records):
                if self.db.insert_daily_activity(activity):
                    added += 1
                else:
                    updated += 1
                if last_ts is None or (activity.collected_at and activity.collected_at > last_ts):
                    last_ts = activity.collected_at

        elif data_type == "sleep":
            records = self.adapter.iter_sleep_sessions(start_date, end_date)
            async for sleep in self._iterate_records(records):
                if self.db.insert_sleep_session(sleep):
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sleep.start_at > last_ts:
                    last_ts = sleep.start_at

        elif data_type == "workouts":
            records = self.adapter.iter_workouts(start_date, end_date)
            async for workout in self._iterate_records(records):
                if self.db.insert_workout(workout):
                    added += 1
                else:
                    updated += 1
                if last_ts is None or workout.start_at > last_ts:
                    last_ts = workout.start_at

        elif data_type == "body_measurements":
            records = self.adapter.iter_body_measurements(start_date, end_date)
            async for measurement in self._iterate_records(records):
                if self.db.insert_body_measurement(measurement):
                    added += 1
                else:
                    updated += 1
                if last_ts is None or measurement.timestamp > last_ts:
                    last_ts = measurement.timestamp

        elif data_type == "heart_rate":
            records = self.adapter.iter_heart_rate(start_date, end_date)
            async for sample in self._iterate_records(records):
                if self.db.insert_heart_rate_sample(sample):
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sample.timestamp > last_ts:
                    last_ts = sample.timestamp

            if hasattr(self.adapter, "iter_resting_heart_rate"):
                resting_records = self.adapter.iter_resting_heart_rate(start_date, end_date)
                async for sample in self._iterate_records(resting_records):
                    if self.db.insert_heart_rate_sample(sample):
                        added += 1
                    else:
                        updated += 1
                    if last_ts is None or sample.timestamp > last_ts:
                        last_ts = sample.timestamp

        elif data_type == "readiness":
            if not hasattr(self.adapter, "iter_readiness"):
                raise ValueError(f"Adapter does not support {data_type}")
            records = self.adapter.iter_readiness(start_date, end_date)
            async for sample in self._iterate_records(records):
                if self.db.insert_readiness_sample(sample):
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sample.timestamp > last_ts:
                    last_ts = sample.timestamp

        elif data_type == "stress":
            if not hasattr(self.adapter, "iter_stress"):
                raise ValueError(f"Adapter does not support {data_type}")
            records = self.adapter.iter_stress(start_date, end_date)
            async for sample in self._iterate_records(records):
                if self.db.insert_stress_sample(sample):
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sample.timestamp > last_ts:
                    last_ts = sample.timestamp

        else:
            raise ValueError(f"Unknown data type: {data_type}")

        # Update sync state
        if last_ts:
            self.db.update_sync_state(data_type, last_ts)

        logger.info(
            f"Synced {data_type}: {added} added, {updated} updated, "
            f"range {start_date} to {end_date}"
        )

        return {
            "data_type": data_type,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "start_date": start_date,
            "end_date": end_date,
        }

    async def ensure_fresh(
        self,
        data_type: str,
        start_date: str,
        end_date: str,
        stale_after_minutes: int,
    ) -> dict | None:
        """Sync a data type/date range if the cache doesn't fully cover it or is stale.

        Coverage is checked by counting distinct calendar days with at least one
        record against the number of days actually spanned by the range - checking
        only that some record exists in the range, or only that end_date is covered,
        both miss a gap in the middle of the range (e.g. start_date and end_date
        populated but a day in between missing).

        Callers must pass an already-normalized range (start_date <= end_date) -
        normalization happens once at the MCP handler level (_normalize_date_range
        in server.py) so the sync and the subsequent DB query agree on the same
        corrected range, instead of each layer swapping independently.

        Returns sync stats if a sync was triggered, None if the cache was already
        fresh and fully covers the range.
        """
        if not self.adapter.is_connected():
            return None

        user_id = self.adapter.get_user_id() or "unknown"

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        if start_dt > end_dt:
            # Defensive: callers are expected to normalize the range before
            # calling ensure_fresh (see docstring above). Raise loudly instead
            # of silently treating a reversed range as "fully covered" - a
            # future caller that skips normalization should fail fast, not
            # produce a silently empty result.
            raise ValueError(
                f"ensure_fresh got a reversed range for {data_type} "
                f"(start_date={start_date} after end_date={end_date}); "
                "the caller must normalize the range first"
            )
        expected_days = (end_dt - start_dt).days + 1

        covered_days = self.db.get_covered_days(data_type, user_id, start_date, end_date)
        if covered_days < expected_days:
            return await self.sync_data_type(data_type, start_date, end_date, force_full=True)

        # Check the OLDEST touched record in the range, not just the newest one -
        # a single freshly-synced day can otherwise mask older, genuinely stale
        # days elsewhere in an already fully-covered range.
        oldest_updated = self.db.get_oldest_updated(data_type, user_id, start_date, end_date)
        if oldest_updated:
            age_minutes = (datetime.utcnow() - oldest_updated).total_seconds() / 60
            if age_minutes < stale_after_minutes:
                return None

        return await self.sync_data_type(data_type, start_date, end_date, force_full=True)

    def sync_data_type_sync(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronous wrapper for sync_data_type.

        Use this when calling from synchronous code.
        """
        return asyncio.run(self.sync_data_type(data_type, start_date, end_date, force_full))

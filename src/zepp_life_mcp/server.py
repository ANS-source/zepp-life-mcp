"""MCP server implementation for Zepp Life."""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from zepp_life_mcp.adapters.cloud_session import CloudSessionAdapter
from zepp_life_mcp.adapters.export_file import ExportFileAdapter
from zepp_life_mcp.auth import load_token
from zepp_life_mcp.config import load_config
from zepp_life_mcp.models import ConnectionStatus, QueryResponse
from zepp_life_mcp.services.query_service import QueryService
from zepp_life_mcp.services.sync_service import SyncService
from zepp_life_mcp.storage import Database

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create server
app = Server("zepp-life-mcp")

# Global services (initialized in main)
config = None
db = None
adapter = None
sync_service = None
query_service = None


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="get_connection_status",
            description="Check connection status to data source and last sync time",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="sync_data",
            description="Synchronize data from source to local cache",
            inputSchema={
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Types of data to sync (daily_activity, sleep, heart_rate, workouts, body_measurements)",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)",
                    },
                    "force_full_sync": {
                        "type": "boolean",
                        "description": "Force full sync instead of incremental",
                    },
                },
            },
        ),
        Tool(
            name="get_profile",
            description="Get user profile information",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_devices": {
                        "type": "boolean",
                        "description": "Include connected devices information",
                    },
                },
            },
        ),
        Tool(
            name="get_daily_summary",
            description="Get daily activity summary for a date or date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Single date (YYYY-MM-DD)",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date for range (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date for range (YYYY-MM-DD)",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Timezone (default from config)",
                    },
                },
            },
        ),
        Tool(
            name="query_metric_series",
            description="Query time series data for a specific metric",
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["steps", "distance_m", "active_kcal", "weight_kg", "sleep_minutes"],
                        "description": "Metric to query",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)",
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "description": "Aggregation granularity",
                    },
                    "aggregation": {
                        "type": "string",
                        "enum": ["sum", "avg", "min", "max", "latest"],
                        "description": "Aggregation method",
                    },
                },
                "required": ["metric", "start_date", "end_date"],
            },
        ),
        Tool(
            name="query_sleep",
            description="Query sleep sessions for a date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)",
                    },
                    "include_naps": {
                        "type": "boolean",
                        "description": "Include nap sessions",
                    },
                    "include_stages": {
                        "type": "boolean",
                        "description": "Include sleep stage breakdown",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        ),
        Tool(
            name="query_workouts",
            description="Query workouts for a date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)",
                    },
                    "activity_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by activity types (running, cycling, etc.)",
                    },
                    "min_duration_minutes": {
                        "type": "integer",
                        "description": "Minimum duration in minutes",
                    },
                    "min_distance_km": {
                        "type": "number",
                        "description": "Minimum distance in kilometers",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        ),
        Tool(
            name="query_heart_rate",
            description="Query heart rate samples for a date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)",
                    },
                    "sample_type": {
                        "type": "string",
                        "enum": ["resting", "active", "passive", "workout"],
                        "description": "Filter by sample type",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of samples to return",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        ),
        Tool(
            name="query_body_measurements",
            description="Query body measurements (weight, body composition) for a date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)",
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["weight_kg", "bmi", "body_fat_pct", "muscle_mass_kg", "water_pct"],
                        },
                        "description": "Specific metrics to include",
                    },
                    "latest_only": {
                        "type": "boolean",
                        "description": "Return only the latest measurement",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        ),
        Tool(
            name="get_data_coverage",
            description="Get data coverage information - which dates have data for each type",
            inputSchema={
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific data types to check (default: all)",
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    global config, db, adapter, sync_service, query_service
    
    try:
        if name == "get_connection_status":
            result = await _handle_get_connection_status()
        elif name == "sync_data":
            result = await _handle_sync_data(arguments)
        elif name == "get_profile":
            result = await _handle_get_profile(arguments)
        elif name == "get_daily_summary":
            result = await _handle_get_daily_summary(arguments)
        elif name == "query_metric_series":
            result = await _handle_query_metric_series(arguments)
        elif name == "query_sleep":
            result = await _handle_query_sleep(arguments)
        elif name == "query_workouts":
            result = await _handle_query_workouts(arguments)
        elif name == "query_heart_rate":
            result = await _handle_query_heart_rate(arguments)
        elif name == "query_body_measurements":
            result = await _handle_query_body_measurements(arguments)
        elif name == "get_data_coverage":
            result = await _handle_get_data_coverage(arguments)
        else:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "error": f"Unknown tool: {name}",
            }))]
        
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    
    except Exception as e:
        logger.exception(f"Error handling tool {name}")
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error": str(e),
        }))]


async def _handle_get_connection_status() -> dict:
    """Handle get_connection_status tool."""
    global adapter, config
    
    if not config or config.mode == "not_configured":
        return ConnectionStatus(
            mode="not_configured",
            connected=False,
            message="Server not configured. Run 'zepp-mcp setup' first.",
        ).model_dump()
    
    connected = adapter is not None and adapter.is_connected()
    
    # Get sync state from database
    last_sync = None
    available_types = []
    
    if db:
        for data_type in ["daily_activity", "sleep", "heart_rate", "workouts", "body_measurements"]:
            state = db.get_sync_state(data_type)
            if state and state.get("last_sync_at"):
                available_types.append(data_type)
                sync_time = datetime.fromisoformat(state["last_sync_at"])
                if last_sync is None or sync_time > last_sync:
                    last_sync = sync_time
    
    # Determine sync health
    sync_health = "unknown"
    if last_sync:
        age_minutes = (datetime.utcnow() - last_sync).total_seconds() / 60
        if age_minutes < config.stale_after_minutes:
            sync_health = "healthy"
        else:
            sync_health = "stale"
    
    next_action = None
    if not connected:
        next_action = "Check export path configuration"
    elif sync_health == "stale":
        next_action = "Run sync_data to update cache"
    elif not available_types:
        next_action = "Run sync_data to import data"
    
    return ConnectionStatus(
        mode=config.mode,
        connected=connected,
        last_sync_at=last_sync,
        available_data_types=available_types,
        sync_health=sync_health,
        next_action=next_action,
    ).model_dump()


async def _handle_sync_data(arguments: dict) -> dict:
    """Handle sync_data tool."""
    global sync_service
    
    if not sync_service:
        return {
            "status": "error",
            "error": "Sync service not initialized",
        }
    
    data_types = arguments.get("data_types") or sync_service.adapter.get_available_data_types()
    start_date = arguments.get("start_date")
    end_date = arguments.get("end_date")
    force_full = arguments.get("force_full_sync", False)
    
    sync_id = str(uuid.uuid4())
    started_at = datetime.utcnow()
    
    total_added = 0
    total_updated = 0
    total_skipped = 0
    types_synced = []
    
    for data_type in data_types:
        try:
            result = await sync_service.sync_data_type(
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                force_full=force_full,
            )
            total_added += result.get("added", 0)
            total_updated += result.get("updated", 0)
            total_skipped += result.get("skipped", 0)
            types_synced.append(data_type)
        except Exception as e:
            logger.error(f"Failed to sync {data_type}: {e}")
    
    finished_at = datetime.utcnow()
    
    return {
        "status": "ok",
        "sync_id": sync_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "records_added": total_added,
        "records_updated": total_updated,
        "records_skipped": total_skipped,
        "data_types_synced": types_synced,
    }


async def _handle_get_profile(arguments: dict) -> dict:
    """Handle get_profile tool."""
    global adapter, config
    
    if not adapter or not adapter.is_connected():
        return {
            "status": "error",
            "error": "Not connected to data source",
        }
    
    user_id = adapter.get_user_id() or "unknown"
    
    profile = {
        "user_id": user_id,
        "display_name": None,
        "timezone": config.timezone if config else "UTC",
        "devices": [],
    }
    
    if arguments.get("include_devices"):
        # TODO: Get devices from adapter
        pass
    
    return QueryResponse(
        status="ok",
        source=config.mode if config else "unknown",
        data={"profile": profile},
    ).model_dump()


async def _handle_get_daily_summary(arguments: dict) -> dict:
    """Handle get_daily_summary tool."""
    global query_service, config
    
    if not query_service:
        return {
            "status": "error",
            "error": "Query service not initialized",
        }
    
    # Handle single date or date range
    if "date" in arguments:
        start_date = arguments["date"]
        end_date = arguments["date"]
    else:
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
    
    if not start_date or not end_date:
        return {
            "status": "error",
            "error": "Either 'date' or 'start_date' and 'end_date' required",
        }
    
    try:
        summaries = query_service.get_daily_summaries(start_date, end_date)
        return QueryResponse(
            status="ok",
            source="cache",
            timezone=arguments.get("timezone", config.timezone if config else "UTC"),
            data={"summaries": summaries},
        ).model_dump()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


async def _handle_query_metric_series(arguments: dict) -> dict:
    """Handle query_metric_series tool."""
    global query_service, config
    
    if not query_service:
        return {
            "status": "error",
            "error": "Query service not initialized",
        }
    
    metric = arguments["metric"]
    start_date = arguments["start_date"]
    end_date = arguments["end_date"]
    granularity = arguments.get("granularity", "day")
    aggregation = arguments.get("aggregation", "sum")
    
    try:
        series = query_service.get_metric_series(
            metric=metric,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            aggregation=aggregation,
        )
        return QueryResponse(
            status="ok",
            source="cache",
            data={
                "metric": metric,
                "granularity": granularity,
                "aggregation": aggregation,
                "series": series,
            },
        ).model_dump()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


async def _handle_query_sleep(arguments: dict) -> dict:
    """Handle query_sleep tool."""
    global query_service, config
    
    if not query_service:
        return {
            "status": "error",
            "error": "Query service not initialized",
        }
    
    start_date = arguments["start_date"]
    end_date = arguments["end_date"]
    include_naps = arguments.get("include_naps", True)
    include_stages = arguments.get("include_stages", True)
    
    try:
        sessions = query_service.get_sleep_sessions(
            start_date=start_date,
            end_date=end_date,
            include_naps=include_naps,
        )
        
        if not include_stages:
            for session in sessions:
                session.pop("stages", None)
        
        return QueryResponse(
            status="ok",
            source="cache",
            data={
                "sessions": sessions,
                "total_sessions": len(sessions),
            },
        ).model_dump()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


async def _handle_query_workouts(arguments: dict) -> dict:
    """Handle query_workouts tool."""
    global query_service, config
    
    if not query_service:
        return {
            "status": "error",
            "error": "Query service not initialized",
        }
    
    start_date = arguments["start_date"]
    end_date = arguments["end_date"]
    activity_types = arguments.get("activity_types")
    min_duration = arguments.get("min_duration_minutes")
    min_distance_km = arguments.get("min_distance_km")
    
    try:
        workouts = query_service.get_workouts(
            start_date=start_date,
            end_date=end_date,
            activity_types=activity_types,
            min_duration=min_duration,
            min_distance_km=min_distance_km,
        )
        
        # Calculate summary
        total_duration = sum(w.get("duration_minutes", 0) for w in workouts)
        total_distance = sum(w.get("distance_m", 0) or 0 for w in workouts)
        total_calories = sum(w.get("calories_kcal", 0) or 0 for w in workouts)
        
        return QueryResponse(
            status="ok",
            source="cache",
            data={
                "workouts": workouts,
                "summary": {
                    "count": len(workouts),
                    "total_duration_minutes": total_duration,
                    "total_distance_m": total_distance,
                    "total_kcal": total_calories,
                },
            },
        ).model_dump()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


async def _handle_query_heart_rate(arguments: dict) -> dict:
    global query_service

    if not query_service:
        return {
            "status": "error",
            "error": "Query service not initialized",
        }

    start_date = arguments["start_date"]
    end_date = arguments["end_date"]
    sample_type = arguments.get("sample_type")
    limit = arguments.get("limit")

    try:
        samples = query_service.get_heart_rate_samples(
            start_date=start_date,
            end_date=end_date,
            sample_type=sample_type,
            limit=limit,
        )
        return QueryResponse(
            status="ok",
            source="cache",
            data={
                "samples": samples,
                "count": len(samples),
            },
        ).model_dump()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


async def _handle_query_body_measurements(arguments: dict) -> dict:
    """Handle query_body_measurements tool."""
    global query_service, config
    
    if not query_service:
        return {
            "status": "error",
            "error": "Query service not initialized",
        }
    
    start_date = arguments["start_date"]
    end_date = arguments["end_date"]
    metrics = arguments.get("metrics")
    latest_only = arguments.get("latest_only", False)
    
    try:
        measurements = query_service.get_body_measurements(
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
        )
        
        if latest_only and measurements:
            measurements = [measurements[-1]]
        
        return QueryResponse(
            status="ok",
            source="cache",
            data={
                "measurements": measurements,
                "count": len(measurements),
            },
        ).model_dump()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


async def _handle_get_data_coverage(arguments: dict) -> dict:
    """Handle get_data_coverage tool."""
    global query_service
    
    if not query_service:
        return {
            "status": "error",
            "error": "Query service not initialized",
        }
    
    data_types = arguments.get("data_types")
    
    try:
        coverage = query_service.get_data_coverage(data_types)
        return QueryResponse(
            status="ok",
            source="cache",
            data={"coverage": coverage},
        ).model_dump()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


async def main():
    """Main entry point."""
    global config, db, adapter, sync_service, query_service
    
    # Load configuration
    config = load_config()
    
    # Initialize database
    db = Database(config.database_path)
    
    # Initialize adapter if configured
    if config.mode == "export_file" and config.export_path:
        adapter = ExportFileAdapter(config.export_path)
        if adapter.connect():
            logger.info(f"Connected to export files at {config.export_path}")
        else:
            logger.warning(f"Failed to connect to export files at {config.export_path}")
    elif config.mode == "cloud_session":
        token, user_id = load_token()
        if token:
            adapter = CloudSessionAdapter(token, user_id)
            if await adapter.connect():
                logger.info("Connected to Zepp cloud API")
            else:
                logger.warning("Failed to connect to Zepp cloud API")
    # Initialize services
    if adapter:
        sync_service = SyncService(adapter, db)
        query_service = QueryService(db, adapter.get_user_id() or "unknown")
    else:
        query_service = QueryService(db, "unknown")
    
    # Run server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

#!/usr/bin/env python3
"""
Исследование Zepp API endpoints.

Запуск:
    python explore_api.py <token> [user_id]

Пример:
    python explore_api.py your_token_here 123456789
"""

import asyncio
import sys

import httpx


async def test_endpoint(client, method, path, params=None, data=None):
    """Test a single endpoint."""
    try:
        if method == "GET":
            response = await client.get(path, params=params)
        elif method == "POST":
            response = await client.post(path, data=data)
        else:
            return None
        
        status = response.status_code
        if status == 200:
            try:
                json_data = response.json()
                preview = str(json_data)[:200]
                return f"✅ {status} - {preview}..."
            except:
                return f"✅ {status} - {response.text[:200]}..."
        elif status == 404:
            return f"❌ {status} - Not found"
        elif status == 401:
            return f"🔒 {status} - Unauthorized"
        else:
            return f"⚠️  {status} - {response.text[:100]}"
    except Exception as e:
        return f"💥 Error: {e}"


async def explore_api(token, user_id=None):
    """Explore all known/potential API endpoints."""
    
    client = httpx.AsyncClient(
        base_url="https://api-mifit.huami.com",
        headers={
            "apptoken": token,
            "appPlatform": "web",
            "appname": "com.xiaomi.hm.health",
        },
        timeout=10.0,
    )
    
    # Test basic connection
    print("=" * 70)
    print("Testing Zepp API Endpoints")
    print("=" * 70)
    print()
    
    # Known working endpoint
    print("1. Testing KNOWN working endpoint (workouts):")
    result = await test_endpoint(client, "GET", "/v1/sport/run/history.json", {"limit": 1})
    print(f"   /v1/sport/run/history.json: {result}")
    print()
    
    # Activity/Steps endpoints
    print("2. Testing ACTIVITY/STEPS endpoints:")
    activity_endpoints = [
        "/v1/activity/steps",
        "/v1/activity/daily",
        "/v1/data/activity",
        "/v1/data/band_data.json",
        "/v1/data/steps",
        "/v1/users/activity",
    ]
    
    for endpoint in activity_endpoints:
        result = await test_endpoint(
            client, "GET", endpoint,
            {"start_date": "2024-01-01", "end_date": "2024-01-01", "user_id": user_id}
        )
        print(f"   {endpoint}: {result}")
    print()
    
    # Sleep endpoints
    print("3. Testing SLEEP endpoints:")
    sleep_endpoints = [
        "/v1/sleep/sessions",
        "/v1/sleep/data",
        "/v1/data/sleep",
        "/v1/users/sleep",
    ]
    
    for endpoint in sleep_endpoints:
        result = await test_endpoint(
            client, "GET", endpoint,
            {"start_date": "2024-01-01", "end_date": "2024-01-01", "user_id": user_id}
        )
        print(f"   {endpoint}: {result}")
    print()
    
    # Heart rate endpoints
    print("4. Testing HEART RATE endpoints:")
    hr_endpoints = [
        "/v1/heart_rate/data",
        "/v1/heartrate/data",
        "/v1/data/heart_rate",
        "/v1/data/heartrate",
    ]
    
    for endpoint in hr_endpoints:
        result = await test_endpoint(
            client, "GET", endpoint,
            {"start_date": "2024-01-01", "end_date": "2024-01-01", "user_id": user_id}
        )
        print(f"   {endpoint}: {result}")
    print()
    
    # Weight endpoints
    print("5. Testing WEIGHT endpoints:")
    if user_id:
        weight_endpoints = [
            f"https://api-mifit.zepp.com/users/{user_id}/members/-1/weightRecords?limit=1",
            f"https://api-mifit.zepp.com/huami.health.scale.familymember.get.json",
        ]
        
        for url in weight_endpoints:
            try:
                if "familymember" in url:
                    response = await client.post(
                        url,
                        data={"fuid": "all", "userid": user_id},
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    )
                else:
                    response = await client.get(url)
                
                status = response.status_code
                if status == 200:
                    print(f"   {url}: ✅ {status}")
                else:
                    print(f"   {url}: ❌ {status}")
            except Exception as e:
                print(f"   {url}: 💥 {e}")
    else:
        print("   (требуется user_id)")
    print()
    
    # User profile endpoints
    print("6. Testing USER/PROFILE endpoints:")
    profile_endpoints = [
        "/v1/users/profile",
        "/v1/user/profile",
        "/v1/account/profile",
        "/v1/users/info",
    ]
    
    for endpoint in profile_endpoints:
        result = await test_endpoint(client, "GET", endpoint)
        print(f"   {endpoint}: {result}")
    print()
    
    # Data export endpoints
    print("7. Testing DATA endpoints:")
    data_endpoints = [
        "/v1/data/export",
        "/v1/data/summary",
        "/v1/data/band_data.json",
    ]
    
    for endpoint in data_endpoints:
        result = await test_endpoint(
            client, "GET", endpoint,
            {"start_date": "2024-01-01", "end_date": "2024-01-01"}
        )
        print(f"   {endpoint}: {result}")
    print()
    
    await client.aclose()
    
    print("=" * 70)
    print("Исследование завершено!")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python explore_api.py <token> [user_id]")
        print()
        print("Example:")
        print("  python explore_api.py your_token_here 123456789")
        sys.exit(1)
    
    token = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    asyncio.run(explore_api(token, user_id))

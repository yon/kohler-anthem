#!/usr/bin/env python3
"""Test script using the kohler-anthem library.

Usage:
    source .env
    python3 scripts/test_library.py
"""

import asyncio
import json
import os
import sys

# Add src to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kohler_anthem import (
    KohlerAnthemClient,
    KohlerAnthemError,
    KohlerConfig,
)


def get_config() -> KohlerConfig:
    """Load configuration from environment variables."""
    required = {
        "KOHLER_USERNAME": "username",
        "KOHLER_PASSWORD": "password",
        "KOHLER_CLIENT_ID": "client_id",
        "KOHLER_APIM_KEY": "apim_subscription_key",
        "KOHLER_API_RESOURCE": "api_resource",
    }

    missing = [env for env in required if not os.environ.get(env)]
    if missing:
        print(f"Error: Missing environment variables: {', '.join(missing)}")
        print("\nRequired environment variables:")
        for env, desc in required.items():
            print(f"  {env} - {desc}")
        print("\nRun: source .env")
        sys.exit(1)

    return KohlerConfig(
        username=os.environ["KOHLER_USERNAME"],
        password=os.environ["KOHLER_PASSWORD"],
        client_id=os.environ["KOHLER_CLIENT_ID"],
        apim_subscription_key=os.environ["KOHLER_APIM_KEY"],
        api_resource=os.environ["KOHLER_API_RESOURCE"],
    )


async def main() -> None:
    """Main test function."""
    print("=" * 60)
    print("Kohler Anthem Library Test")
    print("=" * 60)

    config = get_config()
    print(f"\nUsername: {config.username}")
    print(f"Client ID: {config.client_id[:20]}...")

    try:
        async with KohlerAnthemClient(config) as client:
            # Step 1: Get customer info and discover devices
            print(f"\n{'=' * 60}")
            print("Step 1: Discovering devices...")
            print("=" * 60)

            # Extract customer_id from JWT token
            import base64

            token = client._auth.token
            if token:
                token_parts = token.access_token.split(".")
                if len(token_parts) >= 2:
                    payload = token_parts[1] + "=" * (4 - len(token_parts[1]) % 4)
                    decoded = json.loads(base64.urlsafe_b64decode(payload))
                    customer_id = decoded.get("oid") or decoded.get("sub")
                    print(f"Customer ID: {customer_id}")

            customer = await client.get_customer(customer_id)
            devices = customer.get_all_devices()

            print(f"\n✅ Found {len(devices)} device(s):")
            for i, device in enumerate(devices, 1):
                print(f"   {i}. {device.logical_name} (ID: {device.device_id})")
                print(f"      SKU: {device.sku}")

            if not devices:
                print("❌ No devices found")
                return

            device_id = devices[0].device_id
            print(f"\nUsing device: {devices[0].logical_name}")

            # Step 2: Get device state
            print(f"\n{'=' * 60}")
            print("Step 2: Getting device state...")
            print("=" * 60)

            state = await client.get_device_state(device_id)
            print("\n✅ Device State:")
            print(f"   Connected: {state.is_connected}")
            print(f"   Running: {state.is_running}")
            print(f"   Warming up: {state.is_warming_up}")
            print(f"   System state: {state.state.current_system_state.value}")
            print(f"   Active preset: {state.state.active_preset_id}")

            if state.state.valve_state:
                valve = state.state.valve_state[0]
                print(f"   Valve active: {valve.is_active}")
                print(f"   Temperature setpoint: {valve.temperature_setpoint}°C")
                print(f"   Flow setpoint: {valve.flow_setpoint}%")

            # Step 3: Get presets
            print(f"\n{'=' * 60}")
            print("Step 3: Getting presets...")
            print("=" * 60)

            presets = await client.get_presets(device_id)
            print(f"\n✅ Found {len(presets.presets)} preset(s):")
            for preset in presets.presets:
                status = "Experience" if preset.is_experience else "Preset"
                print(f"   {preset.id}. {preset.title} ({status})")
                print(f"      Duration: {preset.duration_minutes} min, State: {preset.state}")

            # Step 4: Test commands (commented out to avoid affecting shower)
            print(f"\n{'=' * 60}")
            print("Step 4: Command tests (skipped to avoid affecting shower)")
            print("=" * 60)
            print("\nTo test commands, uncomment the relevant lines below:")
            print("  - client.start_warmup(device_id)")
            print("  - client.turn_on_outlet(device_id, Outlet.SHOWERHEAD)")
            print("  - client.turn_off(device_id)")

            # Uncomment to test:
            # print("\nStarting warmup...")
            # await client.start_warmup(device_id)

            # print("\nTurning on showerhead at 38°C, 100% flow...")
            # await client.turn_on_outlet(
            #     device_id,
            #     Outlet.SHOWERHEAD,
            #     temperature_celsius=38.0,
            #     flow_percent=100,
            # )

            # print("\nTurning off...")
            # await client.turn_off(device_id)

            # Summary
            print(f"\n{'=' * 60}")
            print("TEST RESULTS SUMMARY")
            print("=" * 60)
            print("  ✅ Authentication: Success")
            print(f"  ✅ Device Discovery: Found {len(devices)} device(s)")
            print("  ✅ Device State: Retrieved")
            print(f"  ✅ Presets: Found {len(presets.presets)}")
            print("  ⏭️  Commands: Skipped (uncomment to test)")

    except KohlerAnthemError as e:
        print(f"\n❌ Error: {e}")
        if e.status_code:
            print(f"   Status code: {e.status_code}")
        if e.raw_response:
            print(f"   Response: {str(e.raw_response)[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

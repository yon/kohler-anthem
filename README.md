# kohler-anthem

Python library for controlling Kohler Anthem digital showers.

> **DISCLAIMER**: This is an unofficial library developed independently for personal use. It is not affiliated with, endorsed by, or supported by Kohler Co. This library was reverse-engineered from the Kohler Konnect mobile app and may break at any time if Kohler modifies their APIs. The author provides no warranty, assumes no liability, and offers no support for this software. Use at your own risk. The author is not responsible for any damage to your devices, property, or any other consequences resulting from the use of this library.

## Installation

```bash
pip install kohler-anthem
```

## Quick Start

```python
import asyncio
from kohler_anthem import KohlerAnthemClient, KohlerConfig, Outlet

async def main():
    config = KohlerConfig(
        username="user@example.com",
        password="password",
        client_id="...",
        apim_subscription_key="...",
        api_resource="...",
    )

    async with KohlerAnthemClient(config) as client:
        # Discover devices
        customer = await client.get_customer("customer-id")
        device = customer.get_all_devices()[0]

        # Get state
        state = await client.get_device_state(device.device_id)
        print(f"Running: {state.is_running}")

        # Control
        await client.turn_on_outlet(device.device_id, Outlet.SHOWERHEAD, temperature_celsius=38.0)
        await client.turn_off(device.device_id)

asyncio.run(main())
```

## Configuration

| Parameter | Description |
|-----------|-------------|
| `username` | Kohler account email |
| `password` | Kohler account password |
| `client_id` | Azure AD B2C client ID |
| `apim_subscription_key` | Azure APIM subscription key |
| `api_resource` | Azure AD B2C API resource ID |

See [API.md](API.md) for full API documentation.

## Development

```bash
make deps    # Install dependencies
make check   # Run lint, typecheck, tests
make help    # Show all targets
```

See [Makefile](Makefile) for all available targets.

## License

MIT

# kohler-anthem

Python library for controlling Kohler Anthem digital showers.

## Installation

```bash
pip install kohler-anthem
```

## Usage

```python
import asyncio
from kohler_anthem import KohlerAnthemClient, KohlerConfig, Outlet

async def main():
    config = KohlerConfig(
        username="user@example.com",
        password="password",
        client_id="azure-ad-b2c-client-id",
        apim_subscription_key="azure-apim-subscription-key",
        api_resource="azure-ad-api-resource-id",
    )

    async with KohlerAnthemClient(config) as client:
        # Discover devices
        customer = await client.get_customer("customer-id")
        device_id = customer.get_all_devices()[0].device_id

        # Get device state
        state = await client.get_device_state(device_id)
        print(f"Connected: {state.is_connected}")
        print(f"Running: {state.is_running}")

        # Turn on shower
        await client.turn_on_outlet(device_id, Outlet.SHOWERHEAD, temperature_celsius=38.0)

        # Turn off
        await client.turn_off(device_id)

asyncio.run(main())
```

## Configuration

`KohlerConfig` requires the following credentials:

| Parameter | Description |
|-----------|-------------|
| `username` | Kohler account email |
| `password` | Kohler account password |
| `client_id` | Azure AD B2C application client ID |
| `apim_subscription_key` | Azure API Management subscription key |
| `api_resource` | Azure AD B2C API resource identifier |

Optional parameters with defaults:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `auth_tenant` | `konnectkohler.onmicrosoft.com` | Azure AD B2C tenant |
| `auth_policy` | `B2C_1_ROPC_Auth` | Azure AD B2C policy |

## Development

```bash
pip install -e ".[dev]"
pytest
```

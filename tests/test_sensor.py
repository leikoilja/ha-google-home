"""Tests for Google Home sensors."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    SENSOR,
    SERVICE_REBOOT,
    SERVICE_REFRESH,
)
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeTimersSensor,
    async_reboot_devices,
    async_refresh_devices,
    async_setup_entry,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.const import STATE_UNAVAILABLE

# glocaltokens accepts only master tokens of the real length
MASTER_TOKEN = "aas_et/" + "x" * 216
ALARM_IDS = [
    "alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51",
    "alarm/47dc1fa0-5ec0-2cc7-9ead-a94b85e22769",
]
TIMER_IDS = [
    "timer/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51",
    "timer/47dc1fa0-5ec0-2cc7-9ead-a94b85e22769",
]


@pytest.mark.parametrize(
    ("ip_address", "available"), [("192.168.1.10", True), (None, False)]
)
def test_device_sensor_available(ip_address: str | None, available: bool) -> None:
    """Show a device that isn't on the network as unavailable, not unknown."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token", ip_address=ip_address)
    coordinator = Mock(data=[device], last_update_success=True)
    sensor = GoogleHomeDeviceSensor(coordinator, Mock(), "device-id", "Kitchen", None)

    assert sensor.available is available


def test_device_sensor_unavailable_when_missing() -> None:
    """Show a device that Google no longer lists as unavailable."""
    coordinator = Mock(data=[], last_update_success=True)
    sensor = GoogleHomeDeviceSensor(coordinator, Mock(), "device-id", "Kitchen", None)

    assert sensor.available is False


def set_alarms_and_timers(
    device: GoogleHomeDevice, alarm_ids: list[str], timer_ids: list[str]
) -> GoogleHomeDevice:
    """Give the device the given alarms and timers, as a fetch from it would."""
    device.set_alarms(
        [
            {"id": alarm_id, "fire_time": 1700000000000, "status": 1}
            for alarm_id in alarm_ids
        ]
    )
    device.set_timers(
        [
            {
                "id": timer_id,
                "fire_time": 1700000000000,
                "original_duration": 60000,
                "status": 1,
            }
            for timer_id in timer_ids
        ]
    )
    return device


def confirm_delete(device: GoogleHomeDevice, items_to_delete: list[str]) -> None:
    """Remove the items from the device, as the client does once the device confirms."""
    device.remove_alarms_and_timers(items_to_delete)


def set_up_platform() -> tuple[Mock, Mock]:
    """Set up the sensor platform, returning its entity and batched action registrations."""
    platform = Mock()
    hass = Mock(
        data={DOMAIN: {"entry": {DATA_CLIENT: Mock(), DATA_COORDINATOR: Mock(data=[])}}}
    )
    with (
        patch(
            "homeassistant.helpers.entity_platform.async_get_current_platform",
            return_value=platform,
        ),
        patch(
            "homeassistant.helpers.service.async_register_batched_platform_entity_service"
        ) as register_batched,
    ):
        asyncio.run(async_setup_entry(hass, Mock(entry_id="entry"), Mock()))
    return platform, register_batched


def test_batched_actions_registered() -> None:
    """Batch the reboot and refresh actions, so Home Assistant calls each once with every targeted sensor."""
    _, register_batched = set_up_platform()

    assert {
        c.args[2]: (c.kwargs["entity_domain"], c.kwargs["func"])
        for c in register_batched.call_args_list
    } == {
        SERVICE_REBOOT: (SENSOR, async_reboot_devices),
        SERVICE_REFRESH: (SENSOR, async_refresh_devices),
    }


def run_action(
    action: str,
    data: dict[str, str | bool],
    alarm_ids: list[str],
    timer_ids: list[str],
) -> tuple[Mock, Mock, GoogleHomeDevice, list[str | None]]:
    """Run a delete action as registered on every sensor of a device that now has these IDs.

    Like Home Assistant for a device, area, floor or label target, skip sensors
    without the action's required features. The last poll saw other IDs, which
    the delete-all actions must not use. Also return the state of the sensors
    the action ran on each time the entities were updated.
    """
    platform, _ = set_up_platform()
    [(_, _, func, required_features)] = [
        c.args
        for c in platform.async_register_entity_service.call_args_list
        if c.args[0] == action
    ]

    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ["alarm/from-last-poll"],
        ["timer/from-last-poll"],
    )
    client = Mock(
        delete_alarm_or_timer=AsyncMock(side_effect=confirm_delete),
        update_alarms_and_timers=AsyncMock(
            side_effect=lambda d: set_alarms_and_timers(d, alarm_ids, timer_ids)
        ),
    )
    coordinator = Mock(data=[device], async_request_refresh=AsyncMock())
    sensors = [
        sensor_class(coordinator, client, "device-id", "Kitchen", None)
        for sensor_class in (
            GoogleHomeDeviceSensor,
            GoogleHomeAlarmsSensor,
            GoogleHomeTimersSensor,
        )
    ]
    supported = [
        sensor
        for sensor in sensors
        if (features := sensor.supported_features) is not None
        and any(features & f == f for f in required_features)
    ]
    shown: list[str | None] = []
    coordinator.async_update_listeners.side_effect = lambda: shown.extend(
        sensor.state for sensor in supported
    )
    call = Mock(data=data)

    async def run_on_supported() -> None:
        for sensor in supported:
            await func(sensor, call)

    asyncio.run(run_on_supported())
    return client, coordinator, device, shown


@pytest.mark.parametrize(
    ("action", "data", "ids"),
    [
        ("delete_alarm", {"alarm_id": ALARM_IDS[0]}, [ALARM_IDS[0]]),
        ("delete_timer", {"timer_id": TIMER_IDS[0]}, [TIMER_IDS[0]]),
        ("delete_all_alarms", {}, ALARM_IDS),
        ("delete_all_timers", {}, TIMER_IDS),
    ],
)
def test_delete_runs_once_on_its_own_sensor(
    action: str, data: dict[str, str | bool], ids: list[str]
) -> None:
    """Delete only from the sensor the action is for, in one request."""
    client, _, device, _ = run_action(action, data, ALARM_IDS, TIMER_IDS)

    client.delete_alarm_or_timer.assert_awaited_once_with(
        device=device, items_to_delete=ids
    )


@pytest.mark.parametrize("action", ["delete_all_alarms", "delete_all_timers"])
def test_delete_all_sends_nothing_when_empty(action: str) -> None:
    """Send no request and don't refresh when there is nothing to delete."""
    client, coordinator, _, _ = run_action(action, {}, [], [])

    client.delete_alarm_or_timer.assert_not_awaited()
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize("action", ["delete_all_alarms", "delete_all_timers"])
@pytest.mark.parametrize(("alarm_ids", "timer_ids"), [(ALARM_IDS, TIMER_IDS), ([], [])])
def test_delete_all_shows_none_left(
    action: str, alarm_ids: list[str], timer_ids: list[str]
) -> None:
    """Show no alarms or timers right away, even without a refresh.

    Also when the device has none left, such as after deleting them from the phone.
    """
    _, _, _, shown = run_action(action, {"skip_refresh": True}, alarm_ids, timer_ids)

    assert shown == [STATE_UNAVAILABLE]


@pytest.mark.parametrize(
    ("sensor_class", "action", "data"),
    [
        (GoogleHomeAlarmsSensor, "async_delete_alarm", {"alarm_id": ALARM_IDS[0]}),
        (GoogleHomeTimersSensor, "async_delete_timer", {"timer_id": TIMER_IDS[0]}),
    ],
)
def test_delete_one_shows_it_gone(
    sensor_class: type, action: str, data: dict[str, str | bool]
) -> None:
    """Show the deleted alarm or timer as gone right away, even without a refresh."""
    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ALARM_IDS[:1],
        TIMER_IDS[:1],
    )
    client = Mock(delete_alarm_or_timer=AsyncMock(side_effect=confirm_delete))
    coordinator = Mock(data=[device])
    sensor = sensor_class(coordinator, client, "device-id", "Kitchen", None)
    shown: list[str | None] = []
    coordinator.async_update_listeners.side_effect = lambda: shown.append(sensor.state)

    asyncio.run(getattr(sensor, action)(Mock(data={**data, "skip_refresh": True})))

    assert shown == [STATE_UNAVAILABLE]


@pytest.mark.parametrize("action", ["delete_all_alarms", "delete_all_timers"])
@pytest.mark.parametrize(
    ("data", "refreshed"),
    [({}, True), ({"skip_refresh": False}, True), ({"skip_refresh": True}, False)],
)
def test_delete_all_skip_refresh(
    action: str, data: dict[str, str | bool], refreshed: bool
) -> None:
    """Refresh the devices after deleting unless skip_refresh is set."""
    _, coordinator, _, _ = run_action(action, data, ALARM_IDS, TIMER_IDS)

    assert coordinator.async_request_refresh.await_count == int(refreshed)


def test_refresh_devices_once() -> None:
    """Refresh the devices once, however many sensors and devices are targeted."""
    coordinator = Mock(async_request_refresh=AsyncMock())
    sensors: list[GoogleHomeBaseEntity] = [
        sensor_class(coordinator, Mock(), device_id, name, None)
        for device_id, name in (("kitchen-id", "Kitchen"), ("bedroom-id", "Bedroom"))
        for sensor_class in (
            GoogleHomeDeviceSensor,
            GoogleHomeAlarmsSensor,
            GoogleHomeTimersSensor,
        )
    ]

    asyncio.run(async_refresh_devices(sensors, Mock()))

    coordinator.async_request_refresh.assert_awaited_once()


def test_reboot_devices_once_each() -> None:
    """Reboot each device once, though a device target selects two of its sensors."""
    devices = [
        GoogleHomeDevice(device_id, device_id, "token", "192.168.1.10")
        for device_id in ("kitchen", "bedroom")
    ]
    coordinator = Mock(data=devices)
    client = Mock(reboot_google_device=AsyncMock())
    sensors: list[GoogleHomeBaseEntity] = [
        sensor_class(coordinator, client, device.device_id, device.name, None)
        for device in devices
        for sensor_class in (GoogleHomeAlarmsSensor, GoogleHomeTimersSensor)
    ]

    asyncio.run(async_reboot_devices(sensors, Mock()))

    assert [c.args for c in client.reboot_google_device.await_args_list] == [
        (devices[0],),
        (devices[1],),
    ]


def test_reboot_devices_finishes_all_before_raising() -> None:
    """Finish every reboot before reporting the first error."""
    devices = [
        GoogleHomeDevice(device_id, device_id, "token", "192.168.1.10")
        for device_id in ("kitchen", "bedroom")
    ]
    finished: list[str] = []

    async def reboot(device: GoogleHomeDevice) -> None:
        if device.device_id == "kitchen":
            raise RuntimeError("kitchen failed")
        await asyncio.sleep(0.01)
        finished.append(device.device_id)

    coordinator = Mock(data=devices)
    client = Mock(reboot_google_device=AsyncMock(side_effect=reboot))
    sensors: list[GoogleHomeBaseEntity] = [
        GoogleHomeAlarmsSensor(coordinator, client, d.device_id, d.name, None)
        for d in devices
    ]

    with pytest.raises(RuntimeError, match="kitchen failed"):
        asyncio.run(async_reboot_devices(sensors, Mock()))
    assert finished == ["bedroom"]


def test_delete_alarm_or_timer_posts_all_ids() -> None:
    """Post all IDs to the device in one request."""
    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    client.request = AsyncMock(return_value={"success": True})  # type: ignore[method-assign]
    device = GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10")

    asyncio.run(client.delete_alarm_or_timer(device, ALARM_IDS))

    client.request.assert_awaited_once_with(
        method="POST",
        endpoint=API_ENDPOINT_ALARM_DELETE,
        device=device,
        data={"ids": ALARM_IDS},
    )


@pytest.mark.parametrize(
    ("response", "alarms_left"),
    [
        ({"success": True}, ALARM_IDS[1:]),
        ({"success": False}, ALARM_IDS),
        (None, ALARM_IDS),
    ],
)
def test_delete_alarm_or_timer_removes_deleted_ids(
    response: dict[str, bool] | None, alarms_left: list[str]
) -> None:
    """Remove only the deleted IDs from the device, once it confirms deleting them."""
    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]
    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ALARM_IDS,
        TIMER_IDS,
    )

    asyncio.run(client.delete_alarm_or_timer(device, ALARM_IDS[:1]))

    assert [alarm.alarm_id for alarm in device.get_sorted_alarms()] == alarms_left
    assert [timer.timer_id for timer in device.get_sorted_timers()] == TIMER_IDS


def test_delete_alarm_or_timer_sends_nothing_for_no_ids() -> None:
    """Send no request when given no IDs."""
    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    client.request = AsyncMock()  # type: ignore[method-assign]
    device = GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10")

    asyncio.run(client.delete_alarm_or_timer(device, []))

    client.request.assert_not_awaited()

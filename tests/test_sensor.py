"""Tests for Google Home sensors."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARMS,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    SENSOR,
    SERVICE_DELETE_ALL_ALARMS,
    SERVICE_DELETE_ALL_TIMERS,
    SERVICE_REBOOT,
    SERVICE_REFRESH,
)
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeSensorFeature,
    GoogleHomeTimersSensor,
    async_delete_all_from_devices,
    async_reboot_devices,
    async_refresh_devices,
    async_setup_entry,
)
from custom_components.google_home.types import AlarmJsonDict, JsonDict, TimerJsonDict

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError

# pylint: enable=wrong-import-order

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
EN_TRANSLATIONS = json.loads(
    (
        Path(__file__).parents[1] / "custom_components/google_home/translations/en.json"
    ).read_text(encoding="utf-8")
)


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


def alarms_json(alarm_ids: list[str]) -> list[AlarmJsonDict]:
    """Return alarms with these IDs as the device sends them."""
    return [
        {"id": alarm_id, "fire_time": 1700000000000, "status": 1}
        for alarm_id in alarm_ids
    ]


def timers_json(timer_ids: list[str]) -> list[TimerJsonDict]:
    """Return timers with these IDs as the device sends them."""
    return [
        {
            "id": timer_id,
            "fire_time": 1700000000000,
            "original_duration": 60000,
            "status": 1,
        }
        for timer_id in timer_ids
    ]


def set_alarms_and_timers(
    device: GoogleHomeDevice, alarm_ids: list[str], timer_ids: list[str]
) -> GoogleHomeDevice:
    """Give the device the given alarms and timers, as a fetch from it would."""
    device.set_alarms(alarms_json(alarm_ids))
    device.set_timers(timers_json(timer_ids))
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
    """Batch the delete all, reboot and refresh actions, so Home Assistant calls each once with every targeted sensor."""
    _, register_batched = set_up_platform()

    assert {
        c.args[2]: (c.kwargs["entity_domain"], c.kwargs["func"])
        for c in register_batched.call_args_list
    } == {
        SERVICE_DELETE_ALL_ALARMS: (SENSOR, async_delete_all_from_devices),
        SERVICE_DELETE_ALL_TIMERS: (SENSOR, async_delete_all_from_devices),
        SERVICE_REBOOT: (SENSOR, async_reboot_devices),
        SERVICE_REFRESH: (SENSOR, async_refresh_devices),
    }


def get_registered_action(
    action: str,
) -> tuple[
    Callable[[Sequence[GoogleHomeBaseEntity], ServiceCall], Awaitable[None]],
    list[GoogleHomeSensorFeature],
]:
    """Return how the platform runs an action on the sensors it targets, and the features it requires.

    Home Assistant calls a batched action once with all of them, and other
    actions once for each.
    """
    platform, register_batched = set_up_platform()
    for c in register_batched.call_args_list:
        if c.args[2] == action:
            return c.kwargs["func"], c.kwargs["required_features"]
    [(_, _, func, required_features)] = [
        c.args
        for c in platform.async_register_entity_service.call_args_list
        if c.args[0] == action
    ]

    async def run_on_each(
        sensors: Sequence[GoogleHomeBaseEntity], call: ServiceCall
    ) -> None:
        for sensor in sensors:
            await func(sensor, call)

    return run_on_each, required_features


def run_action(
    action: str,
    data: dict[str, str | bool],
    alarm_ids: list[str],
    timer_ids: list[str],
) -> tuple[AsyncMock, Mock, GoogleHomeDevice, list[str | None]]:
    """Run a delete action as registered on every sensor of a device that now has these IDs.

    Like Home Assistant for a device, area, floor or label target, skip sensors
    without the action's required features. The device sends these IDs when
    asked; the last poll saw other IDs, which the delete-all actions must not
    use. Return the mocked delete, and the state of the sensors the action ran
    on each time the entities were updated.
    """
    func, required_features = get_registered_action(action)

    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ["alarm/from-last-poll"],
        ["timer/from-last-poll"],
    )
    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    client.request = AsyncMock(  # type: ignore[method-assign]
        return_value={"alarm": alarms_json(alarm_ids), "timer": timers_json(timer_ids)}
    )
    delete = AsyncMock(side_effect=confirm_delete)
    client.delete_alarm_or_timer = delete  # type: ignore[method-assign]
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
    asyncio.run(func(supported, Mock(data=data)))
    return delete, coordinator, device, shown


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
    delete, _, device, _ = run_action(action, data, ALARM_IDS, TIMER_IDS)

    delete.assert_awaited_once_with(device=device, items_to_delete=ids)


@pytest.mark.parametrize("action", ["delete_all_alarms", "delete_all_timers"])
def test_delete_all_sends_nothing_when_empty(action: str) -> None:
    """Send no request and don't refresh when there is nothing to delete."""
    delete, coordinator, _, _ = run_action(action, {}, [], [])

    delete.assert_not_awaited()
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
    ("action", "sensor_class"),
    [
        ("delete_all_alarms", GoogleHomeAlarmsSensor),
        ("delete_all_timers", GoogleHomeTimersSensor),
    ],
)
@pytest.mark.parametrize("response", [None, {"alarm": []}, {"timer": []}])
def test_delete_all_fails_when_fetch_fails(
    action: str, sensor_class: type[GoogleHomeBaseEntity], response: JsonDict | None
) -> None:
    """Report an error and delete nothing when the device's current IDs can't be fetched.

    The last poll's IDs may be gone, and alarms or timers set since then would
    stay while the action looked successful.
    """
    func, _ = get_registered_action(action)
    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ALARM_IDS,
        TIMER_IDS,
    )
    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    request = AsyncMock(return_value=response)
    client.request = request  # type: ignore[method-assign]
    coordinator = Mock(data=[device], async_request_refresh=AsyncMock())
    sensor = sensor_class(coordinator, client, "device-id", "Kitchen", None)

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func([sensor], Mock(data={})))

    # The fetch is the only request: nothing is deleted with the last poll's IDs
    request.assert_awaited_once_with(
        method="GET", endpoint=API_ENDPOINT_ALARMS, device=device, polling=False
    )
    coordinator.async_request_refresh.assert_not_awaited()
    # Home Assistant shows the message of this key from en.json
    assert err.value.translation_domain == DOMAIN
    message = EN_TRANSLATIONS["exceptions"][err.value.translation_key]["message"]
    assert "Kitchen" in message.format(**(err.value.translation_placeholders or {}))


def set_up_devices(
    sensor_class: type[GoogleHomeBaseEntity], replies: dict[str, JsonDict | None]
) -> tuple[list[GoogleHomeBaseEntity], AsyncMock]:
    """Return a sensor for each device named in replies, and the mocked delete.

    Each device sends its reply when asked for its alarms and timers. The last
    poll saw other IDs, which the delete-all actions must not use.
    """
    devices = [
        set_alarms_and_timers(
            GoogleHomeDevice(f"{name}-id", name, "token", "192.168.1.10"),
            ["alarm/from-last-poll"],
            ["timer/from-last-poll"],
        )
        for name in replies
    ]

    async def request(*, device: GoogleHomeDevice, **_: object) -> JsonDict | None:
        # A device that answers does so after the others fail, so the action
        # must wait for it before raising
        if (reply := replies[device.name]) == REPLY:
            await asyncio.sleep(0.01)
        return reply

    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    client.request = AsyncMock(side_effect=request)  # type: ignore[method-assign]
    delete = AsyncMock(side_effect=confirm_delete)
    client.delete_alarm_or_timer = delete  # type: ignore[method-assign]
    coordinator = Mock(data=devices, async_request_refresh=AsyncMock())
    sensors = [
        sensor_class(coordinator, client, device.device_id, device.name, None)
        for device in devices
    ]
    return sensors, delete


REPLY: JsonDict = {"alarm": alarms_json(ALARM_IDS), "timer": timers_json(TIMER_IDS)}


@pytest.mark.parametrize(
    ("action", "sensor_class"),
    [
        ("delete_all_alarms", GoogleHomeAlarmsSensor),
        ("delete_all_timers", GoogleHomeTimersSensor),
    ],
)
@pytest.mark.parametrize(
    ("offline", "translation_key", "placeholders"),
    [
        (["Kitchen"], "alarms_and_timers_not_fetched", {"device": "Kitchen"}),
        # In alphabetical order, whatever order Home Assistant passes them in
        (
            ["Office", "Kitchen"],
            "alarms_and_timers_not_fetched_from_devices",
            {"devices": "Kitchen, Office"},
        ),
    ],
)
def test_delete_all_names_every_device_it_cant_fetch(
    action: str,
    sensor_class: type[GoogleHomeBaseEntity],
    offline: list[str],
    translation_key: str,
    placeholders: dict[str, str],
) -> None:
    """Delete from the devices that answer, then name all that didn't in one error.

    Home Assistant shows one error for an action, however many devices fail.
    """
    func, _ = get_registered_action(action)
    names = ["Office", "Bedroom", "Kitchen"]
    sensors, delete = set_up_devices(
        sensor_class, {name: None if name in offline else REPLY for name in names}
    )
    call = Mock(data={})

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func(sensors, call))

    assert sorted(c.kwargs["device"].name for c in delete.await_args_list) == sorted(
        name for name in names if name not in offline
    )
    assert err.value.translation_key == translation_key
    assert err.value.translation_placeholders == placeholders
    # Home Assistant shows the message of this key from en.json
    message = EN_TRANSLATIONS["exceptions"][translation_key]["message"]
    assert all(name in message.format(**placeholders) for name in offline)
    # Like Home Assistant's per-entity calls, so the logbook shows the action
    assert all(
        sensor._context is call.context  # noqa: SLF001  # pylint: disable=protected-access
        for sensor in sensors
    )


@pytest.mark.parametrize(
    ("action", "sensor_class"),
    [
        ("delete_all_alarms", GoogleHomeAlarmsSensor),
        ("delete_all_timers", GoogleHomeTimersSensor),
    ],
)
def test_delete_all_raises_unexpected_error(
    action: str, sensor_class: type[GoogleHomeBaseEntity]
) -> None:
    """Raise an unexpected error, such as from a malformed reply, rather than hide it."""
    func, _ = get_registered_action(action)
    sensors, delete = set_up_devices(
        sensor_class,
        # A timer without its fields
        {
            "Kitchen": None,
            "Bedroom": REPLY,
            "Office": {"alarm": [], "timer": [TimerJsonDict()]},
        },
    )

    with pytest.raises(KeyError):
        asyncio.run(func(sensors, Mock(data={})))

    assert [c.kwargs["device"].name for c in delete.await_args_list] == ["Bedroom"]


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


@pytest.mark.parametrize("response", [None, {"alarm": []}, {"timer": []}])
def test_poll_keeps_alarms_and_timers_when_fetch_fails(
    response: JsonDict | None,
) -> None:
    """Keep the last alarms and timers without raising when a scheduled update can't fetch them.

    An error would fail the update of every device.
    """
    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    request = AsyncMock(return_value=response)
    client.request = request  # type: ignore[method-assign]
    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ALARM_IDS,
        TIMER_IDS,
    )

    asyncio.run(client.collect_data_from_endpoints(device))

    # As a poll, so an offline device isn't logged as a warning on every update
    request.assert_any_await(
        method="GET", endpoint=API_ENDPOINT_ALARMS, device=device, polling=True
    )
    assert [alarm.alarm_id for alarm in device.get_sorted_alarms()] == ALARM_IDS
    assert [timer.timer_id for timer in device.get_sorted_timers()] == TIMER_IDS

"""Tests for Google Home sensors."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from http import HTTPStatus
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aiohttp import ClientConnectorError
from aiohttp.client_exceptions import ContentTypeError
import probatio
import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARMS,
    DOMAIN,
    SENSOR,
    SERVICE_DELETE_ALARM,
    SERVICE_DELETE_ALL_ALARMS,
    SERVICE_DELETE_ALL_TIMERS,
    SERVICE_DELETE_TIMER,
    SERVICE_REBOOT,
    SERVICE_REFRESH,
)
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.exceptions import AlarmsAndTimersNotDeleted
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeSensorFeature,
    GoogleHomeTimersSensor,
    async_delete_from_devices,
    async_reboot_devices,
    async_refresh_devices,
    async_setup_entry,
)
from custom_components.google_home.types import (
    AlarmJsonDict,
    GoogleHomeData,
    JsonDict,
    TimerJsonDict,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

# pylint: enable=wrong-import-order

# A realistic master token: setup checks its length with is_aas_et()
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
    coordinator = Mock(data=device, last_update_success=True)
    sensor = GoogleHomeDeviceSensor(coordinator, Mock(), "device-id", "Kitchen", None)

    assert sensor.available is available


def test_device_sensor_unavailable_when_missing() -> None:
    """Show a device that Google no longer lists as unavailable."""
    coordinator = Mock(data=None, last_update_success=True)
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


def set_up_platform() -> Mock:
    """Set up the sensor platform, returning its batched action registrations."""
    entry = Mock(runtime_data=GoogleHomeData(Mock(), Mock(data={}), {}))
    with patch(
        "homeassistant.helpers.service.async_register_batched_platform_entity_service"
    ) as register_batched:
        asyncio.run(async_setup_entry(Mock(), entry, Mock()))
    return register_batched


def test_batched_actions_registered() -> None:
    """Batch every action, so Home Assistant calls each once with every targeted sensor."""
    register_batched = set_up_platform()

    # The delete tests run each delete action as registered
    delete = (SENSOR, async_delete_from_devices)
    assert {
        c.args[2]: (
            c.kwargs["entity_domain"],
            getattr(c.kwargs["func"], "func", c.kwargs["func"]),
        )
        for c in register_batched.call_args_list
    } == {
        SERVICE_DELETE_ALARM: delete,
        SERVICE_DELETE_TIMER: delete,
        SERVICE_DELETE_ALL_ALARMS: delete,
        SERVICE_DELETE_ALL_TIMERS: delete,
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

    Home Assistant calls it once with all of them.
    """
    [c] = [c for c in set_up_platform().call_args_list if c.args[2] == action]
    return c.kwargs["func"], c.kwargs["required_features"]


def validate(action: str, data: dict[str, object]) -> dict[str, object]:
    """Validate an action's data with its registered schema, as Home Assistant does before running it."""
    [c] = [c for c in set_up_platform().call_args_list if c.args[2] == action]
    validated: dict[str, object] = cv.make_entity_service_schema(c.kwargs["schema"])(
        {"entity_id": "sensor.kitchen_alarms", **data}
    )
    return validated


def error_message(error: HomeAssistantError) -> str:
    """Return the message Home Assistant shows for a translated error, from en.json."""
    assert error.translation_domain == DOMAIN
    assert error.translation_key is not None
    text: str = EN_TRANSLATIONS["exceptions"][error.translation_key]["message"]
    return text.format(**(error.translation_placeholders or {}))


@pytest.mark.parametrize(
    ("action", "field", "item_id"),
    [
        ("delete_alarm", "alarm_id", ALARM_IDS[0]),
        ("delete_timer", "timer_id", TIMER_IDS[0]),
    ],
)
def test_valid_id_accepted(action: str, field: str, item_id: str) -> None:
    """Accept an ID in the format the device uses."""
    assert validate(action, {field: item_id})[field] == item_id


@pytest.mark.parametrize(
    ("action", "field", "item_id", "shown_id"),
    [
        ("delete_alarm", "alarm_id", "alarm/wrong-format", "alarm/wrong-format"),
        ("delete_alarm", "alarm_id", TIMER_IDS[0], TIMER_IDS[0]),
        # Such as from a template when the sensor has no alarms
        ("delete_alarm", "alarm_id", "", ""),
        # Turned into text first, like any other text field
        ("delete_alarm", "alarm_id", 12, "12"),
        ("delete_timer", "timer_id", "timer/wrong-format", "timer/wrong-format"),
        ("delete_timer", "timer_id", ALARM_IDS[0], ALARM_IDS[0]),
    ],
)
def test_wrong_id_format_rejected(
    action: str, field: str, item_id: object, shown_id: str
) -> None:
    """Reject an ID in the wrong format before asking any device, with a translated error.

    Unlike a schema error, it lets a step with continue_on_error carry on.
    """
    with pytest.raises(ServiceValidationError) as err:
        validate(action, {field: item_id})

    assert err.value.translation_placeholders == {field: shown_id}
    assert f"“{shown_id}”" in error_message(err.value)


@pytest.mark.parametrize(
    ("action", "field"), [("delete_alarm", "alarm_id"), ("delete_timer", "timer_id")]
)
@pytest.mark.parametrize("value", ["missing", None, [ALARM_IDS[0]]])
def test_missing_id_is_a_configuration_error(
    action: str, field: str, value: object
) -> None:
    """Keep a missing ID, or one that is null or a list, a configuration error, which continue_on_error doesn't cover."""
    with pytest.raises(probatio.Invalid):
        validate(action, {} if value == "missing" else {field: value})


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
    coordinator = Mock(data=device, async_request_refresh=AsyncMock())
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
    coordinator = Mock(data=device, async_request_refresh=AsyncMock())
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
    sensor_class: type[GoogleHomeBaseEntity],
    replies: dict[str, JsonDict | None],
    delete_replies: dict[str, JsonDict | None] | None = None,
) -> tuple[list[GoogleHomeBaseEntity], AsyncMock, dict[str, Mock]]:
    """Return a sensor for each device named in replies, the delete, as a mock, and each device's coordinator by name.

    Each device sends its reply when asked for its alarms and timers. The last
    poll saw other IDs, which the delete actions must not use. A device
    confirms a delete unless delete_replies gives its reply.
    """
    devices = [
        set_alarms_and_timers(
            GoogleHomeDevice(f"{name}-id", name, "token", "192.168.1.10"),
            ["alarm/from-last-poll"],
            ["timer/from-last-poll"],
        )
        for name in replies
    ]

    async def request(
        *, method: str, device: GoogleHomeDevice, **_: object
    ) -> JsonDict | None:
        if method == "POST":
            return (delete_replies or {}).get(device.name, {"success": True})
        # A device that answers does so after the others fail, so the action
        # must wait for it before raising
        if (reply := replies[device.name]) is not None:
            await asyncio.sleep(0.01)
        return reply

    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    client.request = AsyncMock(side_effect=request)  # type: ignore[method-assign]
    delete = AsyncMock(side_effect=client.delete_alarm_or_timer)
    client.delete_alarm_or_timer = delete  # type: ignore[method-assign]
    coordinators = {
        device.name: Mock(data=device, async_request_refresh=AsyncMock())
        for device in devices
    }
    sensors = [
        sensor_class(
            coordinators[device.name], client, device.device_id, device.name, None
        )
        for device in devices
    ]
    return sensors, delete, coordinators


def devices_refreshed(coordinators: dict[str, Mock]) -> list[str]:
    """Return the names of the devices whose coordinator was asked to refresh, each time, sorted."""
    return sorted(
        name
        for name, coordinator in coordinators.items()
        for _ in coordinator.async_request_refresh.await_args_list
    )


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
    sensors, delete, coordinators = set_up_devices(
        sensor_class, {name: None if name in offline else REPLY for name in names}
    )
    call = Mock(data={})

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func(sensors, call))

    assert sorted(c.kwargs["device"].name for c in delete.await_args_list) == sorted(
        name for name in names if name not in offline
    )
    # To update the devices it deleted from
    assert devices_refreshed(coordinators) == sorted(
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
    sensors, delete, coordinators = set_up_devices(
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
    assert devices_refreshed(coordinators) == ["Bedroom"]


# Each delete-one action, its sensor, and its data for an ID the devices have
DELETE_ONE = [
    ("delete_alarm", GoogleHomeAlarmsSensor, {"alarm_id": ALARM_IDS[0]}),
    ("delete_timer", GoogleHomeTimersSensor, {"timer_id": TIMER_IDS[0]}),
]
NONE_LEFT: JsonDict = {"alarm": [], "timer": []}


@pytest.mark.parametrize(("action", "sensor_class", "data"), DELETE_ONE)
def test_delete_one_only_where_listed(
    action: str, sensor_class: type[GoogleHomeBaseEntity], data: dict[str, str]
) -> None:
    """Send the ID only to the devices that have it now, such as with an area target."""
    func, _ = get_registered_action(action)
    sensors, delete, coordinators = set_up_devices(
        sensor_class, {"Kitchen": REPLY, "Bedroom": NONE_LEFT}
    )

    asyncio.run(func(sensors, Mock(data=data)))

    assert [
        (c.kwargs["device"].name, c.kwargs["items_to_delete"])
        for c in delete.await_args_list
    ] == [("Kitchen", list(data.values()))]
    # Not the bedroom speaker, which had nothing to delete
    assert devices_refreshed(coordinators) == ["Kitchen"]


@pytest.mark.parametrize(("action", "sensor_class", "data"), DELETE_ONE)
def test_delete_one_fails_when_no_device_has_it(
    action: str, sensor_class: type[GoogleHomeBaseEntity], data: dict[str, str]
) -> None:
    """Report an ID that no targeted device has, such as from a sensor that hasn't updated yet.

    Devices answer that they deleted an ID they don't have, so the action asks
    them first. The sensor stops showing it.
    """
    func, _ = get_registered_action(action)
    [(field, item_id)] = data.items()
    sensors, delete, coordinators = set_up_devices(
        sensor_class, {"Kitchen": NONE_LEFT, "Bedroom": NONE_LEFT}
    )
    # The last poll still saw it
    for sensor in sensors:
        device = sensor.get_device()
        assert device is not None
        set_alarms_and_timers(device, ALARM_IDS[:1], TIMER_IDS[:1])

    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(func(sensors, Mock(data=data)))

    delete.assert_not_awaited()
    assert devices_refreshed(coordinators) == []
    # alarm_not_found or timer_not_found, not the invalid-ID error, which also names it
    assert err.value.translation_key == f"{field.removesuffix('_id')}_not_found"
    assert item_id in error_message(err.value)
    assert all(sensor.state == STATE_UNAVAILABLE for sensor in sensors)
    assert all(
        coordinator.async_update_listeners.call_count == 1
        for coordinator in coordinators.values()
    )


@pytest.mark.parametrize(("action", "sensor_class", "data"), DELETE_ONE)
@pytest.mark.parametrize(
    ("others", "deleted"),
    [
        # It may be on the device that didn't answer
        (NONE_LEFT, []),
        # Deleted from the other device, but it may also be on this one
        (REPLY, ["Bedroom"]),
    ],
)
def test_delete_one_names_device_it_cant_fetch(
    action: str,
    sensor_class: type[GoogleHomeBaseEntity],
    data: dict[str, str],
    others: JsonDict,
    deleted: list[str],
) -> None:
    """Name a device that didn't answer, rather than say that no device has the ID."""
    func, _ = get_registered_action(action)
    sensors, delete, coordinators = set_up_devices(
        sensor_class, {"Kitchen": None, "Bedroom": others}
    )

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func(sensors, Mock(data=data)))

    assert [c.kwargs["device"].name for c in delete.await_args_list] == deleted
    assert devices_refreshed(coordinators) == deleted
    assert err.value.translation_key == "alarms_and_timers_not_fetched"
    assert "Kitchen" in error_message(err.value)


@pytest.mark.parametrize(
    ("action", "sensor_class", "data"),
    [
        *DELETE_ONE,
        ("delete_all_alarms", GoogleHomeAlarmsSensor, {}),
        ("delete_all_timers", GoogleHomeTimersSensor, {}),
    ],
)
def test_delete_names_every_device_that_failed(
    action: str, sensor_class: type[GoogleHomeBaseEntity], data: dict[str, str]
) -> None:
    """Name every device that didn't answer or confirm the delete, in one error.

    Refresh the device that didn't confirm it: the delete may still have happened.
    """
    func, _ = get_registered_action(action)
    sensors, _, coordinators = set_up_devices(
        sensor_class,
        {"Office": None, "Bedroom": NONE_LEFT, "Kitchen": REPLY},
        delete_replies={"Kitchen": {"success": False}},
    )

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func(sensors, Mock(data=data)))

    assert devices_refreshed(coordinators) == ["Kitchen"]
    assert err.value.translation_key == "alarms_and_timers_not_deleted_from_devices"
    # In alphabetical order, without the device that had nothing to delete
    assert err.value.translation_placeholders == {"devices": "Kitchen, Office"}
    assert "Kitchen, Office" in error_message(err.value)


@pytest.mark.parametrize(
    ("action", "data"),
    [("delete_alarm", {"alarm_id": ALARM_IDS[0]}), ("delete_all_alarms", {})],
)
def test_delete_not_confirmed_shows_current_alarms(
    action: str, data: dict[str, str]
) -> None:
    """Show the alarms the device has now, although it didn't confirm the delete.

    Without a refresh, the sensor would otherwise show the last poll's alarms
    until the next update.
    """
    func, _ = get_registered_action(action)
    sensors, _, coordinators = set_up_devices(
        GoogleHomeAlarmsSensor,
        {"Kitchen": REPLY},
        delete_replies={"Kitchen": {"success": False}},
    )
    [sensor] = sensors
    assert isinstance(sensor, GoogleHomeAlarmsSensor)
    shown: list[list[str]] = []
    coordinators["Kitchen"].async_update_listeners.side_effect = lambda: shown.append(
        [alarm["alarm_id"] for alarm in sensor.extra_state_attributes["alarms"]]
    )

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func(sensors, Mock(data={**data, "skip_refresh": True})))

    # Not the last poll's alarm/from-last-poll; the alarms it may still have stay
    assert shown == [ALARM_IDS]
    assert devices_refreshed(coordinators) == []
    assert err.value.translation_key == "alarms_and_timers_not_deleted"
    assert "Kitchen" in error_message(err.value)


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
    client = Mock(
        # The device still has them
        update_alarms_and_timers=AsyncMock(return_value=device),
        delete_alarm_or_timer=AsyncMock(side_effect=confirm_delete),
    )
    coordinator = Mock(data=device)
    sensor = sensor_class(coordinator, client, "device-id", "Kitchen", None)
    shown: list[str | None] = []
    coordinator.async_update_listeners.side_effect = lambda: shown.append(sensor.state)

    asyncio.run(getattr(sensor, action)(Mock(data=data)))

    assert shown == [STATE_UNAVAILABLE]


@pytest.mark.parametrize(
    ("action", "action_data"),
    [
        ("delete_alarm", {"alarm_id": ALARM_IDS[0]}),
        ("delete_timer", {"timer_id": TIMER_IDS[0]}),
        ("delete_all_alarms", {}),
        ("delete_all_timers", {}),
    ],
)
@pytest.mark.parametrize(
    ("data", "refreshed"),
    [({}, True), ({"skip_refresh": False}, True), ({"skip_refresh": True}, False)],
)
def test_delete_skip_refresh(
    action: str,
    action_data: dict[str, str],
    data: dict[str, str | bool],
    refreshed: bool,
) -> None:
    """Refresh the device after deleting unless skip_refresh is set."""
    _, coordinator, _, _ = run_action(
        action, {**action_data, **data}, ALARM_IDS, TIMER_IDS
    )

    assert coordinator.async_request_refresh.await_count == int(refreshed)


@pytest.mark.parametrize(
    ("action", "sensor_class", "data"),
    [
        ("delete_alarm", GoogleHomeAlarmsSensor, {"alarm_id": ALARM_IDS[0]}),
        ("delete_timer", GoogleHomeTimersSensor, {"timer_id": TIMER_IDS[0]}),
        ("delete_all_alarms", GoogleHomeAlarmsSensor, {}),
        ("delete_all_timers", GoogleHomeTimersSensor, {}),
    ],
)
def test_delete_from_several_devices_refreshes_each_once(
    action: str, sensor_class: type[GoogleHomeBaseEntity], data: dict[str, str]
) -> None:
    """Refresh each device once, after deleting from it."""
    func, _ = get_registered_action(action)
    sensors, delete, coordinators = set_up_devices(
        sensor_class, {"Kitchen": REPLY, "Bedroom": REPLY}
    )
    # The devices deleted from by the time each device was refreshed
    deleted_before: dict[str, list[str]] = {}
    for name, coordinator in coordinators.items():
        coordinator.async_request_refresh.side_effect = lambda name=name: (
            deleted_before.setdefault(
                name, [c.kwargs["device"].name for c in delete.await_args_list]
            )
        )

    asyncio.run(func(sensors, Mock(data=data)))

    assert devices_refreshed(coordinators) == ["Bedroom", "Kitchen"]
    assert all(name in deleted for name, deleted in deleted_before.items())


@pytest.mark.parametrize(
    ("action", "sensor_class", "data"),
    [
        ("delete_alarm", GoogleHomeAlarmsSensor, {"alarm_id": ALARM_IDS[0]}),
        ("delete_timer", GoogleHomeTimersSensor, {"timer_id": TIMER_IDS[0]}),
        ("delete_all_alarms", GoogleHomeAlarmsSensor, {}),
        ("delete_all_timers", GoogleHomeTimersSensor, {}),
    ],
)
def test_delete_fails_when_device_is_gone(
    action: str, sensor_class: type[GoogleHomeBaseEntity], data: dict[str, str]
) -> None:
    """Report an error, send no request and don't refresh when the last update no longer has the device."""
    func, _ = get_registered_action(action)
    sensors, delete, coordinators = set_up_devices(sensor_class, {"Kitchen": REPLY})
    # As the account's update leaves the device's coordinator
    coordinators["Kitchen"].data = None

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func(sensors, Mock(data=data)))

    delete.assert_not_awaited()
    assert devices_refreshed(coordinators) == []
    assert err.value.translation_key == "alarms_and_timers_not_fetched"
    assert "Kitchen" in error_message(err.value)


def test_reboot_devices_once_each() -> None:
    """Reboot each device once, though a device target selects two of its sensors."""
    devices = [
        GoogleHomeDevice(device_id, device_id, "token", "192.168.1.10")
        for device_id in ("kitchen", "bedroom")
    ]
    client = Mock(reboot_google_device=AsyncMock())
    sensors: list[GoogleHomeBaseEntity] = [
        sensor_class(Mock(data=device), client, device.device_id, device.name, None)
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

    client = Mock(reboot_google_device=AsyncMock(side_effect=reboot))
    sensors: list[GoogleHomeBaseEntity] = [
        GoogleHomeAlarmsSensor(Mock(data=d), client, d.device_id, d.name, None)
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


def test_delete_alarm_or_timer_removes_deleted_ids() -> None:
    """Remove only the deleted IDs from the device, once it confirms deleting them."""
    client = GlocaltokensApiClient(Mock(), Mock(), master_token=MASTER_TOKEN)
    client.request = AsyncMock(return_value={"success": True})  # type: ignore[method-assign]
    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ALARM_IDS,
        TIMER_IDS,
    )

    asyncio.run(client.delete_alarm_or_timer(device, ALARM_IDS[:1]))

    assert [alarm.alarm_id for alarm in device.get_sorted_alarms()] == ALARM_IDS[1:]
    assert [timer.timer_id for timer in device.get_sorted_timers()] == TIMER_IDS


def answering(status: HTTPStatus = HTTPStatus.OK, **json_mock: object) -> Mock:
    """Return a session to which the device answers with this status, and json() set up as given."""
    answer = MagicMock(status=status, json=AsyncMock(**json_mock))
    response = MagicMock()
    response.__aenter__.return_value = answer
    return Mock(request=Mock(return_value=response))


INVALID_JSON = json.JSONDecodeError("Expecting value", "<html>", 0)


@pytest.mark.parametrize(
    "session",
    [
        # A reply whose content type says JSON, but isn't
        pytest.param(answering(side_effect=INVALID_JSON), id="invalid-json"),
        pytest.param(
            answering(side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")),
            id="undecodable",
        ),
        pytest.param(
            answering(side_effect=ContentTypeError(Mock(), ())), id="not-json"
        ),
        pytest.param(answering(return_value=None), id="empty-body"),
        pytest.param(answering(HTTPStatus.INTERNAL_SERVER_ERROR), id="server-error"),
        pytest.param(
            Mock(request=Mock(side_effect=ClientConnectorError(Mock(), OSError()))),
            id="offline",
        ),
        pytest.param(Mock(request=Mock(side_effect=TimeoutError())), id="timed-out"),
        pytest.param(answering(return_value={"success": False}), id="refused"),
        pytest.param(answering(return_value={}), id="no-success"),
        # Only the boolean confirms
        pytest.param(answering(return_value={"success": "true"}), id="text-true"),
        pytest.param(answering(return_value={"success": 1}), id="number"),
        pytest.param(answering(return_value=[{"success": True}]), id="list"),
        pytest.param(answering(return_value="success"), id="text"),
    ],
)
def test_delete_alarm_or_timer_fails_unless_confirmed(session: Mock) -> None:
    """Report a delete the device doesn't confirm, naming it, and keep the IDs it may still have."""
    client = GlocaltokensApiClient(Mock(), session, master_token=MASTER_TOKEN)
    device = set_alarms_and_timers(
        GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10"),
        ALARM_IDS,
        TIMER_IDS,
    )

    with pytest.raises(AlarmsAndTimersNotDeleted) as err:
        asyncio.run(client.delete_alarm_or_timer(device, ALARM_IDS[:1]))

    assert session.request.call_count == 1
    assert "Kitchen" in error_message(err.value)
    assert [alarm.alarm_id for alarm in device.get_sorted_alarms()] == ALARM_IDS


def test_delete_alarm_or_timer_keeps_why_reply_is_invalid() -> None:
    """Keep the decoding error as the cause."""
    client = GlocaltokensApiClient(
        Mock(), answering(side_effect=INVALID_JSON), master_token=MASTER_TOKEN
    )
    device = GoogleHomeDevice("device-id", "Kitchen", "token", "192.168.1.10")

    with pytest.raises(AlarmsAndTimersNotDeleted) as err:
        asyncio.run(client.delete_alarm_or_timer(device, ALARM_IDS[:1]))

    assert err.value.__cause__ is INVALID_JSON


def test_delete_alarm_or_timer_raises_other_errors() -> None:
    """Raise an error that isn't about the device's reply as it is, such as a stored address that isn't one."""
    session = answering(return_value={"success": True})
    client = GlocaltokensApiClient(Mock(), session, master_token=MASTER_TOKEN)
    device = GoogleHomeDevice("device-id", "Kitchen", "token", "not-an-address")

    with pytest.raises(ValueError, match="not-an-address"):
        asyncio.run(client.delete_alarm_or_timer(device, ALARM_IDS[:1]))

    session.request.assert_not_called()


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
    # Its info doesn't answer either
    session = Mock(get=Mock(side_effect=TimeoutError()))
    client = GlocaltokensApiClient(Mock(), session, master_token=MASTER_TOKEN)
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

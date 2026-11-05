"""Sensor platform for Google Home."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import IntFlag
from functools import partial
import logging
from typing import Literal, override

import probatio

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ENTITY_MATCH_ALL,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    STATE_UNAVAILABLE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    service,
    target,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import VolDictType, VolSchemaType

from .const import (
    ALARM_AND_TIMER_ID_LENGTH,
    DOMAIN,
    GOOGLE_HOME_ALARM_DEFAULT_VALUE,
    LABEL_ALARMS,
    LABEL_DEVICE,
    LABEL_TIMERS,
    LABEL_UPTIME,
    LABEL_WIFI_NETWORK,
    LABEL_WIFI_SIGNAL,
    SENSOR,
    SERVICE_ATTR_ALARM_ID,
    SERVICE_ATTR_SKIP_REFRESH,
    SERVICE_ATTR_TIMER_ID,
    SERVICE_DELETE_ALARM,
    SERVICE_DELETE_ALL_ALARMS,
    SERVICE_DELETE_ALL_TIMERS,
    SERVICE_DELETE_TIMER,
    SERVICE_REBOOT,
    SERVICE_REFRESH,
)
from .entity import (
    GoogleHomeAddressedEntity,
    GoogleHomeBaseEntity,
    GoogleHomeFeatureEntity,
    async_add_device_entities,
)
from .exceptions import (
    AlarmsAndTimersNotDeleted,
    AlarmsAndTimersNotFetched,
    DeviceRequestFailed,
)
from .models import (
    LAST_ALARM_STATUSES,
    GoogleHomeAlarmStatus,
    GoogleHomeDevice,
    GoogleHomeTimerStatus,
)
from .types import (
    AlarmsAttributes,
    DeviceAttributes,
    GoogleHomeAlarmDict,
    GoogleHomeConfigEntry,
    GoogleHomeTimerDict,
    TimersAttributes,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

# The coordinator does the updates. The integration's own actions, such as
# reboot_device, get all their sensors in one call, which this limit doesn't cover.
PARALLEL_UPDATES = 0


class GoogleHomeSensorFeature(IntFlag):
    """Actions a sensor supports, so a device target runs each on its own sensor."""

    ALARMS = 1
    TIMERS = 2


def valid_id(kind: Literal["alarm", "timer"]) -> Callable[[str], str]:
    """Return a check that an ID is an alarm or a timer ID, for an action's schema.

    It raises an error that is translated and that continue_on_error covers,
    unlike a schema error.
    """

    def check(item_id: str) -> str:
        if not (
            item_id.startswith(f"{kind}/") and len(item_id) == ALARM_AND_TIMER_ID_LENGTH
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                # invalid_alarm_id or invalid_timer_id
                translation_key=f"invalid_{kind}_id",
                translation_placeholders={f"{kind}_id": item_id},
            )
        return item_id

    return check


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Set up sensor platform."""
    # Devices without alarms have diagnostic info too
    async_add_device_entities(
        entry,
        async_add_devices,
        GoogleHomeDeviceSensor,
        WifiNetworkSensor,
        WifiSignalSensor,
        UptimeSensor,
        needs_answer=False,
    )
    async_add_device_entities(
        entry, async_add_devices, GoogleHomeAlarmsSensor, GoogleHomeTimersSensor
    )
    return True


@callback
def async_setup_actions(hass: HomeAssistant) -> None:
    """Register the actions when the integration is set up, before its entry.

    They then exist, so automations and scripts that use them stay valid, also
    while the entry isn't loaded. A call then fails instead of doing nothing.
    """

    def entry_loaded(data: dict[str, object]) -> dict[str, object]:
        # Unless the entry is loaded, raises Home Assistant's own translated
        # error, which continue_on_error covers
        service.async_get_config_entry(hass, DOMAIN, None)
        return data

    def when_loaded(fields: VolDictType) -> VolSchemaType:
        """Check an action's data, then that the entry is loaded.

        Home Assistant checks the data before it looks for the targeted sensors,
        and finds none while the entry isn't loaded.
        """
        return probatio.All(cv.make_entity_service_schema(fields), entry_loaded)

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_ALARM,
        entity_domain=SENSOR,
        schema=when_loaded(
            {
                probatio.Required(SERVICE_ATTR_ALARM_ID): probatio.All(
                    cv.string, valid_id("alarm")
                ),
                probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean,
            }
        ),
        func=partial(
            async_delete_from_devices,
            GoogleHomeAlarmsSensor.async_delete_alarm,
            kind="alarm",
        ),
        required_features=[GoogleHomeSensorFeature.ALARMS],
    )

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_TIMER,
        entity_domain=SENSOR,
        schema=when_loaded(
            {
                probatio.Required(SERVICE_ATTR_TIMER_ID): probatio.All(
                    cv.string, valid_id("timer")
                ),
                probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean,
            }
        ),
        func=partial(
            async_delete_from_devices,
            GoogleHomeTimersSensor.async_delete_timer,
            kind="timer",
        ),
        required_features=[GoogleHomeSensorFeature.TIMERS],
    )

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_ALL_ALARMS,
        entity_domain=SENSOR,
        schema=when_loaded({probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean}),
        func=partial(
            async_delete_from_devices, GoogleHomeAlarmsSensor.async_delete_all
        ),
        required_features=[GoogleHomeSensorFeature.ALARMS],
    )

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_ALL_TIMERS,
        entity_domain=SENSOR,
        schema=when_loaded({probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean}),
        func=partial(
            async_delete_from_devices, GoogleHomeTimersSensor.async_delete_all
        ),
        required_features=[GoogleHomeSensorFeature.TIMERS],
    )

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_REBOOT,
        entity_domain=SENSOR,
        schema=when_loaded({}),
        func=async_reboot_devices,
    )

    # A plain action: Home Assistant doesn't run entity actions on unavailable sensors
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, async_refresh_devices, schema=when_loaded({})
    )


async def async_refresh_devices(call: ServiceCall) -> None:
    """Refresh all devices once if the target covers a Google Home sensor, even an unavailable one.

    Like Home Assistant's entity actions, a user who isn't an admin needs control
    of every entity the target covers, and with entity_id: all only the sensors
    they control count.
    """
    hass = call.hass
    may_control: Callable[[str, str], bool] | None = None
    if call.context.user_id:
        user = await hass.auth.async_get_user(call.context.user_id)
        if user is None:
            raise UnknownUser(context=call.context)
        if not user.is_admin:
            may_control = user.permissions.check_entity
    entry: GoogleHomeConfigEntry = service.async_get_config_entry(hass, DOMAIN, None)
    # Also the sensors of a device that hasn't answered since setup, which aren't
    # added until it does
    sensors = {
        registered.entity_id
        for registered in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if registered.domain == SENSOR and not registered.disabled
    }
    selection = target.TargetSelection(call.data)
    if call.data.get(ATTR_ENTITY_ID) == ENTITY_MATCH_ALL:
        targeted = sensors - target.async_extract_excluded_entity_ids(hass, selection)
        if may_control is not None:
            targeted = {e for e in targeted if may_control(e, POLICY_CONTROL)}
    else:
        selected = target.async_extract_referenced_entity_ids(hass, selection)
        referenced = selected.referenced | selected.indirectly_referenced
        if may_control is not None:
            for entity_id in referenced:
                if not may_control(entity_id, POLICY_CONTROL):
                    raise Unauthorized(
                        context=call.context,
                        entity_id=entity_id,
                        permission=POLICY_CONTROL,
                    )
        targeted = referenced & sensors
        selected.log_missing(selected.referenced - targeted, _LOGGER)
    if not targeted:
        return
    await asyncio.gather(
        *(
            coordinator.async_request_refresh()
            for coordinator in entry.runtime_data.devices.values()
        )
    )


async def async_fetch_current(entity: GoogleHomeBaseEntity) -> GoogleHomeDevice:
    """Return the entity's device with the alarms and timers it has now."""
    if (device := entity.get_device()) is None:
        raise AlarmsAndTimersNotFetched(entity.device_name)
    return await entity.client.update_alarms_and_timers(device, polling=False)


async def async_delete(
    entity: GoogleHomeBaseEntity, device: GoogleHomeDevice, ids: list[str]
) -> bool:
    """Delete these alarms or timers from the device and show what is left.

    Return whether there was anything to delete.
    """
    try:
        if ids:
            await entity.client.delete_alarm_or_timer(
                device=device, items_to_delete=ids
            )
        else:
            _LOGGER.debug("Nothing to delete for %s", device.name)
    finally:
        # Show what was just fetched also when the device doesn't confirm the delete
        entity.async_show_device_changes()
    return bool(ids)


async def async_delete_from_devices[_SensorT: GoogleHomeBaseEntity](
    delete: Callable[[_SensorT, ServiceCall], Awaitable[bool]],
    entities: list[_SensorT],
    call: ServiceCall,
    *,
    kind: Literal["alarm", "timer"] | None = None,
) -> None:
    """Delete from each device, then name every device that failed.

    Request a refresh of each device that a delete request was sent to, unless
    skip_refresh is set. With kind, the action deletes one alarm or timer, and
    fails if every device answered and none has it.
    """

    async def delete_from(entity: _SensorT) -> bool:
        # Like Home Assistant's per-entity calls, so the logbook shows that the
        # action changed the sensor
        entity.async_set_context(call.context)
        return await delete(entity, call)

    results = await asyncio.gather(
        *(delete_from(entity) for entity in entities), return_exceptions=True
    )
    # A delete that the device didn't confirm may still have happened
    sent_to = [
        entity
        for entity, result in zip(entities, results, strict=True)
        if result is True or isinstance(result, AlarmsAndTimersNotDeleted)
    ]
    if not call.data.get(SERVICE_ATTR_SKIP_REFRESH, False):
        await asyncio.gather(
            *(entity.coordinator.async_request_refresh() for entity in sent_to)
        )
    failed: list[AlarmsAndTimersNotFetched | AlarmsAndTimersNotDeleted] = []
    for result in results:
        if isinstance(result, AlarmsAndTimersNotFetched | AlarmsAndTimersNotDeleted):
            failed.append(result)
        # Don't hide an unexpected error
        elif isinstance(result, BaseException):
            raise result
    if len(failed) > 1:
        # One Refresh devices covers every device, so the error needn't say which
        # needs it
        if any(error.refresh_needed for error in failed):
            key = (
                "alarms_and_timers_not_deleted_from_devices_token_rejected_polling_off"
            )
        elif all(isinstance(error, AlarmsAndTimersNotFetched) for error in failed):
            key = "alarms_and_timers_not_fetched_from_devices"
        else:
            key = "alarms_and_timers_not_deleted_from_devices"
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={
                "devices": ", ".join(sorted(error.device_name for error in failed))
            },
        )
    if failed:
        raise failed[0]
    # Every device answered. A device that failed could have had the alarm or timer.
    if kind is not None and not sent_to:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            # alarm_not_found or timer_not_found
            translation_key=f"{kind}_not_found",
            translation_placeholders={f"{kind}_id": call.data[f"{kind}_id"]},
        )


async def async_reboot_devices(
    entities: list[GoogleHomeBaseEntity], _call: ServiceCall
) -> None:
    """Reboot the device of each entity, once per device, then name every device that failed.

    One device that failed raises its own error, which says why.
    """
    one_per_device = {entity.device_id: entity for entity in entities}.values()
    results = await asyncio.gather(
        *(entity.async_reboot_device() for entity in one_per_device),
        return_exceptions=True,
    )
    # Like Home Assistant's per-entity calls: finish every reboot, then raise.
    failed: list[DeviceRequestFailed] = []
    for result in results:
        if isinstance(result, DeviceRequestFailed):
            failed.append(result)
        elif isinstance(result, BaseException):
            raise result
    if len(failed) > 1:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="devices_not_rebooted",
            translation_placeholders={
                "devices": ", ".join(sorted(error.device_name for error in failed))
            },
        )
    if failed:
        raise failed[0]


class GoogleHomeDeviceSensor(GoogleHomeAddressedEntity):
    """Google Home Device sensor."""

    _attr_translation_key = "device"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_DEVICE

    @property
    @override
    def state(self) -> str | None:
        """Return device IP address if any."""
        device = self.get_device()
        return device.ip_address if device else None

    @property
    @override
    def extra_state_attributes(self) -> DeviceAttributes | None:
        """Return the state attributes, or None while Google doesn't list the device."""
        device = self.get_device()
        return self.get_device_attributes(device) if device else None

    @staticmethod
    def get_device_attributes(device: GoogleHomeDevice) -> DeviceAttributes:
        """Device representation as dictionary."""
        return {
            "device_id": device.device_id,
            "device_name": device.name,
            "home": device.home_name,
            "auth_token": device.auth_token,
            "ip_address": device.ip_address,
            "available": device.reachable,
        }


class InfoSensor(GoogleHomeAddressedEntity, SensorEntity):
    """What the device's info said at the last firmware check.

    Disabled by default, as few users need it. Every device gets it, also one that
    doesn't report the value, whose sensor stays unknown.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class WifiNetworkSensor(InfoSensor):
    """The name (SSID) of the Wi-Fi network that the device uses."""

    _attr_translation_key = "wifi_network"

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_WIFI_NETWORK

    @property
    @override
    def native_value(self) -> str | None:
        """Return the network's name, or None until the device gives one."""
        device = self.get_device()
        return device.wifi_ssid if device else None


class WifiSignalSensor(InfoSensor):
    """The device's Wi-Fi signal strength, which a Nest Hub doesn't report.

    Without a translation key, Home Assistant names it after its device class, in its
    language.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_WIFI_SIGNAL

    @property
    @override
    def native_value(self) -> float | None:
        """Return the signal strength in dBm, or None until the device gives it."""
        device = self.get_device()
        return device.wifi_signal if device else None


class UptimeSensor(InfoSensor):
    """Estimated last boot, with Home Assistant's localized name and drift tolerance."""

    _attr_device_class = SensorDeviceClass.UPTIME

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_UPTIME

    @property
    @override
    def native_value(self) -> datetime | None:
        """Return the stored estimate, or None until the device reports valid uptime."""
        device = self.get_device()
        return device.booted_at if device else None


class GoogleHomeAlarmsSensor(GoogleHomeFeatureEntity):
    """Google Home Alarms sensor."""

    _attr_translation_key = "alarms"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_supported_features = GoogleHomeSensorFeature.ALARMS

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_ALARMS

    @property
    @override
    def state(self) -> str | None:
        """Return next alarm if available."""
        device = self.get_device()
        if not device:
            return None
        next_alarm = device.get_next_alarm()
        return (
            next_alarm.local_time_iso
            if next_alarm and next_alarm.status not in LAST_ALARM_STATUSES
            else STATE_UNAVAILABLE
        )

    @property
    @override
    def extra_state_attributes(self) -> AlarmsAttributes:
        """Return the state attributes."""
        return {
            "next_alarm_status": self._get_next_alarm_status(),
            "alarm_volume": self._get_alarm_volume(),
            "alarms": self._get_alarms_data(),
        }

    def _get_next_alarm_status(self) -> str:
        """Update next alarm status from coordinator."""
        device = self.get_device()
        next_alarm = device.get_next_alarm() if device else None
        return (
            next_alarm.status.name.lower()
            if next_alarm
            else GoogleHomeAlarmStatus.NONE.name.lower()
        )

    def _get_alarm_volume(self) -> float:
        """Update alarm volume status from coordinator."""
        device = self.get_device()
        alarm_volume = device.alarm_volume if device else None
        return alarm_volume or GOOGLE_HOME_ALARM_DEFAULT_VALUE

    def _get_alarms_data(self) -> list[GoogleHomeAlarmDict]:
        """Update alarms data extracting it from coordinator."""
        device = self.get_device()
        return (
            [alarm.as_dict() for alarm in device.get_sorted_alarms()] if device else []
        )

    async def async_delete_alarm(self, call: ServiceCall) -> bool:
        """Service call to delete alarm on device, if the device has it now."""
        device = await async_fetch_current(self)
        alarm_id: str = call.data[SERVICE_ATTR_ALARM_ID]
        has_it = any(alarm.alarm_id == alarm_id for alarm in device.get_sorted_alarms())
        return await async_delete(self, device, [alarm_id] if has_it else [])

    async def async_delete_all(self, _call: ServiceCall) -> bool:
        """Service call to delete all alarms on device."""
        device = await async_fetch_current(self)
        alarm_ids = [alarm.alarm_id for alarm in device.get_sorted_alarms()]
        return await async_delete(self, device, alarm_ids)


class GoogleHomeTimersSensor(GoogleHomeFeatureEntity):
    """Google Home Timers sensor."""

    _attr_translation_key = "timers"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_supported_features = GoogleHomeSensorFeature.TIMERS

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_TIMERS

    @property
    @override
    def state(self) -> str | None:
        """Return next timer if available."""
        device = self.get_device()
        if not device:
            return None
        timer = device.get_next_timer()
        return (
            timer.local_time_iso
            if timer
            and timer.local_time_iso
            and timer.status is not GoogleHomeTimerStatus.UNKNOWN
            else STATE_UNAVAILABLE
        )

    @property
    @override
    def extra_state_attributes(self) -> TimersAttributes:
        """Return the state attributes."""
        return {
            "next_timer_status": self._get_next_timer_status(),
            "timers": self._get_timers_data(),
        }

    def _get_next_timer_status(self) -> str:
        """Update next timer status from coordinator."""
        device = self.get_device()
        next_timer = device.get_next_timer() if device else None
        return (
            next_timer.status.name.lower()
            if next_timer
            else GoogleHomeTimerStatus.NONE.name.lower()
        )

    def _get_timers_data(self) -> list[GoogleHomeTimerDict]:
        """Update timers data extracting it from coordinator."""
        device = self.get_device()
        return (
            [timer.as_dict() for timer in device.get_sorted_timers()] if device else []
        )

    async def async_delete_timer(self, call: ServiceCall) -> bool:
        """Service call to delete timer on device, if the device has it now."""
        device = await async_fetch_current(self)
        timer_id: str = call.data[SERVICE_ATTR_TIMER_ID]
        has_it = any(timer.timer_id == timer_id for timer in device.get_sorted_timers())
        return await async_delete(self, device, [timer_id] if has_it else [])

    async def async_delete_all(self, _call: ServiceCall) -> bool:
        """Service call to delete all timers on device."""
        device = await async_fetch_current(self)
        timer_ids = [timer.timer_id for timer in device.get_sorted_timers()]
        return await async_delete(self, device, timer_ids)

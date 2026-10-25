"""Sensor platform for Google Home."""

import asyncio
from collections.abc import Awaitable, Callable
from enum import IntFlag
from functools import partial
import logging
from typing import override

import probatio

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import (
    ALARM_AND_TIMER_ID_LENGTH,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    GOOGLE_HOME_ALARM_DEFAULT_VALUE,
    ICON_ALARMS,
    ICON_TIMERS,
    ICON_TOKEN,
    LABEL_ALARMS,
    LABEL_DEVICE,
    LABEL_TIMERS,
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
from .entity import GoogleHomeBaseEntity, async_add_device_entities
from .exceptions import AlarmsAndTimersNotFetched
from .models import GoogleHomeAlarmStatus, GoogleHomeDevice, GoogleHomeTimerStatus
from .types import (
    AlarmsAttributes,
    DeviceAttributes,
    GoogleHomeAlarmDict,
    GoogleHomeConfigEntry,
    GoogleHomeTimerDict,
    TimersAttributes,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeSensorFeature(IntFlag):
    """Actions a sensor supports, so a device target runs each on its own sensor."""

    ALARMS = 1
    TIMERS = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Set up sensor platform."""
    client: GlocaltokensApiClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]
    async_add_device_entities(
        entry,
        coordinator,
        client,
        async_add_devices,
        GoogleHomeDeviceSensor,
        needs_answer=False,
    )
    async_add_device_entities(
        entry,
        coordinator,
        client,
        async_add_devices,
        GoogleHomeAlarmsSensor,
        GoogleHomeTimersSensor,
    )

    # Services
    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_ALARM,
        entity_domain=SENSOR,
        schema={
            probatio.Required(SERVICE_ATTR_ALARM_ID): cv.string,
            probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean,
        },
        func=partial(
            async_delete_from_devices, GoogleHomeAlarmsSensor.async_delete_alarm
        ),
        required_features=[GoogleHomeSensorFeature.ALARMS],
    )

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_TIMER,
        entity_domain=SENSOR,
        schema={
            probatio.Required(SERVICE_ATTR_TIMER_ID): cv.string,
            probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean,
        },
        func=partial(
            async_delete_from_devices, GoogleHomeTimersSensor.async_delete_timer
        ),
        required_features=[GoogleHomeSensorFeature.TIMERS],
    )

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_ALL_ALARMS,
        entity_domain=SENSOR,
        schema={probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean},
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
        schema={probatio.Optional(SERVICE_ATTR_SKIP_REFRESH): cv.boolean},
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
        schema={},
        func=async_reboot_devices,
    )

    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_REFRESH,
        entity_domain=SENSOR,
        schema={},
        func=async_refresh_devices,
    )

    return True


async def async_refresh_devices(
    entities: list[GoogleHomeBaseEntity], _call: ServiceCall
) -> None:
    """Refresh all devices once, however many sensors are targeted."""
    # The integration allows one config entry, so all sensors share its coordinator
    await entities[0].coordinator.async_request_refresh()


async def async_delete(
    entity: GoogleHomeBaseEntity, device: GoogleHomeDevice, ids: list[str]
) -> bool:
    """Delete these alarms or timers from the device and show what is left.

    Return whether there was anything to delete.
    """
    if ids:
        await entity.client.delete_alarm_or_timer(device=device, items_to_delete=ids)
    else:
        _LOGGER.debug("Nothing to delete for %s", device.name)
    # Other entities show this device's data too
    entity.coordinator.async_update_listeners()
    return bool(ids)


async def async_delete_from_devices[_SensorT: GoogleHomeBaseEntity](
    delete: Callable[[_SensorT, ServiceCall], Awaitable[bool]],
    entities: list[_SensorT],
    call: ServiceCall,
) -> None:
    """Delete from each device, then name every device that failed.

    Refresh all devices once if a delete request was sent, unless skip_refresh is set.
    """

    async def delete_from(entity: _SensorT) -> bool:
        # Like Home Assistant's per-entity calls, so the logbook shows that the
        # action changed the sensor
        entity.async_set_context(call.context)
        return await delete(entity, call)

    results = await asyncio.gather(
        *(delete_from(entity) for entity in entities), return_exceptions=True
    )
    # One refresh updates every device. Another request while it runs or in the
    # debouncer's cooldown after it would poll them all again when that ends
    sent = any(result is True for result in results)
    if sent and not call.data.get(SERVICE_ATTR_SKIP_REFRESH, False):
        await entities[0].coordinator.async_request_refresh()
    not_fetched: list[AlarmsAndTimersNotFetched] = []
    for result in results:
        if isinstance(result, AlarmsAndTimersNotFetched):
            not_fetched.append(result)
        # Don't hide an unexpected error, such as from a malformed reply
        elif isinstance(result, BaseException):
            raise result
    if len(not_fetched) > 1:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="alarms_and_timers_not_fetched_from_devices",
            translation_placeholders={
                "devices": ", ".join(sorted(error.device_name for error in not_fetched))
            },
        )
    if not_fetched:
        raise not_fetched[0]


async def async_reboot_devices(
    entities: list[GoogleHomeBaseEntity], _call: ServiceCall
) -> None:
    """Reboot the device of each entity, once per device."""
    one_per_device = {entity.device_id: entity for entity in entities}.values()
    results = await asyncio.gather(
        *(entity.async_reboot_device() for entity in one_per_device),
        return_exceptions=True,
    )
    # Like Home Assistant's per-entity calls: finish every reboot, then raise.
    for result in results:
        if isinstance(result, BaseException):
            raise result


class GoogleHomeDeviceSensor(GoogleHomeBaseEntity):
    """Google Home Device sensor."""

    _attr_icon = ICON_TOKEN
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    @override
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_DEVICE

    @property
    @override
    def available(self) -> bool:
        """Return whether the device was found on the network."""
        device = self.get_device()
        return (
            super().available and device is not None and device.ip_address is not None
        )

    @property
    @override
    def state(self) -> str | None:
        """Return device IP address if any."""
        device = self.get_device()
        return device.ip_address if device else None

    @property
    @override
    def extra_state_attributes(self) -> DeviceAttributes:
        """Return the state attributes."""
        device = self.get_device()
        attributes: DeviceAttributes = {
            "device_id": None,
            "device_name": self.device_name,
            "auth_token": None,
            "ip_address": None,
            "available": False,
        }
        return self.get_device_attributes(device) if device else attributes

    @staticmethod
    def get_device_attributes(device: GoogleHomeDevice) -> DeviceAttributes:
        """Device representation as dictionary."""
        return {
            "device_id": device.device_id,
            "device_name": device.name,
            "auth_token": device.auth_token,
            "ip_address": device.ip_address,
            "available": device.available,
        }


class GoogleHomeAlarmsSensor(GoogleHomeBaseEntity):
    """Google Home Alarms sensor."""

    _attr_icon = ICON_ALARMS
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_supported_features = GoogleHomeSensorFeature.ALARMS

    @property
    @override
    def label(self) -> str:
        """Label to use for name and unique id."""
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
            if next_alarm
            and next_alarm.status
            not in {GoogleHomeAlarmStatus.INACTIVE, GoogleHomeAlarmStatus.MISSED}
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
        alarm_volume = device.get_alarm_volume() if device else None
        return alarm_volume or GOOGLE_HOME_ALARM_DEFAULT_VALUE

    def _get_alarms_data(self) -> list[GoogleHomeAlarmDict]:
        """Update alarms data extracting it from coordinator."""
        device = self.get_device()
        return (
            [alarm.as_dict() for alarm in device.get_sorted_alarms()] if device else []
        )

    @staticmethod
    def is_valid_alarm_id(alarm_id: str) -> bool:
        """Check if the alarm id provided is valid."""
        return (
            alarm_id.startswith("alarm/") and len(alarm_id) == ALARM_AND_TIMER_ID_LENGTH
        )

    async def async_delete_alarm(self, call: ServiceCall) -> bool:
        """Service call to delete alarm on device."""
        device = self.get_device()

        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return False

        alarm_id: str = call.data[SERVICE_ATTR_ALARM_ID]
        if not self.is_valid_alarm_id(alarm_id):
            _LOGGER.error(
                "Incorrect ID format! Please provide a valid alarm ID. "
                "See services tab for more info."
            )
            return False

        return await async_delete(self, device, [alarm_id])

    async def async_delete_all(self, _call: ServiceCall) -> bool:
        """Service call to delete all alarms on device."""
        device = self.get_device()

        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return False

        await self.client.update_alarms_and_timers(device, polling=False)
        alarm_ids = [alarm.alarm_id for alarm in device.get_sorted_alarms()]
        return await async_delete(self, device, alarm_ids)


class GoogleHomeTimersSensor(GoogleHomeBaseEntity):
    """Google Home Timers sensor."""

    _attr_icon = ICON_TIMERS
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_supported_features = GoogleHomeSensorFeature.TIMERS

    @property
    @override
    def label(self) -> str:
        """Label to use for name and unique id."""
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
            if timer and timer.local_time_iso
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

    @staticmethod
    def is_valid_timer_id(timer_id: str) -> bool:
        """Check if the timer id provided is valid."""
        return (
            timer_id.startswith("timer/") and len(timer_id) == ALARM_AND_TIMER_ID_LENGTH
        )

    async def async_delete_timer(self, call: ServiceCall) -> bool:
        """Service call to delete timer on device."""
        device = self.get_device()

        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return False

        timer_id: str = call.data[SERVICE_ATTR_TIMER_ID]
        if not self.is_valid_timer_id(timer_id):
            _LOGGER.error(
                "Incorrect ID format! Please provide a valid timer ID. "
                "See services tab for more info."
            )
            return False

        return await async_delete(self, device, [timer_id])

    async def async_delete_all(self, _call: ServiceCall) -> bool:
        """Service call to delete all timers on device."""
        device = self.get_device()

        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return False

        await self.client.update_alarms_and_timers(device, polling=False)
        timer_ids = [timer.timer_id for timer in device.get_sorted_timers()]
        return await async_delete(self, device, timer_ids)

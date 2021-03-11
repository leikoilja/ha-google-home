from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_NAME,
    DOMAIN,
    ICON_ALARMS,
    ICON_TIMERS,
    ICON_TOKEN,
    LABEL_ALARMS,
    LABEL_DEVICE,
    LABEL_NEXT_ALARM,
    LABEL_NEXT_TIMER,
    LABEL_TIMERS,
    MANUFACTURER,
    VERSION,
)


class GoogleHomeDeviceEntity(CoordinatorEntity):
    def __init__(self, coordinator, device_name):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_DEVICE}"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_DEVICE}"

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON_TOKEN

    @property
    def device_class(self):
        """Return de device class of the sensor."""
        return "google_home__custom_device_class"


class GoogleHomeAlarmEntity(CoordinatorEntity):
    def __init__(self, coordinator, device_name):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_ALARMS}"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_ALARMS}"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_ALARMS


class GoogleHomeNextAlarmEntity(CoordinatorEntity):
    def __init__(self, coordinator, device_name):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_NEXT_ALARM}"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_NEXT_ALARM}"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_ALARMS


class GoogleHomeTimersEntity(CoordinatorEntity):
    def __init__(self, coordinator, device_name):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_TIMERS}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_TIMERS}"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_TIMERS


class GoogleHomeNextTimerEntity(CoordinatorEntity):
    def __init__(self, coordinator, device_name):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_NEXT_TIMER}"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_NEXT_TIMER}"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_TIMERS

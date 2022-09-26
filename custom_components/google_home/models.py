"""Models for Google Home"""
from __future__ import annotations

from datetime import timedelta
from enum import Enum
import logging
import sys
from typing import List

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import DATETIME_STR_FORMAT, GOOGLE_HOME_ALARM_DEFAULT_VALUE
from .types import (
    AlarmJsonDict,
    BTJsonDict,
    GoogleHomeAlarmDict,
    GoogleHomeBTDeviceDict,
    GoogleHomeTimerDict,
    TimerJsonDict,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def convert_from_ms_to_s(timestamp: int) -> int:
    """Converts from milliseconds to seconds"""
    return round(timestamp / 1000)


class GoogleHomeDevice:
    """Local representation of Google Home device"""

    def __init__(
        self,
        device_id: str,
        name: str,
        auth_token: str | None,
        ip_address: str | None = None,
        hardware: str | None = None,
    ):
        self.device_id = device_id
        self.name = name
        self.auth_token = auth_token
        self.ip_address = ip_address
        self.hardware = hardware
        self.available = True
        self._do_not_disturb = False
        self._alarm_volume = GOOGLE_HOME_ALARM_DEFAULT_VALUE
        self._timers: list[GoogleHomeTimer] = []
        self._alarms: list[GoogleHomeAlarm] = []
        self._bt_devices: list[GoogleHomeBTDevice] = []

    def set_bt(self, devices: list[BTJsonDict]) -> None:
        """Stores BT devices as GoogleHomeBTDevice objects"""
        self._bt_devices = [
            GoogleHomeBTDevice(
                mac_address=device["mac_address"],
                device_class=device["device_class"],
                device_type=device["device_type"],
                rssi=device["rssi"],
                expected_profiles=device["expected_profiles"],
                name=device["name"],
            )
            for device in devices
        ]

    def set_alarms(self, alarms: list[AlarmJsonDict]) -> None:
        """Stores alarms as GoogleHomeAlarm objects"""
        self._alarms = [
            GoogleHomeAlarm(
                alarm_id=alarm["id"],
                fire_time=alarm["fire_time"],
                status=alarm["status"],
                label=alarm.get("label"),
                recurrence=alarm.get("recurrence"),
            )
            for alarm in alarms
        ]

    def set_timers(self, timers: list[TimerJsonDict]) -> None:
        """Stores timers as GoogleHomeTimer objects"""
        self._timers = [
            GoogleHomeTimer(
                timer_id=timer["id"],
                fire_time=timer.get("fire_time"),
                duration=timer["original_duration"],
                status=timer["status"],
                label=timer.get("label"),
            )
            for timer in timers
        ]

    def get_sorted_alarms(self) -> list[GoogleHomeAlarm]:
        """Returns alarms in a sorted order. Inactive & missed alarms are at the end."""
        return sorted(
            self._alarms,
            key=lambda k: k.fire_time
            if k.status
            not in (GoogleHomeAlarmStatus.INACTIVE, GoogleHomeAlarmStatus.MISSED)
            else k.fire_time + sys.maxsize,
        )

    def get_sorted_bt_devices(self) -> list[GoogleHomeBTDevice]:
        """Returns sorted BT devices"""
        return sorted(self._bt_devices, key=lambda k: k.rssi, reverse=True)

    def get_next_alarm(self) -> GoogleHomeAlarm | None:
        """Returns next alarm"""
        alarms = self.get_sorted_alarms()
        return alarms[0] if alarms else None

    def get_closest_device(self) -> GoogleHomeBTDevice | None:
        """Returns the closest BT device"""
        devices = self.get_sorted_bt_devices()
        return devices[0] if devices else None

    def get_sorted_timers(self) -> list[GoogleHomeTimer]:
        """Returns timers in a sorted order. If timer is paused, put it in the end."""
        return sorted(
            self._timers,
            key=lambda k: k.fire_time if k.fire_time is not None else sys.maxsize,
        )

    def get_next_timer(self) -> GoogleHomeTimer | None:
        """Returns next alarm"""
        timers = self.get_sorted_timers()
        return timers[0] if timers else None

    def set_do_not_disturb(self, status: bool) -> None:
        """Set Do Not Disturb status."""
        self._do_not_disturb = status

    def get_do_not_disturb(self) -> bool:
        """Return Do Not Disturb status."""
        return self._do_not_disturb

    def set_alarm_volume(self, volume: int) -> None:
        """Set Alarm Volume status."""
        self._alarm_volume = volume

    def get_alarm_volume(self) -> int:
        """Return Alarm Volume status."""
        return self._alarm_volume


class GoogleHomeTimer:
    """Local representation of Google Home timer"""

    def __init__(
        self,
        timer_id: str,
        fire_time: int | None,
        duration: int,
        status: int,
        label: str | None,
    ) -> None:
        self.timer_id = timer_id
        self.duration = str(timedelta(seconds=convert_from_ms_to_s(duration)))
        self.status = GoogleHomeTimerStatus(status)
        self.label = label

        if fire_time is None:
            self.fire_time = None
            self.local_time = None
            self.local_time_iso = None
        else:
            self.fire_time = convert_from_ms_to_s(fire_time)
            dt_utc = utc_from_timestamp(self.fire_time)
            dt_local = as_local(dt_utc)
            self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
            self.local_time_iso = dt_local.isoformat()

    def as_dict(self) -> GoogleHomeTimerDict:
        """Return typed dict representation."""
        return {
            "timer_id": self.timer_id,
            "fire_time": self.fire_time,
            "local_time": self.local_time,
            "local_time_iso": self.local_time_iso,
            "duration": self.duration,
            "status": self.status.name.lower(),
            "label": self.label,
        }


class GoogleHomeBTDevice:
    """Local representation of detected BT devices"""

    def __init__(
        self,
        mac_address: str,
        device_class: int,
        device_type: int,
        rssi: int,
        expected_profiles: int,
        name: str | None,
    ) -> None:

        self.mac_address = mac_address
        self.device_class = device_class
        self.device_type = device_type
        self.rssi = rssi
        self.expected_profiles = expected_profiles
        self.name = name

    def as_dict(self) -> GoogleHomeBTDeviceDict:
        """Return typed dict representation."""
        return {
            "mac_address": self.mac_address,
            "device_class": self._decode_device_class(),
            "device_type": self._decode_device_type(self.device_type),
            "rssi": self.rssi,
            "expected_profiles": self.expected_profiles,
            "name": self.name,
        }

    @staticmethod
    def _decode_device_type(device_type: int) -> str:
        types = ["BREDR", "BLE"]

        out_types = []

        for num, name in enumerate(types):
            if device_type & (1 << num):
                out_types.append(name)

        return "|".join(out_types)

    @staticmethod
    def _device_major_class(major_number: int) -> str:
        # Major Device Classes
        classes = [
            "Miscellaneous",
            "Computer",
            "Phone",
            "LAN/Network Access Point",
            "Audio/Video",
            "Peripheral",
            "Imaging",
            "Wearable",
            "Toy",
            "Health",
        ]
        if major_number < len(classes):
            major = classes[major_number]
        elif major_number == 31:
            major = "Uncategorized"
        else:
            major = "Reserved"
        return major

    @staticmethod
    def _device_class_imaging(minor_number: int) -> str:
        minors = []
        minor = ""
        if minor_number & (1 << 2):
            minors.append("Display")
        if minor_number & (1 << 3):
            minors.append("Camera")
        if minor_number & (1 << 4):
            minors.append("Scanner")
        if minor_number & (1 << 5):
            minors.append("Printer")
        if len(minors) > 0:
            minor = ", ".join(minors)
        return minor

    @staticmethod
    def _device_class_peripheral(minor_number: int) -> str:
        feel_number = minor_number >> 4
        classes = [
            "Not Keyboard / Not Pointing Device",
            "Keyboard",
            "Pointing device",
            "Combo keyboard/pointing device",
        ]
        feel = classes[feel_number]

        classes = [
            "Uncategorized",
            "Joystick",
            "Gamepad",
            "Remote control",
            "Sensing device",
            "Digitizer tablet",
            "Card Reader",
            "Digital Pen",
            "Handheld scanner for bar-codes, RFID, etc.",
            "Handheld gestural input device",
        ]
        if minor_number < len(classes):
            minor_low = classes[minor_number]
        else:
            minor_low = "reserved"
        return f"{feel}, {minor_low}"

    @staticmethod
    def _device_major_service_class(device_class: int) -> List[str]:
        services = []
        if device_class & (1 << 23):
            services.append("Information")
        if device_class & (1 << 22):
            services.append("Telephony")
        if device_class & (1 << 21):
            services.append("Audio")
        if device_class & (1 << 20):
            services.append("Object Transfer")
        if device_class & (1 << 19):
            services.append("Capturing")
        if device_class & (1 << 18):
            services.append("Rendering")
        if device_class & (1 << 17):
            services.append("Networking")
        if device_class & (1 << 16):
            services.append("Positioning")
        if device_class & (1 << 15):
            services.append("(reserved)")
        if device_class & (1 << 14):
            services.append("(reserved)")
        if device_class & (1 << 13):
            services.append("Limited Discoverable Mode")
        return services

    def _decode_device_class(self) -> str:
        major_number = (self.device_class >> 8) & 0x1F
        major = self._device_major_class(major_number)

        # Minor - varies depending on major
        minor_number = (self.device_class >> 2) & 0x3F
        minor = None

        # computer
        if major_number == 1:
            minor = self._device_class_computer(minor_number)

        # phone
        elif major_number == 2:
            minor = self._device_class_phone(minor_number)

        # network access point
        elif major_number == 3:
            minor = self._device_class_ap(minor_number)

        # audio/video
        elif major_number == 4:
            minor = self._device_class_av(minor_number)

        # peripheral, this one's gross
        elif major_number == 5:
            minor = self._device_class_peripheral(minor_number)

        # imaging
        elif major_number == 6:
            minor = self._device_class_imaging(minor_number)

        # wearable
        elif major_number == 7:
            minor = self._device_class_wearable(minor_number)

        # toy
        elif major_number == 8:
            self._device_class_toy(minor_number)

        # health
        elif major_number == 9:
            minor = self._device_class_health(minor_number)

        # Major Service Class (can by multiple)
        services = self._device_major_service_class(self.device_class)

        output = str(major)
        if minor is not None:
            output += f" ({minor}s)"

        if services:
            output += ": "
            output += ", ".join(services)

        return output

    @staticmethod
    def _device_class_health(minor_number: int) -> str:
        classes = [
            "Undefined",
            "Blood Pressure Monitor",
            "Thermometer",
            "Weighing Scale",
            "Glucose Meter",
            "Pulse Oximeter",
            "Heart/Pulse Rate Monitor",
            "Health Data Display",
            "Step Counter",
            "Body Composition Analyzer",
            "Peak Flow Monitor",
            "Medication Monitor",
            "Knee Prosthesis",
            "Ankle Prosthesis",
            "Generic Health Manager",
            "Personal Mobility Device",
        ]
        if minor_number < len(classes):
            minor = classes[minor_number]
        else:
            minor = "reserved"
        return minor

    @staticmethod
    def _device_class_toy(minor_number: int) -> str:
        classes = ["Robot", "Vehicle", "Doll / Action figure", "Controller", "Game"]
        if minor_number < len(classes):
            minor = classes[minor_number]
        else:
            minor = "reserved"
        return minor

    @staticmethod
    def _device_class_wearable(minor_number: int) -> str:
        classes = ["Wristwatch", "Pager", "Jacket", "Helmet", "Glasses"]
        if minor_number < len(classes):
            minor = classes[minor_number]
        else:
            minor = "reserved"
        return minor

    @staticmethod
    def _device_class_av(minor_number: int) -> str:
        classes = [
            "Uncategorized",
            "Wearable Headset Device",
            "Hands-free Device",
            "(Reserved)",
            "Microphone",
            "Loudspeaker",
            "Headphones",
            "Portable Audio",
            "Car audio",
            "Set-top box",
            "HiFi Audio Device",
            "VCR",
            "Video Camera",
            "Camcorder",
            "Video Monitor",
            "Video Display and Loudspeaker",
            "Video Conferencing",
            "(Reserved)",
            "Gaming/Toy",
        ]
        if minor_number < len(classes):
            minor = classes[minor_number]
        else:
            minor = "reserved"
        return minor

    @staticmethod
    def _device_class_ap(minor_number: int) -> str:
        classes = [
            "Fully available",
            "1% to 17% utilized",
            "17% to 33% utilized",
            "33% to 50% utilized",
            "50% to 67% utilized",
            "67% to 83% utilized",
            "83% to 99% utilized",
            "No service available",
        ]
        if minor_number < len(classes):
            minor = classes[minor_number]
        else:
            minor = "reserved"
        return minor

    @staticmethod
    def _device_class_phone(minor_number: int) -> str:
        classes = [
            "Uncategorized",
            "Cellular",
            "Cordless",
            "Smartphone",
            "Wired modem or voice gateway",
            "Common ISDN access",
        ]
        if minor_number < len(classes):
            minor = classes[minor_number]
        else:
            minor = "reserved"
        return minor

    @staticmethod
    def _device_class_computer(minor_number: int) -> str:
        classes = [
            "Uncategorized",
            "Desktop workstation",
            "Server-class computer",
            "Laptop",
            "Handheld PC/PDA (clamshell)",
            "Palm-size PC/PDA",
            "Wearable computer (watch size)",
            "Tablet",
        ]
        if minor_number < len(classes):
            minor = classes[minor_number]
        else:
            minor = "reserved"
        return minor


class GoogleHomeAlarm:
    """Local representation of Google Home alarm"""

    def __init__(
        self,
        alarm_id: str,
        fire_time: int,
        status: int,
        label: str | None,
        recurrence: str | None,
    ) -> None:
        self.alarm_id = alarm_id
        self.recurrence = recurrence
        self.fire_time = convert_from_ms_to_s(fire_time)
        self.status = GoogleHomeAlarmStatus(status)
        self.label = label

        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
        self.local_time_iso = dt_local.isoformat()

    def as_dict(self) -> GoogleHomeAlarmDict:
        """Return typed dict representation."""
        return {
            "alarm_id": self.alarm_id,
            "fire_time": self.fire_time,
            "local_time": self.local_time,
            "local_time_iso": self.local_time_iso,
            "status": self.status.name.lower(),
            "label": self.label,
            "recurrence": self.recurrence,
        }


class GoogleHomeAlarmStatus(Enum):
    """Definition of Google Home alarm status"""

    NONE = 0
    SET = 1
    RINGING = 2
    SNOOZED = 3
    INACTIVE = 4
    MISSED = 5


class GoogleHomeTimerStatus(Enum):
    """Definition of Google Home timer status"""

    NONE = 0
    SET = 1
    PAUSED = 2
    RINGING = 3

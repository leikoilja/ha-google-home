"""Models for Google Home"""
from __future__ import annotations

from datetime import timedelta
from enum import Enum
import sys
from typing import Mapping

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import DATETIME_STR_FORMAT, GOOGLE_HOME_ALARM_DEFAULT_VALUE
from .types import (
    AlarmJsonDict,
    EurekaCompatibilityDict,
    EurekaDeviceInfoDict,
    GoogleHomeAlarmDict,
    GoogleHomeEurekaDict,
    GoogleHomeTimerDict,
    JsonCChildrenDict,
    JsonChildrenDict,
    JsonChildrenElem,
    TimerJsonDict,
)


def convert_from_ms_to_s(timestamp: int) -> int:
    """Converts from milliseconds to seconds"""
    return round(timestamp / 1000)


class GoogleHomeDevice:
    """Local representation of Google Home device"""

    def __init__(
        self,
        name: str,
        auth_token: str | None,
        ip_address: str | None = None,
        hardware: str | None = None,
        eureka: GoogleHomeEureka | None = None,
    ):
        self.name = name
        self.auth_token = auth_token
        self.ip_address = ip_address
        self.hardware = hardware
        self.available = True
        self._do_not_disturb = False
        self._alarm_volume = GOOGLE_HOME_ALARM_DEFAULT_VALUE
        self._timers: list[GoogleHomeTimer] = []
        self._alarms: list[GoogleHomeAlarm] = []
        self._eureka: GoogleHomeEureka | None = eureka

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
        """Returns alarms in a sorted order. Inactive alarms are in the end."""
        return sorted(
            self._alarms,
            key=lambda k: k.fire_time
            if k.status != GoogleHomeAlarmStatus.INACTIVE
            else k.fire_time + sys.maxsize,
        )

    def get_next_alarm(self) -> GoogleHomeAlarm | None:
        """Returns next alarm"""
        alarms = self.get_sorted_alarms()
        return alarms[0] if alarms else None

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

    def set_alarm_volume(self, volume: float) -> None:
        """Set Alarm Volume status."""
        self._alarm_volume = volume

    def get_alarm_volume(self) -> float:
        """Return Alarm Volume status."""
        return self._alarm_volume

    def set_eureka(self, eureka: GoogleHomeEureka) -> None:
        """Stores the Eureka data"""
        self._eureka = eureka

    def get_eureka(self) -> GoogleHomeEureka | None:
        """Returns the Eureka data"""
        return self._eureka

    def is_compatible(self, function_name: str) -> bool:
        """Checks if a function is compatible. If Eureka is not loaded, returns false"""
        if (
            not self._eureka
            or not self._eureka.device_info
            or not self._eureka.device_info.compatibility
        ):
            return False
        return function_name in self._eureka.device_info.compatibility.as_dict()


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


class GoogleHomeEureka:
    """Local representation of Google Home Eureka"""

    def __init__(self, device_info: EurekaDeviceInfo) -> None:
        self.device_info = device_info

    def as_dict(self) -> GoogleHomeEurekaDict:
        """Return typed dict representation."""
        return {
            "device_info": self.device_info.as_dict(),
        }


class EurekaDeviceInfo:
    """Local representation of Google Home Eureka device_info data"""

    def __init__(self, data: JsonChildrenDict) -> None:
        # self.4k_blocked: str = data[""]
        capabilities: JsonChildrenElem | None = (
            data["capabilities"] if isinstance(data["capabilities"], Mapping) else None
        )
        self.compatibility: EurekaCompatibility | None = (
            EurekaCompatibility(capabilities)
            if isinstance(capabilities, Mapping)
            else None
        )
        self.cloud_device_id: str | None = (
            data["cloud_device_id"]
            if isinstance(data["cloud_device_id"], str)
            else None
        )
        self.factory_country_code: str | None = (
            data["factory_country_code"]
            if isinstance(data["factory_country_code"], str)
            else None
        )
        self.hotspot_bssid: str | None = (
            data["hotspot_bssid"] if isinstance(data["hotspot_bssid"], str) else None
        )
        self.local_authorization_token_hash: str | None = (
            data["local_authorization_token_hash"]
            if isinstance(data["local_authorization_token_hash"], str)
            else None
        )
        self.mac_address: str | None = (
            data["mac_address"] if isinstance(data["mac_address"], str) else None
        )
        self.manufacturer: str | None = (
            data["manufacturer"] if isinstance(data["manufacturer"], str) else None
        )
        self.model_name: str | None = (
            data["model_name"] if isinstance(data["model_name"], str) else None
        )
        self.product_name: str | None = (
            data["product_name"] if isinstance(data["product_name"], str) else None
        )
        self.public_key: str | None = (
            data["public_key"] if isinstance(data["public_key"], str) else None
        )
        self.ssdp_udn: str | None = (
            data["ssdp_udn"] if isinstance(data["ssdp_udn"], str) else None
        )
        self.uptime: float | None = (
            data["uptime"] if isinstance(data["uptime"], float) else None
        )
        self.weave_device_id: str | None = (
            data["weave_device_id"]
            if isinstance(data["weave_device_id"], str)
            else None
        )

    def as_dict(self) -> EurekaDeviceInfoDict:
        """Return typed dict representation."""
        return {
            # Skipped since Python's variable names can't start with a number, so
            #   the TypedDict can't exist
            # "4k_blocked": self.4k_blocked,
            "capabilities": self.compatibility.as_dict()
            if self.compatibility
            else None,
            "cloud_device_id": self.cloud_device_id,
            "factory_country_code": self.factory_country_code,
            "hotspot_bssid": self.hotspot_bssid,
            "local_authorization_token_hash": self.local_authorization_token_hash,
            "mac_address": self.mac_address,
            "manufacturer": self.manufacturer,
            "model_name": self.model_name,
            "product_name": self.product_name,
            "public_key": self.public_key,
            "ssdp_udn": self.ssdp_udn,
            "uptime": self.uptime,
            "weave_device_id": self.weave_device_id,
        }


class EurekaCompatibility:
    """Local representation of Google Home Eureka compatibility data"""

    # Note: skipped the "_supported" suffix for simplicity.
    def __init__(self, data: JsonCChildrenDict) -> None:
        self.aogh: bool | None = (
            data["aogh_supported"] if isinstance(data["aogh_supported"], bool) else None
        )
        self.assistant: bool | None = (
            data["assistant_supported"]
            if isinstance(data["assistant_supported"], bool)
            else None
        )
        self.audio_hdr: bool | None = (
            data["audio_hdr_supported"]
            if isinstance(data["audio_hdr_supported"], bool)
            else None
        )
        self.audio_surround_mode: bool | None = (
            data["audio_surround_mode_supported"]
            if isinstance(data["audio_surround_mode_supported"], bool)
            else None
        )
        self.ble_supported: bool | None = (
            data["ble_supported"] if isinstance(data["ble_supported"], bool) else None
        )
        self.bluetooth_audio_sink: bool | None = (
            data["bluetooth_audio_sink_supported"]
            if isinstance(data["bluetooth_audio_sink_supported"], bool)
            else None
        )
        self.bluetooth_audio_source: bool | None = (
            data["bluetooth_audio_source_supported"]
            if isinstance(data["bluetooth_audio_source_supported"], bool)
            else None
        )
        self.bluetooth: bool | None = (
            data["bluetooth_supported"]
            if isinstance(data["bluetooth_supported"], bool)
            else None
        )
        self.cloudcast: bool | None = (
            data["cloudcast_supported"]
            if isinstance(data["cloudcast_supported"], bool)
            else None
        )
        self.content_filters: bool | None = (
            data["content_filters_supported"]
            if isinstance(data["content_filters_supported"], bool)
            else None
        )
        self.disable_google_dns: bool | None = (
            data["disable_google_dns_supported"]
            if isinstance(data["disable_google_dns_supported"], bool)
            else None
        )
        self.display: bool | None = (
            data["display_supported"]
            if isinstance(data["display_supported"], bool)
            else None
        )
        self.fdr: bool | None = (
            data["fdr_supported"] if isinstance(data["fdr_supported"], bool) else None
        )
        self.hdmi_prefer_50hz: bool | None = (
            data["hdmi_prefer_50hz_supported"]
            if isinstance(data["hdmi_prefer_50hz_supported"], bool)
            else None
        )
        self.hdmi_prefer_high_fps: bool | None = (
            data["hdmi_prefer_high_fps_supported"]
            if isinstance(data["hdmi_prefer_high_fps_supported"], bool)
            else None
        )
        self.hotspot: bool | None = (
            data["hotspot_supported"]
            if isinstance(data["hotspot_supported"], bool)
            else None
        )
        self.https_setup: bool | None = (
            data["https_setup_supported"]
            if isinstance(data["https_setup_supported"], bool)
            else None
        )
        self.input_management: bool | None = (
            data["input_management_supported"]
            if isinstance(data["input_management_supported"], bool)
            else None
        )
        self.keep_hotspot_until_connected: bool | None = (
            data["keep_hotspot_until_connected_supported"]
            if isinstance(data["keep_hotspot_until_connected_supported"], bool)
            else None
        )
        self.multi_user: bool | None = (
            data["multi_user_supported"]
            if isinstance(data["multi_user_supported"], bool)
            else None
        )
        self.multichannel_group: bool | None = (
            data["multichannel_group_supported"]
            if isinstance(data["multichannel_group_supported"], bool)
            else None
        )
        self.multizone: bool | None = (
            data["multizone_supported"]
            if isinstance(data["multizone_supported"], bool)
            else None
        )
        self.night_mode: bool | None = (
            data["night_mode_supported"]
            if isinstance(data["night_mode_supported"], bool)
            else None
        )
        self.night_mode_v2: bool | None = (
            data["night_mode_supported_v2"]
            if isinstance(data["night_mode_supported_v2"], bool)
            else None
        )
        self.opencast: bool | None = (
            data["opencast_supported"]
            if isinstance(data["opencast_supported"], bool)
            else None
        )
        self.preview_channel: bool | None = (
            data["preview_channel_supported"]
            if isinstance(data["preview_channel_supported"], bool)
            else None
        )
        self.reboot: bool | None = (
            data["reboot_supported"]
            if isinstance(data["reboot_supported"], bool)
            else None
        )
        self.remote_ducking: bool | None = (
            data["remote_ducking_supported"]
            if isinstance(data["remote_ducking_supported"], bool)
            else None
        )
        self.renaming: bool | None = (
            data["renaming_supported"]
            if isinstance(data["renaming_supported"], bool)
            else None
        )
        self.setup: bool | None = (
            data["setup_supported"]
            if isinstance(data["setup_supported"], bool)
            else None
        )
        self.sleep_mode: bool | None = (
            data["sleep_mode_supported"]
            if isinstance(data["sleep_mode_supported"], bool)
            else None
        )
        self.stats: bool | None = (
            data["stats_supported"]
            if isinstance(data["stats_supported"], bool)
            else None
        )
        self.system_sound_effects: bool | None = (
            data["system_sound_effects_supported"]
            if isinstance(data["system_sound_effects_supported"], bool)
            else None
        )
        self.ui_flipping: bool | None = (
            data["ui_flipping_supported"]
            if isinstance(data["ui_flipping_supported"], bool)
            else None
        )
        self.user_eq: bool | None = (
            data["user_eq_supported"]
            if isinstance(data["user_eq_supported"], bool)
            else None
        )
        self.wifi_auto_save: bool | None = (
            data["wifi_auto_save_supported"]
            if isinstance(data["wifi_auto_save_supported"], bool)
            else None
        )
        self.wifi: bool | None = (
            data["wifi_supported"] if isinstance(data["wifi_supported"], bool) else None
        )

    def as_dict(self) -> EurekaCompatibilityDict:
        """Return typed dict representation."""
        return {
            "aogh_supported": self.aogh,
            "assistant_supported": self.assistant,
            "audio_hdr_supported": self.audio_hdr,
            "audio_surround_mode_supported": self.audio_surround_mode,
            "ble_supported": self.ble_supported,
            "bluetooth_audio_sink_supported": self.bluetooth_audio_sink,
            "bluetooth_audio_source_supported": self.bluetooth_audio_source,
            "bluetooth_supported": self.bluetooth,
            "cloudcast_supported": self.cloudcast,
            "content_filters_supported": self.content_filters,
            "disable_google_dns_supported": self.disable_google_dns,
            "display_supported": self.display,
            "fdr_supported": self.fdr,
            "hdmi_prefer_50hz_supported": self.hdmi_prefer_50hz,
            "hdmi_prefer_high_fps_supported": self.hdmi_prefer_high_fps,
            "hotspot_supported": self.hotspot,
            "https_setup_supported": self.https_setup,
            "input_management_supported": self.input_management,
            "keep_hotspot_until_connected_supported": self.keep_hotspot_until_connected,
            "multi_user_supported": self.multi_user,
            "multichannel_group_supported": self.multichannel_group,
            "multizone_supported": self.multizone,
            "night_mode_supported": self.night_mode,
            "night_mode_supported_v2": self.night_mode_v2,
            "opencast_supported": self.opencast,
            "preview_channel_supported": self.preview_channel,
            "reboot_supported": self.reboot,
            "remote_ducking_supported": self.remote_ducking,
            "renaming_supported": self.renaming,
            "setup_supported": self.setup,
            "sleep_mode_supported": self.sleep_mode,
            "stats_supported": self.stats,
            "system_sound_effects_supported": self.system_sound_effects,
            "ui_flipping_supported": self.ui_flipping,
            "user_eq_supported": self.user_eq,
            "wifi_auto_save_supported": self.wifi_auto_save,
            "wifi_supported": self.wifi,
        }


class GoogleHomeAlarmStatus(Enum):
    """Definition of Google Home alarm status"""

    NONE = 0
    SET = 1
    RINGING = 2
    SNOOZED = 3
    INACTIVE = 4


class GoogleHomeTimerStatus(Enum):
    """Definition of Google Home timer status"""

    NONE = 0
    SET = 1
    PAUSED = 2
    RINGING = 3

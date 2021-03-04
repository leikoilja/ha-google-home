"""utils.py for google home integration"""
from datetime import timedelta

from homeassistant.util.dt import as_local
from homeassistant.util.dt import utc_from_timestamp

from .const import DATETIME_STR_FORMAT
from .const import DATETIME_UTC
from .const import FIRE_TIME
from .const import LOCAL_TIME
from .const import ORIGINAL_DURATION
from .const import TIME_LEFT


def convert_from_ms_to_s(timestamp):
    return round(timestamp / 1000)


def format_timer_information(timer_dict):
    timer = {}

    timer[FIRE_TIME] = convert_from_ms_to_s(timer_dict[FIRE_TIME])
    duration = convert_from_ms_to_s(timer_dict[ORIGINAL_DURATION])

    dt_utc = utc_from_timestamp(timer[FIRE_TIME])
    timer[DATETIME_UTC] = dt_utc.strftime(DATETIME_STR_FORMAT)
    timer[LOCAL_TIME] = as_local(dt_utc).strftime(DATETIME_STR_FORMAT)
    timer[TIME_LEFT] = str(timedelta(seconds=duration))
    return timer


def format_alarm_information(alarm_dict):
    alarm = {}

    alarm[FIRE_TIME] = convert_from_ms_to_s(alarm_dict[FIRE_TIME])

    dt_utc = utc_from_timestamp(alarm[FIRE_TIME])
    alarm[DATETIME_UTC] = dt_utc.strftime(DATETIME_STR_FORMAT)
    alarm[LOCAL_TIME] = as_local(dt_utc).strftime(DATETIME_STR_FORMAT)
    return alarm

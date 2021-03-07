"""utils.py for google home integration"""
from datetime import timedelta

from homeassistant.util.dt import as_local
from homeassistant.util.dt import utc_from_timestamp

from .const import DATETIME_STR_FORMAT
from .const import DURATION
from .const import FIRE_TIME
from .const import ID
from .const import LABEL
from .const import LOCAL_TIME
from .const import LOCAL_TIME_ISO
from .const import ORIGINAL_DURATION
from .const import RECURRENCE


def convert_from_ms_to_s(timestamp):
    return round(timestamp / 1000)


def format_timer_information(timer_dict):
    timer = {}

    timer[FIRE_TIME] = convert_from_ms_to_s(timer_dict[FIRE_TIME])
    duration = convert_from_ms_to_s(timer_dict[ORIGINAL_DURATION])

    dt_utc = utc_from_timestamp(timer[FIRE_TIME])
    dt_local = as_local(dt_utc)
    timer[ID] = timer_dict[ID]
    if LABEL in timer_dict:
        timer[LABEL] = timer_dict[LABEL]
    timer[LOCAL_TIME] = dt_local.strftime(DATETIME_STR_FORMAT)
    timer[LOCAL_TIME_ISO] = dt_local.isoformat()
    timer[DURATION] = str(timedelta(seconds=duration))
    return timer


def format_alarm_information(alarm_dict):
    alarm = {}

    alarm[FIRE_TIME] = convert_from_ms_to_s(alarm_dict[FIRE_TIME])

    dt_utc = utc_from_timestamp(alarm[FIRE_TIME])
    dt_local = as_local(dt_utc)
    alarm[ID] = alarm_dict[ID]
    if LABEL in alarm_dict:
        alarm[LABEL] = alarm_dict[LABEL]
    alarm[LOCAL_TIME] = dt_local.strftime(DATETIME_STR_FORMAT)
    alarm[LOCAL_TIME_ISO] = dt_local.isoformat()
    if alarm_dict.get(RECURRENCE):
        alarm[RECURRENCE] = alarm_dict[RECURRENCE]
    return alarm

"""utils.py for google home integration"""
from datetime import timedelta

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import (
    DATETIME_STR_FORMAT,
    DURATION,
    FIRE_TIME,
    ID,
    LABEL,
    LOCAL_TIME,
    LOCAL_TIME_ISO,
    ORIGINAL_DURATION,
    RECURRENCE,
)


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


def sort_list_by_firetime(unsorted_list):
    return sorted(unsorted_list, key=lambda k: k[FIRE_TIME])

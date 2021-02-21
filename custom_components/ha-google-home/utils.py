"""utils.py for google home integration"""
from datetime import datetime

from .const import DATE_TIME
from .const import DURATION
from .const import FIRE_TIME
from .const import FIRE_TIME_IN_S
from .const import LOCAL_TIME
from .const import ORIGINAL_DURATION
from .const import SHOW_DATE_AND_TIME
from .const import SHOW_DATE_TIMEZONE
from .const import SHOW_TIME_ONLY


def convert_from_ms_to_s(timestamp):
    return round(timestamp / 1000)


def format_timer_information(timer):
    timer[FIRE_TIME_IN_S] = convert_from_ms_to_s(timer[FIRE_TIME])
    timer[DATE_TIME] = datetime.fromtimestamp(timer[FIRE_TIME_IN_S]).strftime(
        SHOW_TIME_ONLY
    )

    duration = convert_from_ms_to_s(timer[ORIGINAL_DURATION])
    timer[DURATION] = datetime.utcfromtimestamp(duration).strftime(SHOW_TIME_ONLY)
    return timer


def format_alarm_information(alarm):
    alarm[FIRE_TIME_IN_S] = convert_from_ms_to_s(alarm[FIRE_TIME])
    alarm[DATE_TIME] = datetime.utcfromtimestamp(alarm[FIRE_TIME_IN_S]).strftime(
        SHOW_DATE_TIMEZONE
    )
    alarm[LOCAL_TIME] = datetime.fromtimestamp(alarm[FIRE_TIME_IN_S]).strftime(
        SHOW_DATE_AND_TIME
    )
    return alarm

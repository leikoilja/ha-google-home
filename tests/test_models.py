"""Tests for Google Home models."""

from custom_components.google_home.models import GoogleHomeDevice


def test_timers_show_time_left_on_paused_timer() -> None:
    """Show the time left on a paused timer, which has no fire time to work it out from.

    A running timer has a fire time instead: the time left it had at the last update
    would be out of date, so it shows none even if the device sends it.
    """
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    device.set_timers(
        [
            # A 30-minute timer paused with 1785.268 s left, with the values a Nest Hub
            # sent while showing 29:46
            {
                "id": "timer/paused",
                "original_duration": 1800000,
                "remaining_duration": 1785268,
                "status": 2,
            },
            # A whole second isn't rounded up
            {
                "id": "timer/paused-whole-second",
                "original_duration": 60000,
                "remaining_duration": 60000,
                "status": 2,
            },
            {
                "id": "timer/running",
                "fire_time": 1700000000000,
                "original_duration": 60000,
                "remaining_duration": 60000,
                "status": 1,
            },
            # A device that doesn't send the time left
            {"id": "timer/no-time-left", "original_duration": 60000, "status": 2},
        ]
    )

    # The timers sensor shows these in its timers attribute
    assert {
        timer["timer_id"]: (timer["duration"], timer["remaining"])
        for timer in (timer.as_dict() for timer in device.get_sorted_timers())
    } == {
        "timer/paused": ("0:30:00", "0:29:46"),  # 1785.268 s rounds up to 29 min 46 s
        "timer/paused-whole-second": ("0:01:00", "0:01:00"),
        "timer/running": ("0:01:00", None),
        "timer/no-time-left": ("0:01:00", None),
    }

# Entities

Each Google Home device gets the entities below. The examples use a device named _Living Room_.

| Entity                | Example                             | What it does                                              |
| --------------------- | ----------------------------------- | --------------------------------------------------------- |
| Alarms sensor         | `sensor.living_room_alarms`         | Time of the next alarm, with all alarms in its attributes |
| Timers sensor         | `sensor.living_room_timers`         | Time of the next timer, with all timers in its attributes |
| Device sensor         | `sensor.living_room_device`         | The device's IP address and connection details            |
| Do Not Disturb switch | `switch.living_room_do_not_disturb` | Turns Do Not Disturb on or off                            |
| Alarm volume          | `number.living_room_alarm_volume`   | Sets the alarm volume, from 0 to 100%                     |
| Reboot button         | `button.living_room_reboot`         | Reboots the device                                        |

The alarms sensor, timers sensor, switch and alarm volume are added once Home Assistant can reach the device. If a device has only a device sensor and a reboot button, see [No alarms or timers sensors](troubleshooting.md#no-alarms-or-timers-sensors).

## Alarms sensor

The state is the time of the next alarm, such as `2026-03-07T15:26:17+01:00`. It is `unavailable` when no alarm is set, or when all alarms are inactive or missed.

To start automations at the time of the next alarm or timer, see [Automation examples](automations.md).

The state uses the same format as the [next alarm sensor](https://companion.home-assistant.io/docs/core/sensors/#next-alarm-sensor) of the Home Assistant mobile app, such as `sensor.phone_next_alarm`. You can use both in the same automations.

| Attribute           | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| `next_alarm_status` | [Status](#alarm-and-timer-status) of the next alarm, or `none` if there are no alarms |
| `alarm_volume`      | Alarm volume in percent, the same value as the alarm volume entity                    |
| `alarms`            | List of all alarms, with the next one first. Inactive and missed alarms come last.    |

Each alarm in `alarms` has these keys:

| Key              | Example                                      | Description                                                                                                                                         |
| ---------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `alarm_id`       | `alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51` | ID of the alarm. Use it to [delete the alarm](actions.md#delete-alarm).                                                                             |
| `fire_time`      | `1772893577`                                 | When the alarm goes off, as a Unix timestamp in seconds                                                                                             |
| `local_time`     | `2026-03-07 15:26:17`                        | When the alarm goes off, in Home Assistant's time zone                                                                                              |
| `local_time_iso` | `2026-03-07T15:26:17+01:00`                  | The same time in ISO 8601 format, convenient for automations                                                                                        |
| `status`         | `set`                                        | [Status](#alarm-and-timer-status) of the alarm                                                                                                      |
| `label`          | `Wake up`                                    | Name of the alarm, if you gave it one                                                                                                               |
| `recurrence`     | `[1, 2, 3, 4, 5]`                            | Days of the week the alarm repeats on. Following Google's convention, the week starts on Sunday: `0` is Sunday, `1` is Monday, and `6` is Saturday. |

## Timers sensor

The state is the time the next timer goes off, such as `2026-03-07T15:26:17+01:00`. It is `unavailable` when no timer is set, or when all timers are paused.

| Attribute           | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| `next_timer_status` | [Status](#alarm-and-timer-status) of the next timer, or `none` if there are no timers |
| `timers`            | List of all timers, with the one that goes off next first. Paused timers come last.   |

Each timer in `timers` has these keys:

| Key              | Example                                      | Description                                                                               |
| ---------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `timer_id`       | `timer/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51` | ID of the timer. Use it to [delete the timer](actions.md#delete-timer).                   |
| `fire_time`      | `1772893577`                                 | When the timer goes off, as a Unix timestamp in seconds. Empty while the timer is paused. |
| `local_time`     | `2026-03-07 15:26:17`                        | When the timer goes off, in Home Assistant's time zone. Empty while paused.               |
| `local_time_iso` | `2026-03-07T15:26:17+01:00`                  | The same time in ISO 8601 format. Empty while paused.                                     |
| `duration`       | `0:10:00`                                    | Length the timer was set for, as hours:minutes:seconds                                    |
| `status`         | `set`                                        | [Status](#alarm-and-timer-status) of the timer                                            |
| `label`          | `Pasta`                                      | Name of the timer, if you gave it one                                                     |

## Alarm and timer status

| Status     | Meaning                                      |
| ---------- | -------------------------------------------- |
| `none`     | There is no alarm or timer                   |
| `set`      | The alarm or timer is set                    |
| `ringing`  | The alarm or timer is ringing right now      |
| `snoozed`  | The alarm rang and was snoozed. Alarms only. |
| `inactive` | The alarm is inactive. Alarms only.          |
| `missed`   | The alarm was missed. Alarms only.           |
| `paused`   | The timer is paused. Timers only.            |

Timers have no `snoozed` status. If you snooze a ringing timer, it restarts and its status goes back to `set`.

## Device sensor

The state is the device's IP address on your network. If no IP address is available for the device, the sensor is unavailable and the device details listed below are hidden. The sensor appears under **Diagnostic** on the device page.

| Attribute     | Description                                                     |
| ------------- | --------------------------------------------------------------- |
| `device_id`   | Google's ID for the device                                      |
| `device_name` | Name of the device in the Google Home app                       |
| `ip_address`  | IP address of the device                                        |
| `available`   | `true` if Home Assistant reached the device at its last request |
| `auth_token`  | Token Home Assistant uses to talk to the device                 |

!!! warning

    Anyone who can see the device sensor in Home Assistant can read `auth_token` and use it to control the device from your network until the token expires, usually within a day. Only give Home Assistant access to people you trust with your devices.

## Do Not Disturb switch

Turns Do Not Disturb on or off on the device. It appears under **Configuration** on the device page.

## Alarm volume

Sets how loud alarms ring on the device, from 0 to 100%. It appears under **Configuration** on the device page. To change the volume of media, use the Google Cast integration that comes with Home Assistant.

## Reboot button

Press it to reboot the device. It appears under **Configuration** on the device page. It sends the same request as the [Reboot device](actions.md#reboot-device) action. To press it from an automation or script, use the `button.press` action:

```yaml
action: button.press
target:
  entity_id: button.living_room_reboot
```

The button is unavailable until Home Assistant finds the device on your network. If the device goes offline later, the button may stay available, but pressing it then has no effect. The `available` attribute of the [device sensor](#device-sensor) shows whether Home Assistant reached the device at its last request.

Not every device supports rebooting. The log can show "Successfully asked Living Room to reboot." even when the device didn't restart. If that happens, [reboot it from the Google Home app or unplug it for a minute](https://support.google.com/googlehome/answer/7072490).

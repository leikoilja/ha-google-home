# Actions

The integration adds these actions, which older Home Assistant versions called services. Use them in automations and scripts, or try them in [**Developer tools** > **Actions**](https://my.home-assistant.io/redirect/developer_services/).

| Action                                                | What it does                    |
| ----------------------------------------------------- | ------------------------------- |
| [`google_home.delete_alarm`](#delete-alarm)           | Deletes an alarm from a device  |
| [`google_home.delete_timer`](#delete-timer)           | Deletes a timer from a device   |
| [`google_home.delete_all_alarms`](#delete-all-alarms) | Deletes all alarms from devices |
| [`google_home.delete_all_timers`](#delete-all-timers) | Deletes all timers from devices |
| [`google_home.reboot_device`](#reboot-device)         | Reboots a device                |
| [`google_home.refresh_devices`](#refresh-devices)     | Updates all devices immediately |

## Delete alarm

Deletes one alarm from a device.

```yaml
action: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  alarm_id: alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51
  skip_refresh: false
```

| Field          | Description                                                                                                                                                                      |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `entity_id`    | Alarms sensor of the device, such as `sensor.kitchen_alarms`                                                                                                                     |
| `alarm_id`     | ID of the alarm to delete. Find it in the `alarms` attribute of the [alarms sensor](entities.md#alarms-sensor). It starts with `alarm/`.                                         |
| `skip_refresh` | Optional. `false`, the default, updates all devices straight after deleting, so the sensor shows the change immediately. `true` leaves the change for the next scheduled update. |

To delete the next alarm, use a template:

```yaml
action: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  alarm_id: "{{ state_attr('sensor.kitchen_alarms', 'alarms')[0].alarm_id }}"
  skip_refresh: false
```

If the ID has the wrong format, nothing is deleted and the Home Assistant log shows "Incorrect ID format! Please provide a valid alarm ID."

## Delete timer

Deletes one timer from a device.

```yaml
action: google_home.delete_timer
data:
  entity_id: sensor.kitchen_timers
  timer_id: timer/47dc1fa0-5ec0-2cc7-9ead-a94b85e22769
  skip_refresh: false
```

| Field          | Description                                                                                                                              |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `entity_id`    | Timers sensor of the device, such as `sensor.kitchen_timers`                                                                             |
| `timer_id`     | ID of the timer to delete. Find it in the `timers` attribute of the [timers sensor](entities.md#timers-sensor). It starts with `timer/`. |
| `skip_refresh` | Optional. Same as for [Delete alarm](#delete-alarm).                                                                                     |

## Delete all alarms

Deletes all alarms from one or more devices.

```yaml
action: google_home.delete_all_alarms
target:
  entity_id: sensor.kitchen_alarms
data:
  skip_refresh: false
```

| Field          | Description                                          |
| -------------- | ---------------------------------------------------- |
| `skip_refresh` | Optional. Same as for [Delete alarm](#delete-alarm). |

Target the alarms sensor of each device, or the devices themselves. The action asks each device for its current alarms first, so it also deletes alarms set since the last update.

## Delete all timers

Deletes all timers from one or more devices.

```yaml
action: google_home.delete_all_timers
target:
  entity_id: sensor.kitchen_timers
data:
  skip_refresh: false
```

| Field          | Description                                          |
| -------------- | ---------------------------------------------------- |
| `skip_refresh` | Optional. Same as for [Delete alarm](#delete-alarm). |

Target the timers sensor of each device, or the devices themselves. The action asks each device for its current timers first, so it also deletes timers set since the last update.

## Reboot device

Reboots a device.

```yaml
action: google_home.reboot_device
target:
  entity_id: sensor.kitchen_device
```

Target any Google Home sensor of the device, such as its device sensor. To reboot from the device page or a dashboard, press the device's [reboot button](entities.md#reboot-button) instead.

Not every device supports rebooting. The log can show "Successfully asked Kitchen to reboot." even when the device didn't restart. If that happens, [reboot it from the Google Home app or unplug it for a minute](https://support.google.com/googlehome/answer/7072490).

## Refresh devices

Updates alarms, timers and settings for all devices now, instead of waiting for the next scheduled update. It also restarts the countdown to the next update.

```yaml
action: google_home.refresh_devices
target:
  entity_id: sensor.kitchen_device
```

Target any one Google Home sensor; all devices are updated. Without a target, the action does nothing.

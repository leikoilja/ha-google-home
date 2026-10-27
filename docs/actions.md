# Actions

The integration adds these actions, which older Home Assistant versions called services. Use them in automations and scripts, or try them in [**Settings** > **Tools** > **Actions**](https://my.home-assistant.io/redirect/tools_actions/).

| Action                                                | What it does                    |
| ----------------------------------------------------- | ------------------------------- |
| [`google_home.delete_alarm`](#delete-alarm)           | Deletes an alarm from a device  |
| [`google_home.delete_timer`](#delete-timer)           | Deletes a timer from a device   |
| [`google_home.delete_all_alarms`](#delete-all-alarms) | Deletes all alarms from devices |
| [`google_home.delete_all_timers`](#delete-all-timers) | Deletes all timers from devices |
| [`google_home.reboot_device`](#reboot-device)         | Reboots a device                |
| [`google_home.refresh_devices`](#refresh-devices)     | Updates all devices immediately |

There are no actions to create, change or snooze alarms and timers, or to turn alarms on or off. The local API that the integration uses can only read and delete them. Set them by voice or on a display's screen. The [alarms](entities.md#alarms-sensor) and [timers](entities.md#timers-sensor) sensors show them after the next [scheduled update](installation.md#change-the-update-interval), or straight away when you run [`google_home.refresh_devices`](#refresh-devices).

The [Google Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) integration can't set them either: [Google's Assistant SDK](https://developers.google.com/assistant/sdk/overview) doesn't support timers and alarms.

## Delete alarm

Deletes one alarm from a device.

```yaml
action: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  alarm_id: alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51
  skip_refresh: false
```

| Field          | Description                                                                                                                                                                                                                                   |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `entity_id`    | Alarms sensor of the device, such as `sensor.kitchen_alarms`. Leave it out when you target the device instead, as described below.                                                                                                            |
| `alarm_id`     | ID of the alarm to delete. Find it in the `alarms` attribute of the [alarms sensor](entities.md#alarms-sensor). It starts with `alarm/`.                                                                                                      |
| `skip_refresh` | Optional. The sensor shows the deletion as soon as the device confirms it. `false`, the default, also updates all devices straight after deleting. `true` leaves other changes, such as an alarm set by voice, for the next scheduled update. |

To delete the next alarm, use a template:

```yaml
action: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  alarm_id: "{{ state_attr('sensor.kitchen_alarms', 'alarms')[0].alarm_id }}"
  skip_refresh: false
```

If the ID has the wrong format, nothing is deleted and the Home Assistant log shows "Incorrect ID format! Please provide a valid alarm ID."

Instead of the alarms sensor, you can target the device itself. This works only in YAML: the action form in **Tools** > **Actions** offers just the sensor. The device ID is the last part of the device page's address in Home Assistant.

```yaml
action: google_home.delete_alarm
target:
  device_id: 0123456789abcdef0123456789abcdef
data:
  alarm_id: alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51
```

The action then runs on the device's alarms sensor only. If that sensor is hidden or disabled, nothing is deleted and nothing is logged. Name a hidden sensor directly instead, and enable a disabled one first. Naming another sensor of the device, such as `sensor.kitchen_timers`, fails with "Entity sensor.kitchen_timers does not support action google_home.delete_alarm." and nothing is deleted on any device, even if you also name the alarms sensor. Target one device at a time: an area, floor or label target sends the alarm ID to every speaker it covers, and speakers without that alarm can log an error.

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
| `entity_id`    | Timers sensor of the device, such as `sensor.kitchen_timers`. Leave it out when you target the device instead, as described below.       |
| `timer_id`     | ID of the timer to delete. Find it in the `timers` attribute of the [timers sensor](entities.md#timers-sensor). It starts with `timer/`. |
| `skip_refresh` | Optional. Same as for [Delete alarm](#delete-alarm).                                                                                     |

You can target the device instead of its timers sensor, as for [Delete alarm](#delete-alarm). The action then runs on the timers sensor only, and does nothing if that sensor is hidden or disabled. Name a hidden sensor directly instead, and enable a disabled one first. Naming another sensor of the device fails, and nothing is deleted on any device, even if you also name the timers sensor. Target one device at a time: an area, floor or label target sends the timer ID to every speaker it covers, and speakers without that timer can log an error.

## Delete all alarms

Deletes all alarms from one or more devices.

```yaml
action: google_home.delete_all_alarms
target:
  entity_id: sensor.kitchen_alarms
data:
  skip_refresh: false
```

| Field          | Description                                                                                                                                                                                          |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skip_refresh` | Optional. The alarms and timers sensors show what is on the device straight away, since the action reads it before deleting. `false`, the default, also updates all devices straight after deleting. |

Target the alarms sensor of each device, or the devices themselves. A device target skips a device whose alarms sensor is hidden or disabled. Name a hidden sensor directly instead, and enable a disabled one first. Naming another sensor of a device, such as its timers sensor, fails, and nothing is deleted on any device. So does a group or template that includes other Google Home sensors, such as `{{ integration_entities('google_home') }}`. To clear every speaker, target `entity_id: all`. The action asks each device for its current alarms first, so it also deletes alarms set since the last update.

If the action can't get a device's current alarms, for example because the device is offline, it sends no delete request to that device, so its alarms stay. It still runs for the other devices you target, then fails with "Couldn't get the current alarms and timers from Kitchen, so nothing was deleted from it. Check that it's online and try again later". If several devices fail, one error names them all: "Couldn't get the current alarms and timers from these devices, so nothing was deleted from them: Bedroom, Kitchen. Check that they're online and try again later". The error stops your automation or script at this step. To run the next steps anyway, select **Continue on error** in the step's menu, or in YAML add `continue_on_error: true` to the step, next to `action:` rather than under `data:`. The devices in the error still keep their alarms. See [Continuing when a step fails](https://www.home-assistant.io/docs/scripts/#continuing-on-error).

## Delete all timers

Deletes all timers from one or more devices.

```yaml
action: google_home.delete_all_timers
target:
  entity_id: sensor.kitchen_timers
data:
  skip_refresh: false
```

| Field          | Description                                                    |
| -------------- | -------------------------------------------------------------- |
| `skip_refresh` | Optional. Same as for [Delete all alarms](#delete-all-alarms). |

Target the timers sensor of each device, or the devices themselves. A device target skips a device whose timers sensor is hidden or disabled. Name a hidden sensor directly instead, and enable a disabled one first. Naming another sensor of a device, such as its alarms sensor, fails, and nothing is deleted on any device. So does a group or template that includes other Google Home sensors. To clear every speaker, target `entity_id: all`. The action asks each device for its current timers first, so it also deletes timers set since the last update.

If the action can't get a device's current timers, it sends no delete request to that device, so its timers stay. It still runs for the other devices you target, then fails with the same error as Delete all alarms, which names every device that failed. To run the next steps of your automation or script anyway, see [Delete all alarms](#delete-all-alarms).

## Reboot device

Reboots a device.

```yaml
action: google_home.reboot_device
target:
  entity_id: sensor.kitchen_device
```

Target any Google Home sensor of the device, such as its device sensor, or the device itself. A device, area or floor target, or a label on the device, reboots each device once. It silently skips a device that has [only a device sensor](troubleshooting.md#no-alarms-or-timers-sensors), or whose alarms and timers sensors are both hidden or disabled. For a device without alarms, such as an NVIDIA Shield, or with hidden or disabled sensors, target its device sensor instead. An offline device can't be rebooted until it answers. To reboot from the device page or a dashboard, press the device's [reboot button](entities.md#reboot-button) instead.

Not every device supports rebooting. The log can show "Successfully asked Kitchen to reboot." even when the device didn't restart. If that happens, [reboot it from the Google Home app or unplug it for a minute](https://support.google.com/googlehome/answer/7072490).

## Refresh devices

Updates alarms, timers and settings for all devices now, instead of waiting for the next scheduled update. It also restarts the countdown to the next update.

```yaml
action: google_home.refresh_devices
target:
  entity_id: sensor.kitchen_alarms
```

Target an alarms or timers sensor, or a device that has [alarms and timers sensors](troubleshooting.md#no-alarms-or-timers-sensors). All devices are updated once, however many sensors the target covers. The action needs a target.

If the sensors you target are unavailable, run [`homeassistant.update_entity`](https://www.home-assistant.io/actions/homeassistant.update_entity/) on one Google Home sensor instead. Home Assistant runs `refresh_devices` only on available sensors. The device sensor is unavailable while the integration doesn't know the device's IP address, every sensor of a device that Google no longer lists is unavailable, the alarms and timers sensors of a [device without alarms and timers](troubleshooting.md#devices-without-alarms-and-timers) are unavailable, and every sensor is unavailable after a failed update. An alarms or timers sensor that shows `unavailable` only because nothing is coming up still works: in [**Settings** > **Tools** > **States**](https://my.home-assistant.io/redirect/tools_states/) it still has its `alarms` or `timers` attribute. If you name an unavailable sensor directly, the log shows "Referenced entities sensor.kitchen_alarms are missing or not currently available", even if another named sensor updated the devices.

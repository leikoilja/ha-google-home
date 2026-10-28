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

| Field          | Description                                                                                                                                                                                                                                                                                                            |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `entity_id`    | Alarms sensor of the device, such as `sensor.kitchen_alarms`. Leave it out when you target the device instead, as described below.                                                                                                                                                                                     |
| `alarm_id`     | ID of the alarm to delete. Find it in the `alarms` attribute of the [alarms sensor](entities.md#alarms-sensor). It starts with `alarm/`.                                                                                                                                                                               |
| `skip_refresh` | Optional. The action reads the device's current alarms before deleting, so the sensor shows them straight away, without the deleted alarm once the device confirms. `false`, the default, also asks for an update of all devices after deleting. `true` leaves changes on other devices for the next scheduled update. |

To delete the next alarm, use a template:

```yaml
action: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  alarm_id: "{{ state_attr('sensor.kitchen_alarms', 'alarms')[0].alarm_id }}"
  skip_refresh: false
```

The action asks the device for its current alarms first, and sends the delete only if the device still has the alarm. Otherwise it fails with "Couldn't find the alarm alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51 on the devices you targeted. It may already have gone off or been deleted". This can happen with the template above if the sensor hasn't updated since the alarm was cancelled by voice. An ID that doesn't start with `alarm/` or has the wrong length fails before any device is asked: "“alarm/123” isn't an alarm ID. Copy the ID, which starts with alarm/, from the alarms attribute of the device's alarms sensor". For other errors, and how to let your automation carry on, see [If a delete fails](#if-a-delete-fails).

Instead of the alarms sensor, you can target the device itself. This works only in YAML: the action form in **Tools** > **Actions** offers just the sensor. The device ID is the last part of the device page's address in Home Assistant.

```yaml
action: google_home.delete_alarm
target:
  device_id: 0123456789abcdef0123456789abcdef
data:
  alarm_id: alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51
```

The action then runs on the device's alarms sensor only. If that sensor is hidden or disabled, nothing is deleted and nothing is logged. Name a hidden sensor directly instead, and enable a disabled one first. Naming another sensor of the device, such as `sensor.kitchen_timers`, fails with "Entity sensor.kitchen_timers does not support action google_home.delete_alarm." and nothing is deleted on any device, even if you also name the alarms sensor. An area, floor or label target asks each speaker it covers for its alarms, except those whose alarms sensor is hidden, disabled or unavailable, and sends the delete only to the speakers that have the alarm.

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

As for [Delete alarm](#delete-alarm), the action asks the device for its current timers first, and sends the delete only if the device still has the timer. Otherwise it fails with "Couldn't find the timer timer/47dc1fa0-5ec0-2cc7-9ead-a94b85e22769 on the devices you targeted. It may already have gone off or been deleted". An ID that doesn't start with `timer/` or has the wrong length fails before any device is asked. See [If a delete fails](#if-a-delete-fails).

You can target the device instead of its timers sensor, as for [Delete alarm](#delete-alarm). The action then runs on the timers sensor only, and does nothing if that sensor is hidden or disabled. Name a hidden sensor directly instead, and enable a disabled one first. Naming another sensor of the device fails, and nothing is deleted on any device, even if you also name the timers sensor. An area, floor or label target sends the delete only to the speakers that have the timer.

## Delete all alarms

Deletes all alarms from one or more devices.

```yaml
action: google_home.delete_all_alarms
target:
  entity_id: sensor.kitchen_alarms
data:
  skip_refresh: false
```

| Field          | Description                                                                                                                                                                                               |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skip_refresh` | Optional. The alarms and timers sensors show what is on the device straight away, since the action reads it before deleting. `false`, the default, also asks for an update of all devices after deleting. |

Target the alarms sensor of each device, or the devices themselves. A device target skips a device whose alarms sensor is hidden or disabled. Name a hidden sensor directly instead, and enable a disabled one first. Naming another sensor of a device, such as its timers sensor, fails, and nothing is deleted on any device. So does a group or template that includes other Google Home sensors, such as `{{ integration_entities('google_home') }}`. To clear every speaker, target `entity_id: all`. The action asks each device for its current alarms first, so it also deletes alarms set since the last update.

If the action can't get a device's current alarms, for example because the device is offline, it sends no delete request to that device, so its alarms stay. It still runs for the other devices you target, then fails. See [If a delete fails](#if-a-delete-fails).

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

If the action can't get a device's current timers, it sends no delete request to that device, so its timers stay. It still runs for the other devices you target, then fails. See [If a delete fails](#if-a-delete-fails).

## If a delete fails

The four delete actions fail, rather than look successful, when an alarm or timer may still be set. The error names each device that failed. The action still runs for the other devices you target before it fails.

- A device that doesn't send its current alarms and timers, for example because it's offline or rejects its token, gets no delete request: "Couldn't get the current alarms and timers from Kitchen, so nothing was deleted from it. Check that it's online and try again later".
- A device that doesn't confirm the delete, because it stops answering, refuses or sends an unexpected reply: "Kitchen didn't confirm deleting the alarms or timers, so they may still be set. Check that it's online and try again later". The device may still have deleted them. Unless `skip_refresh` is `true`, the action asks for an update of all devices, which shows what the device has once it answers.
- If several devices fail, one error names them all. When none of them sent its current alarms and timers: "Couldn't get the current alarms and timers from these devices, so nothing was deleted from them: Bedroom, Kitchen. Check that they're online and try again later". Otherwise: "Couldn't delete alarms or timers from these devices, or confirm that they were deleted: Bedroom, Kitchen. Check that they're online and try again later".

Delete alarm and Delete timer report that no device has the ID when every device the action checks sends its current list without it. Home Assistant skips unavailable sensors, as described below, and with a device, area, floor or label target also hidden or disabled ones, so a device it skipped may still have the alarm or timer. Retrying after a device didn't confirm can give that error if the alarm or timer is gone by then.

The error stops your automation or script at this step. To run the next steps anyway, select **Continue on error** in the step's menu, or in YAML add `continue_on_error: true` to the step, next to `action:` rather than under `data:`:

```yaml
- action: google_home.delete_all_alarms
  target:
    entity_id: all
  continue_on_error: true
```

This also covers an ID that no device has, or one in the wrong format. It doesn't cover configuration errors, such as a missing `alarm_id`, or one that is a list instead of text. See [Continuing when a step fails](https://www.home-assistant.io/docs/scripts/#continuing-on-error).

Home Assistant runs these actions only on available sensors, and skips the others without an error. Every sensor of a device that Google no longer lists is unavailable, the alarms and timers sensors of a [device without alarms and timers](troubleshooting.md#devices-without-alarms-and-timers) are unavailable, and every sensor is unavailable after a failed update. If all the sensors you target are unavailable, nothing is deleted and the action doesn't fail. An alarms or timers sensor that shows `unavailable` only because nothing is coming up is still available, and the actions run on it. If you name an unavailable sensor directly, the log shows "Referenced entities sensor.kitchen_alarms are missing or not currently available".

## Reboot device

Reboots a device.

```yaml
action: google_home.reboot_device
target:
  entity_id: sensor.kitchen_device
```

Target any Google Home sensor of the device, such as its device sensor, or the device itself. A device, area or floor target, or a label on the device, reboots each device once. It silently skips a device that has [only a device sensor](troubleshooting.md#no-alarms-or-timers-sensors), or whose alarms and timers sensors are both hidden or disabled. For a device without alarms, such as an NVIDIA Shield, or with hidden or disabled sensors, target its device sensor instead. To reboot from the device page or a dashboard, press the device's [reboot button](entities.md#reboot-button) instead.

If a device doesn't confirm the reboot, for example because it's offline, the action fails with an error that names the device and says why, such as "Couldn't reach Kitchen. Check that it's on and connected to your network, then try again". For the other messages, and how to let your automation carry on, see [If a setting or reboot fails](entities.md#if-a-setting-or-reboot-fails). With several devices, the action reboots every device that answers, then fails. If more than one device fails, one error names them all: "These devices didn't confirm that they'll reboot: Bedroom, Kitchen. Check that they're online and try again later".

Not every device supports rebooting. A device can accept the request, so there's no error and the log shows "Successfully asked Kitchen to reboot.", even when it doesn't restart. If that happens, [reboot it from the Google Home app or unplug it for a minute](https://support.google.com/googlehome/answer/7072490).

## Refresh devices

Updates alarms, timers and settings for all devices now, instead of waiting for the next scheduled update. It also restarts the countdown to the next update.

```yaml
action: google_home.refresh_devices
target:
  entity_id: sensor.kitchen_alarms
```

Target an alarms or timers sensor, or a device that has [alarms and timers sensors](troubleshooting.md#no-alarms-or-timers-sensors). All devices are updated once, however many sensors the target covers. The action needs a target.

If the sensors you target are unavailable, run [`homeassistant.update_entity`](https://www.home-assistant.io/actions/homeassistant.update_entity/) on one Google Home sensor instead. Home Assistant runs `refresh_devices` only on available sensors. The device sensor is unavailable while the integration doesn't know the device's IP address, every sensor of a device that Google no longer lists is unavailable, the alarms and timers sensors of a [device without alarms and timers](troubleshooting.md#devices-without-alarms-and-timers) are unavailable, and every sensor is unavailable after a failed update. An alarms or timers sensor that shows `unavailable` only because nothing is coming up still works: in [**Settings** > **Tools** > **States**](https://my.home-assistant.io/redirect/tools_states/) it still has its `alarms` or `timers` attribute. If you name an unavailable sensor directly, the log shows "Referenced entities sensor.kitchen_alarms are missing or not currently available", even if another named sensor updated the devices.

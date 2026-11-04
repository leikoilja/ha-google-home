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

There are no actions to create, change or snooze alarms and timers, or to turn alarms on or off. The local API that the integration uses can only read and delete them. Set them by voice or on a display's screen. The [alarms](entities.md#alarms-sensor) and [timers](entities.md#timers-sensor) sensors show them after the next [scheduled update](configuration.md#change-the-update-interval), or straight away when you run [`google_home.refresh_devices`](#refresh-devices).

The [Google Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) integration can't set them either: [Google's Assistant SDK](https://developers.google.com/assistant/sdk/overview) doesn't support timers and alarms.

Integrations that come with Home Assistant add other actions for the same devices, such as playing media, setting the media volume and broadcasting messages. See [Other integrations for the same devices](other-integrations.md#other-integrations-for-the-same-devices).

## Delete alarm

Deletes one alarm from a device.

```yaml
action: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  alarm_id: alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51
```

| Field          | Description                                                                                                                                                                                                                                                                                                                                                                     |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `entity_id`    | Alarms sensor of the device, such as `sensor.kitchen_alarms`. Leave it out when you [target the device](#targets) instead.                                                                                                                                                                                                                                                      |
| `alarm_id`     | ID of the alarm to delete. Find it in the `alarms` attribute of the [alarms sensor](entities.md#alarms-sensor). It starts with `alarm/`.                                                                                                                                                                                                                                        |
| `skip_refresh` | Optional. The sensor shows the device's current alarms straight away, without the deleted one once the device confirms. By default (`false`), the action then also asks each device it sent a delete to for an update. `true` leaves that to the next scheduled update. To update all devices, use [Refresh devices](#refresh-devices). |

To delete the next alarm, use a template:

```yaml
action: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  alarm_id: "{{ state_attr('sensor.kitchen_alarms', 'alarms')[0].alarm_id }}"
```

The action asks the device for its current alarms first, and sends the delete only if the device still has the alarm. Otherwise it fails. This can happen with the template above if the sensor hasn't updated since the alarm was cancelled by voice. See [If a delete fails](#if-a-delete-fails).

## Delete timer

Deletes one timer from a device.

```yaml
action: google_home.delete_timer
data:
  entity_id: sensor.kitchen_timers
  timer_id: timer/47dc1fa0-5ec0-2cc7-9ead-a94b85e22769
```

| Field          | Description                                                                                                                              |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `entity_id`    | Timers sensor of the device, such as `sensor.kitchen_timers`. Leave it out when you [target the device](#targets) instead.               |
| `timer_id`     | ID of the timer to delete. Find it in the `timers` attribute of the [timers sensor](entities.md#timers-sensor). It starts with `timer/`. |
| `skip_refresh` | Optional. Same as for [Delete alarm](#delete-alarm).                                                                                     |

As for [Delete alarm](#delete-alarm), the action fails if the device no longer has the timer. See [If a delete fails](#if-a-delete-fails).

## Delete all alarms

Deletes all alarms from one or more devices.

```yaml
action: google_home.delete_all_alarms
target:
  entity_id: sensor.kitchen_alarms
```

| Field          | Description                                          |
| -------------- | ---------------------------------------------------- |
| `skip_refresh` | Optional. Same as for [Delete alarm](#delete-alarm). |

Target the alarms sensor of each device, or the devices themselves; see [Targets](#targets). To clear every speaker, target `entity_id: all`. The action asks each device for its current alarms first, so it also deletes alarms set since the last update.

If the action can't get a device's current alarms, for example because the device has just gone offline, that device's alarms stay. See [If a delete fails](#if-a-delete-fails).

## Delete all timers

Deletes all timers from one or more devices.

```yaml
action: google_home.delete_all_timers
target:
  entity_id: sensor.kitchen_timers
```

| Field          | Description                                          |
| -------------- | ---------------------------------------------------- |
| `skip_refresh` | Optional. Same as for [Delete alarm](#delete-alarm). |

Target the timers sensor of each device, or the devices themselves; see [Targets](#targets). To clear every speaker, target `entity_id: all`. The action asks each device for its current timers first, so it also deletes timers set since the last update.

If the action can't get a device's current timers, that device's timers stay. See [If a delete fails](#if-a-delete-fails).

## If a delete fails

The four delete actions fail, rather than look successful, when an alarm or timer may still be set, for example because a device has just gone offline. The action still runs for the other devices you target, then fails with one error that names every device that failed. A device whose sensor is [unavailable](#unavailable-sensors) is skipped without an error, so it isn't named. Delete alarm and Delete timer also fail when no device has the ID, or when it isn't a valid ID.

The error stops your automation or script at this step, unless you [let it continue](#continue-after-an-error). For each message and what to do, see [A delete fails](troubleshooting.md#a-delete-fails).

## Reboot device

Reboots a device.

```yaml
action: google_home.reboot_device
target:
  entity_id: sensor.kitchen_device
```

Target a Google Home sensor of the device, such as its device sensor, or the device itself; see [Targets](#targets). Its [update sensor](entities.md#update-sensor) doesn't work: it's a binary sensor, so naming it reboots nothing, and the log shows "Referenced entities binary_sensor.kitchen_update are missing or not currently available". To reboot from the device page or a dashboard, press the device's [reboot button](entities.md#reboot-button) instead.

If a device doesn't confirm the reboot, for example because it has just gone offline, the action reboots every other device that answers, then fails with one error that names every device that didn't confirm. A device whose sensors are [unavailable](#unavailable-sensors) is skipped without an error. See [A setting or reboot fails](troubleshooting.md#a-setting-or-reboot-fails), and to let your automation carry on, [Continue after an error](#continue-after-an-error).

Not every device supports rebooting, even when there's no error; see the [reboot button](entities.md#reboot-button).

## Refresh devices

Updates alarms, timers and settings for all devices now, except [disabled ones](configuration.md#stop-checking-some-devices), instead of waiting for the next scheduled update. It also restarts the countdown to the next update. While [polling is turned off](configuration.md#turn-off-polling), it's how your devices update, and it also gets new tokens for devices that rejected theirs.

```yaml
action: google_home.refresh_devices
target:
  entity_id: sensor.kitchen_alarms
```

Target an alarms or timers sensor, or a device that has [alarms and timers sensors](troubleshooting.md#no-alarms-or-timers-sensors). All devices are updated once, however many sensors the target covers. The action needs a target.

The action also runs when the sensors you target are [unavailable](#unavailable-sensors), for example while a device doesn't answer, so it can bring that device back: once the device answers, its entities are available again. A target that covers no Google Home sensor, such as only a light, updates nothing.

## Targets

You can name sensors, as in the examples above, or target devices, areas, floors or labels on devices. For each device such a target covers, the action uses the device's alarms and timers sensors, and silently skips those that are hidden or disabled. Name a hidden sensor directly instead, and enable a disabled one first.

- **Delete alarm** and **Delete all alarms** run on each device's alarms sensor, and **Delete timer** and **Delete all timers** on its timers sensor. With an area, floor or label target, Delete alarm and Delete timer ask each speaker for its current alarms or timers, and send the delete only to the speakers that have the ID.
- **Reboot device** reboots each device once, however many of its sensors the target covers. It skips a device that has [only a device sensor](troubleshooting.md#no-alarms-or-timers-sensors), or whose alarms and timers sensors are both hidden or disabled. For a device without alarms, such as an NVIDIA Shield, or with hidden or disabled sensors, target its device sensor instead.
- **Refresh devices** updates all devices once.

For the four delete actions, naming another Google Home sensor, such as a device sensor, or a group or template that includes one, such as `{{ integration_entities('google_home') }}`, fails, and nothing is deleted on any device. For example, Delete alarm with `sensor.kitchen_timers` fails with "Entity sensor.kitchen_timers does not support action google_home.delete_alarm." Naming the [update sensor](entities.md#update-sensor) doesn't fail: it's a binary sensor, so the actions skip it and run on the other sensors you name, as Reboot device does.

The form for Delete alarm and Delete timer in **Settings** > **Tools** > **Actions** offers only the sensor. To target a device, use YAML. The device ID is the last part of the device page's address in Home Assistant.

```yaml
action: google_home.delete_alarm
target:
  device_id: 0123456789abcdef0123456789abcdef
data:
  alarm_id: alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51
```

## Unavailable sensors

Except for [Refresh devices](#refresh-devices), Home Assistant runs these actions only on available sensors, and skips the others without an error. If all the sensors you target are unavailable, nothing happens and the action doesn't fail. If you name an unavailable sensor directly, the log shows "Referenced entities sensor.kitchen_alarms are missing or not currently available", even if another sensor you named ran the action.

While the integration itself isn't loaded, for example because its setup failed, its sensors are unavailable too, but the actions fail instead of doing nothing. See [An action fails while the integration isn't loaded](troubleshooting.md#an-action-fails-while-the-integration-isnt-loaded).

A device's sensors are unavailable, for example, once the device hasn't answered 5 updates in a row; see [When entities are unavailable](entities.md#when-entities-are-unavailable). An alarms or timers sensor that shows `unavailable` only because nothing is coming up is still available, and the actions run on it: in [**Settings** > **Tools** > **States**](https://my.home-assistant.io/redirect/tools_states/) it still has its `alarms` or `timers` attribute.

## Continue after an error

An action that fails stops your automation or script at that step. To run the next steps anyway, select **Continue on error** in the step's menu, or in YAML add `continue_on_error: true` to the step, next to `action:` rather than under `data:`:

```yaml
- action: google_home.delete_all_alarms
  target:
    entity_id: all
  continue_on_error: true
```

This works the same for a step that turns the [Do Not Disturb switch](entities.md#do-not-disturb-switch) on or off, sets the [alarm volume](entities.md#alarm-volume) or presses the [reboot button](entities.md#reboot-button). It also covers an alarm or timer ID that no device has, or one in the wrong format, and the error while the integration [isn't loaded](troubleshooting.md#an-action-fails-while-the-integration-isnt-loaded). It doesn't cover configuration errors, such as a missing `alarm_id`, or one that is a list instead of text. See [Continuing when a step fails](https://www.home-assistant.io/docs/scripts/#continuing-on-error).

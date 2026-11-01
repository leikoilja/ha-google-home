# Entities

Each Google Home device gets the entities below. The examples use a device named _Living Room_ that isn't in an area, with Home Assistant in English. If your entity IDs repeat the room, see [Room name twice in entity IDs](#room-name-twice-in-entity-ids). In other languages, see [Entity names in other languages](#entity-names-in-other-languages).

| Entity                | Example                             | What it does                                              |
| --------------------- | ----------------------------------- | --------------------------------------------------------- |
| Alarms sensor         | `sensor.living_room_alarms`         | Time of the next alarm, with all alarms in its attributes |
| Timers sensor         | `sensor.living_room_timers`         | Time of the next timer, with all timers in its attributes |
| Device sensor         | `sensor.living_room_device`         | The device's IP address and connection details            |
| Do Not Disturb switch | `switch.living_room_do_not_disturb` | Turns Do Not Disturb on or off                            |
| Alarm volume          | `number.living_room_alarm_volume`   | Sets the alarm volume, from 0 to 100%                     |
| Reboot button         | `button.living_room_reboot`         | Reboots the device                                        |

The alarms sensor, timers sensor, switch and alarm volume are added once the device answers successfully. If a device has only a device sensor and a reboot button, see [No alarms or timers sensors](troubleshooting.md#no-alarms-or-timers-sensors). A device without alarms and timers, such as a Chromecast Audio, doesn't get these four entities.

Entities become unavailable, for example, while a device is unplugged or after you remove it from the Google Home app. See [When entities are unavailable](#when-entities-are-unavailable).

## Alarms sensor

The state is the time of the next alarm, such as `2026-03-07T15:26:17+01:00`. It is `unavailable` when no alarm is set, or when all alarms are inactive or missed. That is only its state: the sensor keeps its attributes, and actions still run on it.

To start automations at the time of the next alarm or timer, see [Automation examples](automations.md).

The state uses the same format as the [next alarm sensor](https://companion.home-assistant.io/docs/core/sensors/#next-alarm-sensor) of the Home Assistant mobile app, such as `sensor.phone_next_alarm`. You can use both in the same automations.

| Attribute           | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| `next_alarm_status` | [Status](#alarm-and-timer-status) of the next alarm, or `none` if there are no alarms |
| `alarm_volume`      | Alarm volume in percent, the same value as the alarm volume entity                    |
| `alarms`            | List of all alarms, with the next one first. Inactive and missed alarms come last.    |

Each alarm in `alarms` has these keys:

| Key              | Example                                              | Description                                                                                                                                         |
| ---------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `alarm_id`       | `alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51`{.break} | ID of the alarm. Use it to [delete the alarm](actions.md#delete-alarm).                                                                             |
| `fire_time`      | `1772893577`                                         | When the alarm goes off, as a Unix timestamp in seconds                                                                                             |
| `local_time`     | `2026-03-07 15:26:17`                                | When the alarm goes off, in Home Assistant's time zone                                                                                              |
| `local_time_iso` | `2026-03-07T15:26:17+01:00`                          | The same time in ISO 8601 format, convenient for automations                                                                                        |
| `status`         | `set`                                                | [Status](#alarm-and-timer-status) of the alarm                                                                                                      |
| `label`          | `Wake up`                                            | Name of the alarm, if you gave it one                                                                                                               |
| `recurrence`     | `[1, 2, 3, 4, 5]`                                    | Days of the week the alarm repeats on. Following Google's convention, the week starts on Sunday: `0` is Sunday, `1` is Monday, and `6` is Saturday. |

## Timers sensor

The state is the time the next timer goes off, such as `2026-03-07T15:26:17+01:00`. It is `unavailable` when no timer is set, or when all timers are paused. That is only its state: the sensor keeps its attributes, and actions still run on it.

| Attribute           | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| `next_timer_status` | [Status](#alarm-and-timer-status) of the next timer, or `none` if there are no timers |
| `timers`            | List of all timers, with the one that goes off next first. Paused timers come last.   |

Each timer in `timers` has these keys:

| Key              | Example                                              | Description                                                                                                                                          |
| ---------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `timer_id`       | `timer/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51`{.break} | ID of the timer. Use it to [delete the timer](actions.md#delete-timer).                                                                              |
| `fire_time`      | `1772893577`                                         | When the timer goes off, as a Unix timestamp in seconds. `None` while paused.                                                                        |
| `local_time`     | `2026-03-07 15:26:17`                                | When the timer goes off, in Home Assistant's time zone. `None` while paused.                                                                         |
| `local_time_iso` | `2026-03-07T15:26:17+01:00`                          | The same time in ISO 8601 format. `None` while paused.                                                                                               |
| `duration`       | `0:10:00`                                            | Length the timer was set for, as hours:minutes:seconds                                                                                               |
| `remaining`      | `0:07:45`                                            | Time left on a paused timer, as hours:minutes:seconds. `None` for other timers, which have `fire_time` instead, or if the speaker doesn't report it. |
| `status`         | `set`                                                | [Status](#alarm-and-timer-status) of the timer                                                                                                       |
| `label`          | `Pasta`                                              | Name of the timer, if you gave it one                                                                                                                |

To use the time left in a template or automation, convert `remaining` to seconds with `as_timedelta`. For example, `{{ as_timedelta('0:07:45').total_seconds() }}` gives 465 seconds. `remaining` is `None` (shown as `null`) for timers that aren't paused or if the speaker doesn't report it, and `as_timedelta` raises an error for `None`, so check first, for example with `timer.remaining is not none`.

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

The state is the device's IP address on your network. If no IP address is available for the device, or the device hasn't answered 5 updates in a row, the sensor is unavailable and the device details listed below are hidden. The sensor appears under **Diagnostic** on the device page.

| Attribute     | Description                                                                                                                                                                                                          |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `device_id`   | Google's ID for the device                                                                                                                                                                                           |
| `device_name` | Name of the device in the Google Home app                                                                                                                                                                            |
| `ip_address`  | IP address of the device                                                                                                                                                                                             |
| `available`   | `true` if, at the last update, the device answered successfully when asked for its alarms, or else when asked for its information, which needs no token. `false` otherwise, for example while the device is offline. |
| `auth_token`  | Token Home Assistant uses to talk to the device                                                                                                                                                                      |

!!! warning

    Anyone who can see the device sensor in Home Assistant can read `auth_token` and use it to control the device from your network until the token expires, usually within a day. Only give Home Assistant access to people you trust with your devices.

## Do Not Disturb switch

Turns Do Not Disturb on or off on the device. It appears under **Configuration** on the device page. If the request to the device fails, Home Assistant shows an error and the switch keeps its old setting; see [If a setting or reboot fails](#if-a-setting-or-reboot-fails).

## Alarm volume

Sets how loud alarms ring on the device, from 0 to 100%. It appears under **Configuration** on the device page. If the request to the device fails, Home Assistant shows an error and the old volume stays; see [If a setting or reboot fails](#if-a-setting-or-reboot-fails). The volume of music and other media is a separate setting that you change on the Google Cast media player; see [Other integrations for the same devices](other-integrations.md#other-integrations-for-the-same-devices).

## Reboot button

Press it to reboot the device. It appears under **Configuration** on the device page. It sends the same request as the [Reboot device](actions.md#reboot-device) action. To press it from an automation or script, use the `button.press` action:

```yaml
action: button.press
target:
  entity_id: button.living_room_reboot
```

The button is unavailable until Home Assistant finds the device on your network, and once the device hasn't answered 5 updates in a row. If the device goes offline, pressing the button before then fails with an error; see [If a setting or reboot fails](#if-a-setting-or-reboot-fails). The `available` attribute of the [device sensor](#device-sensor) shows whether the device answered successfully at the last update.

Not every device supports rebooting. A device can accept the request, so there's no error and the log shows "Successfully asked Living Room to reboot.", even when it doesn't restart. If that happens, [reboot it from the Google Home app or unplug it for a minute](https://support.google.com/googlehome/answer/7072490).

The button's state is the time it was last pressed in Home Assistant, not when the device last restarted. It's `unknown` until the first press. Each press sets it, even one that fails or doesn't restart the device. Rebooting the device with the [Reboot device](actions.md#reboot-device) action or from the Google Home app doesn't set it, and neither does unplugging the device or a power cut.

Home Assistant keeps this time when it restarts. If the button is unavailable when Home Assistant stops, for example while the device is unplugged, the time is lost: once the button is available again, its state is `unknown` until the next press.

## When entities are unavailable

All entities of a device are unavailable:

- Once Google no longer lists the device, for example after you remove it from the Google Home app, until the integration removes the device. See [Remove a device](configuration.md#remove-a-device).
- Once the device hasn't answered 5 [updates](configuration.md#change-the-update-interval) in a row, for example while it's unplugged. At the default 15-second interval, that's usually after one to two minutes. With a shorter interval, a speaker that restarts can miss 5 updates and become unavailable for a moment; with a longer one, it takes longer to notice. A [device without alarms and timers](troubleshooting.md#devices-without-alarms-and-timers) is asked only for its information at each update, and its device sensor and reboot button follow its answers the same way.
- After the device's update fails unexpectedly, for example on a reply the integration can't read, until its next update. Once the integration has started, this affects only that device. While the integration is starting, such an error stops it from starting, and Home Assistant tries again later. When the integration can't get your device list from Google, the devices keep updating with the tokens and addresses they have, and their entities stay available.

Some entities are also unavailable on their own:

- On a [device without alarms and timers](troubleshooting.md#devices-without-alarms-and-timers), such as a Chromecast Audio, the alarms sensor, timers sensor, switch and alarm volume, if it had them. Reloading the integration or restarting Home Assistant brings them back only if the device then answers for these features.
- The device sensor and reboot button, while Home Assistant doesn't know the device's IP address.

Entities that became unavailable because the device didn't answer are available again at the next update the device answers with anything other than "not found". A speaker that is starting answers "not found" for a while, so they stay unavailable until then. Being available again doesn't always mean new values: if the device rejects its token and Google gives no new one, or answers with another error, they show the values they had. See [Alarms, timers or settings stop changing](troubleshooting.md#alarms-timers-or-settings-stop-changing).

Home Assistant skips an unavailable entity without an error, so an action on it does nothing and doesn't fail. For the integration's own actions, see [Unavailable sensors](actions.md#unavailable-sensors).

The alarms and timers sensors also show `unavailable` as their state when nothing is coming up. That isn't an unavailable entity: in [**Settings** > **Tools** > **States**](https://my.home-assistant.io/redirect/tools_states/), the sensor still has its `alarms` or `timers` attribute, and actions still run on it.

## If a setting or reboot fails

Turning Do Not Disturb on or off, setting the alarm volume and pressing Reboot fail with an error, rather than look successful, when the request to the device fails, for example because the device has just gone offline. Once its entities are [unavailable](#when-entities-are-unavailable), Home Assistant skips them without an error. The error names the device and says why. For each message and what to do, see [A setting or reboot fails](troubleshooting.md#a-setting-or-reboot-fails).

The error stops your automation or script at this step, unless you [let it continue](actions.md#continue-after-an-error). If one action targets several entities, such as the Do Not Disturb switches of two devices, Home Assistant runs it on all of them and shows only the first error. For several reboots, use [Reboot device](actions.md#reboot-device), which names every device that failed.

## Room name twice in entity IDs

By default, Home Assistant starts new entity IDs with the device's area. A device named _Speaker_ in the _Living Room_ area gets `sensor.living_room_speaker_alarms`. Google Home device names often contain the room already, so a device named _Living Room speaker_ in that area gets `sensor.living_room_living_room_speaker_alarms`.

To avoid this for entities added later, do one of the following:

- Rename the device in Home Assistant without the room, such as _Speaker_. The device keeps its name in the Google Home app.
- Remove **Area** in **Settings** > **System** > **Entity ID format**. This is a global setting for new entity IDs, not just Google Home ones. Integrations that suggest their own entity IDs don't use it.

Entities you already have keep their entity IDs. Changing them is optional. Go to **Settings** > **Devices & services** > **Google Home** and select the device, such as _Kitchen display_. Open the **⋮** menu and select **Recreate entity IDs**. This:

- Builds the entity IDs from the current device name and entity ID format. Do one of the steps above first. Otherwise a device whose name contains its room gets the room twice in all its entity IDs.
- Uses each entity's name and doesn't change it: the name you gave it, otherwise its default name in the language Home Assistant uses for entity IDs. See [Entity names in other languages](#entity-names-in-other-languages).
- Changes each entity ID of the device that differs from the one Home Assistant would create now, including any you changed yourself. Entity IDs that already match stay the same.

Home Assistant lists the old and new entity IDs before it changes them. If a new entity ID still contains an earlier device name, cancel. Open that entity's settings, select the restore icon (**Restore default name**) next to its name, select **Update**, then recreate the entity IDs again.

After you confirm, update the automations, scripts and manually configured dashboard cards that use the entity IDs that changed. See [Customizing entities](https://www.home-assistant.io/docs/configuration/customizing-entities/#changing-the-attributes-of-an-entity).

## Entity names in other languages

Home Assistant shows these entities' names in its language, such as _Wecker_ for the alarms sensor in German, or in English where a translation is missing. To correct a translation, see [Translate the integration](contributing.md#translate-the-integration).

In Catalan, Czech, Danish, Dutch, Finnish, French, German, Hungarian, Indonesian, Italian, Norwegian, Polish, Portuguese, Romanian, Slovak, Spanish and Swedish, Home Assistant also builds new entity IDs from the translated names. In German, the alarms sensor of a new device named _Living Room_ gets `sensor.living_room_wecker`. In other languages, such as Russian or Japanese, entity IDs use the English names, as in the table at the top of this page. What counts is the language set for Home Assistant itself, not the language in your user profile.

Entities you already have keep their entity IDs in every language. In the languages listed above, a new device's entity IDs can then differ from those of your other devices, and [Recreate entity IDs](#room-name-twice-in-entity-ids) changes the existing ones to the translated names too, unless you gave an entity a name of your own. Check the list of changes before you confirm.

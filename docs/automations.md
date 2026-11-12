# Automation examples

The [alarms and timers sensors](entities.md) show the time of the next alarm or timer. Home Assistant's [time trigger](https://www.home-assistant.io/docs/automation/trigger/#time-trigger) can start an automation at that time, or a set time before or after it.

**For the most precise timing at an alarm's or timer's scheduled due time, use a time trigger on its sensor.** Once the integration has seen the due time, Home Assistant schedules the trigger for that time without waiting for another device check. A `ringing` event waits until a successful check reports ringing, so it can arrive later. The due time must be known beforehand, and changes are only picked up at the next check; see [When the trigger runs](#when-the-trigger-runs).

To use an example, go to **Settings** > **Automations & scenes** > **Create automation** > **Create new automation**, open the **⋮** menu, select **Edit in YAML**, and paste it. The examples use Google Home devices, such as _Bedroom_ and _Kitchen_, that aren't in an area. Replace the entity IDs with your own. If yours repeat the room, see [Room name twice in entity IDs](entities.md#room-name-twice-in-entity-ids).

## Before the next alarm

Turn on the bedroom lights 10 minutes before the next alarm on the bedroom speaker:

```yaml
alias: Wake-up lights
triggers:
  - trigger: time
    at:
      entity_id: sensor.bedroom_alarms
      offset: "-00:10:00"
actions:
  - action: light.turn_on
    target:
      entity_id: light.bedroom
```

A negative offset runs the automation before the alarm. Avoid a positive offset to run it after the alarm: if you stop the alarm and the integration notices before the offset has passed, the sensor moves on to the next alarm, and Home Assistant [cancels the trigger](https://www.home-assistant.io/triggers/time/#good-to-know). Instead, trigger at the alarm time and add a delay:

```yaml
alias: Coffee after the alarm
triggers:
  - trigger: time
    at: sensor.bedroom_alarms
actions:
  - delay: "00:10:00"
  - action: switch.turn_on
    target:
      entity_id: switch.coffee_machine
```

## When an alarm goes off

Open the bedroom blinds at the alarm's reported due time, without waiting for the integration to observe ringing:

```yaml
alias: Open the blinds with the alarm
triggers:
  - trigger: time
    at: sensor.bedroom_alarms
actions:
  - action: cover.open_cover
    target:
      entity_id: cover.bedroom_blinds
```

## React to observed alarm and timer events

For precise timing at a known due time, keep using the sensor's **time trigger**, as in [When an alarm goes off](#when-an-alarm-goes-off) and [When a timer finishes](#when-a-timer-finishes). Events react to what a poll observes, so they are less precise for starting an automation at that scheduled time.

Use **Event received** to react to ringing, snoozing or stopping that the integration sees, including an item that isn't the speaker's next alarm or timer. In the automation editor, add a trigger, select an entity, device, area or label under **By target**, choose **Event received**, then select the event types:

- **Alarm events:** `ringing`, `snoozed` or `stopped`.
- **Timer events:** `ringing` or `stopped`. A timer returning from ringing to set produces `stopped`; it has no separate snoozed status.

Each detected transition produces its own event. If several items change at the same update, use an automation mode such as `queued` or `parallel` so its actions can handle each event. You can read that event's ID, label and time, and a timer's length or an alarm's repeat days, from `trigger.to_state.attributes`; see [Alarm and timer events](entities.md#alarm-and-timer-events). The entity itself shows only the latest event.

### What these events mean

The integration compares the IDs and statuses reported by successful updates:

- `ringing`: a reported item ID is newly seen ringing.
- `snoozed`: an alarm ID is newly seen snoozed. A change from ringing to snoozed under the same ID produces only snoozed.
- `stopped`: ringing tracked under an ID ended, including when the item disappears or a recurring alarm returns to set. It does not prove that someone dismissed it. If the speaker changes an item's ID, the old ID can produce stopped while the new one produces ringing or snoozed, even if the physical sound continues. Events do not identify an alarm across different IDs.

Events can be delayed until the next successful update, and a complete ring between updates can be missed; see [How quickly ringing shows](#how-quickly-ringing-shows). Nothing is inferred from a due time alone. The first successful update after startup, reload, a failed update or a device returning establishes a baseline and produces no events. Missing data, unrecognized item statuses and unavailable devices produce no events either. With [polling off](configuration.md#turn-off-polling), events depend on updates you request yourself.

Existing next-item attribute triggers follow only the next item. More elaborate templates can compare the sensors' full lists; event entities provide type and target selection without you maintaining that comparison.

## When an alarm stops ringing

Turn on the kitchen lights when the integration observes the end of ringing under an alarm ID on the bedroom speaker:

```yaml
alias: Kitchen lights after the alarm
triggers:
  - trigger: event.received
    target:
      entity_id: event.bedroom_alarm_events
    options:
      event_type:
        - stopped
actions:
  - action: light.turn_on
    target:
      entity_id: light.kitchen
mode: queued
```

This covers each observed alarm ID, even when another alarm becomes the next one. It follows the [event meanings and limits](#what-these-events-mean) above. To react to snoozing instead, select `snoozed`. To react to a timer ending its ringing interval, target `event.bedroom_timer_events` with `stopped`.

## When a timer finishes

Send a notification to your phone at the kitchen timer's reported due time. This time trigger is scheduled beforehand, giving more precise timing than waiting for a `ringing` event. Replace `notify.mobile_app_your_phone` with the notify action of your phone, which you can find in [**Settings** > **Tools** > **Actions**](https://my.home-assistant.io/redirect/tools_actions/):

```yaml
alias: Kitchen timer finished
triggers:
  - trigger: time
    at: sensor.kitchen_timers
actions:
  - action: notify.mobile_app_your_phone
    data:
      message: The kitchen timer has finished.
```

To be told about every timer that rings, including one that isn't next, with its label and length, use the timer events instead. The notification comes once a check sees the timer ringing, usually a few seconds later; see [How quickly ringing shows](#how-quickly-ringing-shows):

```yaml
alias: Kitchen timers ringing
triggers:
  - trigger: event.received
    target:
      entity_id: event.kitchen_timer_events
    options:
      event_type:
        - ringing
actions:
  - action: notify.mobile_app_your_phone
    data:
      message: >
        {{ trigger.to_state.attributes.label or 'A timer' }} set for
        {{ trigger.to_state.attributes.duration }} is ringing on the kitchen speaker.
mode: queued
```

For a 10-minute timer named Pasta, the message is "Pasta set for 0:10:00 is ringing on the kitchen speaker."

## When a timer starts

Send a notification to your phone when a timer is set on the kitchen speaker, using your phone's notify action as in [When a timer finishes](#when-a-timer-finishes):

```yaml
alias: Kitchen timer set
triggers:
  - trigger: state
    entity_id: sensor.kitchen_timers
    attribute: timers
conditions:
  - condition: template
    value_template: >
      {% set old = trigger.from_state.attributes.timers | default(none) if trigger.from_state else none %}
      {% set new = trigger.to_state.attributes.timers | default(none) if trigger.to_state else none %}
      {{ old is list and new is list and new | map(attribute='timer_id')
         | reject('in', old | map(attribute='timer_id') | list) | list | count > 0 }}
actions:
  - action: notify.mobile_app_your_phone
    data:
      message: A timer was set on the kitchen speaker.
```

It runs when the integration next [checks your devices](configuration.md#change-the-update-interval), every 15 seconds by default, and finds a timer that it didn't see at the previous check:

- It runs even while other timers are running, paused or ringing. Several new timers found at the same check send one notification.
- A timer that's gone by the next check, such as a short one you've already stopped or cancelled, doesn't run it. Neither do the timers the integration finds when it starts, such as after a restart of Home Assistant, or when the speaker's entities become available again after being [unavailable](entities.md#when-entities-are-unavailable).
- Pausing, resuming or snoozing a timer runs it only if the speaker gives the timer a new `timer_id`.

## When the trigger runs

A time trigger follows the time that the integration last saw. The integration [checks your devices](configuration.md#change-the-update-interval) every 15 seconds by default, so:

- An alarm or timer that the integration has seen triggers on time, even between checks. One that goes off before the integration sees it, which can happen to a timer shorter than the update interval, doesn't trigger anything.
- If you pause, cancel or change an alarm or timer, the automation follows the change only after the next check, so it can still run at the old time if that comes first.
- Inactive and missed alarms, paused timers, and alarms or timers with an [unknown status](entities.md#alarm-and-timer-status) don't trigger anything. A timer you resume triggers at its new end time, once the integration has seen it.
- To react to an observed status change for any item, use [alarm and timer events](#react-to-observed-alarm-and-timer-events). You can also trigger on the `next_alarm_status` or `next_timer_status` attribute, which follows only the next item. The integration checks the speaker more often around that time; see [How quickly ringing shows](#how-quickly-ringing-shows).

## How quickly ringing shows

Around an alarm's or timer's time, the integration checks that speaker more often than the [update interval](configuration.md#change-the-update-interval):

- About 1 second after its time, or at a regular check that comes sooner. This also applies when a snoozed alarm is due again.
- While it isn't ringing yet, every 5 seconds, until about 30 seconds after its time.
- While it rings, every 10 seconds, until about 65 minutes after its time. With an update interval of 10 seconds or less, the regular checks already come this often.

A change shows once the check that sees it has finished, which takes longer if the speaker is slow to answer. So `ringing` usually shows within a few seconds of the alarm's or timer's time, and its end within about 10 seconds of when you stop or snooze it.

This works only for an alarm or timer that the integration saw before its time, on a speaker that keeps answering:

- An alarm or timer that goes off before the integration has seen it, such as one that you set after the last regular check, shows at the next regular check. So does a ring that the speaker reports more than about 30 seconds late. If it still rings then, the checks every 10 seconds start.
- A ring that starts and stops between two checks doesn't show, for example if you stop the alarm within a few seconds.
- If the speaker doesn't answer a check, or answers without its alarms and timers, the integration checks it at the update interval until it answers again. An extra check that the speaker doesn't answer counts toward the [5 unanswered updates](entities.md#when-entities-are-unavailable) after which its entities become unavailable.
- If a ring lasts more than 65 minutes, its end shows at the update interval.
- If you turned off polling for the integration in its system options, it makes no extra checks either.

## Hear the timers set on other speakers

A speaker knows only its own timers, so another speaker can't tell you how long is left on them. Home Assistant can't copy or move a timer to another speaker either: the local API that the integration uses can only [read and delete timers](actions.md). But the [timers sensors](entities.md#timers-sensor) show the timers of every speaker, so a script can announce them all on a speaker you choose.

To add the script, go to **Settings** > **Automations & scenes** > **Scripts** > **Create script** > **Create new script**, open the **⋮** menu, select **Edit in YAML**, and paste:

```yaml
alias: Running timers
sequence:
  - variables:
      message: >
        {% set ns = namespace(timers=[]) %}
        {% for sensor in states.sensor
             | selectattr('entity_id', 'in', integration_entities('google_home'))
             | selectattr('attributes.timers', 'defined') %}
          {% for timer in sensor.attributes.timers
               | selectattr('status', 'eq', 'set')
               | selectattr('fire_time', 'gt', now().timestamp()) %}
            {% set ns.timers = ns.timers + [(timer.label or 'Timer') ~ ' on '
              ~ device_name(sensor.entity_id) ~ ': '
              ~ time_until(as_datetime(timer.fire_time), 2) ~ ' left'] %}
          {% endfor %}
        {% endfor %}
        {{ ns.timers | join('. ') if ns.timers else 'No timers are running.' }}
  - action: tts.speak
    target:
      entity_id: tts.google_translate_en_com
    data:
      media_player_entity_id: media_player.living_room
      message: "{{ message }}"
```

Replace `media_player.living_room` with the Google Cast media player of the speaker that should answer, and `tts.google_translate_en_com` with your text-to-speech entity; see [Speak a message](other-integrations.md#other-integrations-for-the-same-devices). When you run the script, for example from a dashboard button, the speaker reads out each running timer and the speaker it's set on, by its name in Home Assistant, such as "Pasta on Kitchen: 40 minutes 12 seconds left". With no running timers, it says "No timers are running." The announcement plays at the speaker's current media volume, so it's easy to miss if that volume is low.

To get the message on your phone instead, replace the `tts.speak` step with this one, using your phone's notify action as in [When a timer finishes](#when-a-timer-finishes):

```yaml
  - action: notify.mobile_app_your_phone
    data:
      message: "{{ message }}"
```

The script works out the time left when you run it, from the timers that the integration last saw. A timer you set, change or cancel shows only after the integration next [checks your devices](configuration.md#change-the-update-interval), every 15 seconds by default. Paused and ringing timers are left out, and so is a speaker whose entities are [unavailable](entities.md#when-entities-are-unavailable), such as one that's offline. The time left is in English, as Home Assistant's `time_until` writes it.

## Set the alarm volume on several speakers

The `number.set_value` action sets the [alarm volume](entities.md#alarm-volume) of all the speakers you list at once. Set the alarm volume of the bedroom and kitchen speakers to 30% every evening at 21:00:

```yaml
alias: Alarm volume at bedtime
triggers:
  - trigger: time
    at: "21:00:00"
actions:
  - action: number.set_value
    target:
      entity_id:
        - number.bedroom_alarm_volume
        - number.kitchen_alarm_volume
    data:
      value: 30
```

If the request to a speaker fails, for example because it has just gone offline, the others still change, but the error stops the automation at this step; see [If a setting or reboot fails](entities.md#if-a-setting-or-reboot-fails).

## Control alarms with a spoken command (unsupported)

Neither this integration nor Google supports this. It has been seen working, but it may stop working at any time.

The integration has [no actions](actions.md) to set or snooze alarms, and the [Google Assistant SDK integration](other-integrations.md#other-integrations-for-the-same-devices) can't do it either. Instead, a script can play a spoken command on one speaker, starting with "Hey Google", so that another Google device nearby hears it and acts on it as if you'd said it. This has been seen setting an alarm, and snoozing and stopping a ringing one.

```yaml
alias: Set an alarm by voice
sequence:
  - action: tts.speak
    target:
      entity_id: tts.google_translate_en_com
    data:
      media_player_entity_id: media_player.living_room
      message: "Hey Google, set an alarm for 7 AM"
```

Add it as in [Hear the timers set on other speakers](#hear-the-timers-set-on-other-speakers). Replace `tts.google_translate_en_com` with your text-to-speech entity, and `media_player.living_room` with the media player of a different speaker near the Google device you want to set the alarm on, or near the one whose alarm is ringing. Don't play it on that device itself. For a ringing alarm, use a message such as "Hey Google, snooze" or "Hey Google, stop".

Before you rely on it:

- It needs a second Google device within earshot: the speaker that plays the command hasn't been seen acting on it. Everyone nearby hears the command too.
- Whether a device hears it depends on the volume and where the devices are. If several Google devices hear it, Google picks one to answer, and Voice Match may send the command to a different device than you expect. When it has worked, the alarm was set, snoozed or stopped on the device that acted on the command.
- Each command takes about 5 to 10 seconds to take effect.
- The integration doesn't send or check the command. To see which device acted and whether it worked, check the [alarms sensors](entities.md#alarms-sensor) of your devices. A new alarm shows after the next [update](configuration.md#change-the-update-interval), or straight away when you run [Refresh devices](actions.md#refresh-devices) once the command has taken effect. A snoozed or stopped alarm usually shows within about 10 seconds; see [How quickly ringing shows](#how-quickly-ringing-shows).

# Automation examples

The [alarms and timers sensors](entities.md) show the time of the next alarm or timer. Home Assistant's [time trigger](https://www.home-assistant.io/docs/automation/trigger/#time-trigger) can start an automation at that time, or a set time before or after it.

To use an example, go to **Settings** > **Automations & scenes** > **Create automation** > **Create new automation**, open the **⋮** menu, select **Edit in YAML**, and paste it. Replace the entity IDs with your own.

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

Open the bedroom blinds when the alarm goes off:

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

## When a timer finishes

Send a notification to your phone when the kitchen timer finishes. Replace `notify.mobile_app_your_phone` with the notify action of your phone, which you can find in [**Settings** > **Tools** > **Actions**](https://my.home-assistant.io/redirect/tools_actions/):

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

## When the trigger runs

The trigger follows the time that the integration last saw. The integration [checks your devices](configuration.md#change-the-update-interval) every 15 seconds by default, so:

- An alarm or timer that the integration has seen triggers on time, even between checks. One that goes off before the integration sees it, which can happen to a timer shorter than the update interval, doesn't trigger anything.
- If you pause, cancel or change an alarm or timer, the automation follows the change only after the next check, so it can still run at the old time if that comes first.
- Inactive and missed alarms and paused timers don't trigger anything. A timer you resume triggers at its new end time, once the integration has seen it.
- You can also trigger on the `next_alarm_status` or `next_timer_status` attribute changing to `ringing`, or from `ringing` when you stop or snooze it. The integration checks the speaker more often around that time; see [How quickly ringing shows](#how-quickly-ringing-shows).

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

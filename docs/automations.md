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

Send a notification to your phone when the kitchen timer finishes. Replace `notify.mobile_app_your_phone` with the notify action of your phone, which you can find in [**Developer tools** > **Actions**](https://my.home-assistant.io/redirect/developer_services/):

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

The trigger follows the time that the integration last saw. The integration [checks your devices](installation.md#change-the-update-interval) every 180 seconds, so:

- An alarm or timer that the integration has seen triggers on time, even between checks. One that goes off before the integration sees it, such as a one-minute timer, doesn't trigger anything.
- If you pause, cancel or change an alarm or timer, the automation follows the change only after the next check, so it can still run at the old time if that comes first.
- Inactive and missed alarms and paused timers don't trigger anything. A timer you resume triggers at its new end time, once the integration has seen it.
- You can also trigger on the `next_alarm_status` or `next_timer_status` attribute changing to `ringing`, but that trigger runs only at the next check, up to 180 seconds late, and it misses an alarm or timer that you stop before the next check.

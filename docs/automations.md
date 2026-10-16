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

A negative offset runs the automation before the alarm, a positive one after it.

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

## What the trigger can't see

- The integration [checks your devices](installation.md#change-the-update-interval) every 180 seconds. An alarm or timer that goes off before the next check, such as a one-minute timer, doesn't trigger anything.
- Inactive and missed alarms and paused timers don't trigger anything. A timer you resume triggers at its new end time.
- You can also trigger on the `next_alarm_status` or `next_timer_status` attribute changing to `ringing`, but because of the 180-second checks, that trigger can run up to 3 minutes late, and it misses an alarm or timer that you stop before the next check.

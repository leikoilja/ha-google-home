# Google Home for Home Assistant

[![Home Assistant quality scale: Platinum][quality-scale-badge]](#quality-scale)

This custom integration brings your Google Home and Nest speakers and displays into Home Assistant. You can:

- See every alarm and timer set on each device, and use them in automations.
- Delete alarms and timers.
- Turn Do Not Disturb on or off.
- Change the alarm volume.
- Reboot a device.
- See each device's firmware version and whether it says a firmware update is waiting.
- See each device's Wi-Fi network and signal strength, once you [enable the Wi-Fi sensors](entities.md#wi-fi-sensors).
- Tell whether your phone or another Bluetooth device is home, with [Bluetooth tracking](bluetooth.md).

To start, follow **[Getting Started](installation.md)** to install the integration and sign in.

## What you can automate

The alarms and timers sensors show the time of the next alarm or timer, so an automation can start at that time or a set time before it. The timers sensors also list each timer, so a script can read out the running ones. For example, you can:

- [Turn on the bedroom lights 10 minutes before the next alarm](automations.md#before-the-next-alarm).
- [Open the bedroom blinds when the alarm goes off](automations.md#when-an-alarm-goes-off).
- [Send a notification to your phone when the kitchen timer finishes](automations.md#when-a-timer-finishes).
- [Have one speaker read out the timers running on all your speakers when you run a script](automations.md#hear-the-timers-set-on-other-speakers).

[Automation examples](automations.md) has the YAML for each one. The full list of what the integration adds is on the [Entities](entities.md) and [Actions](actions.md) pages.

## What it can't do

It can't create, change or snooze alarms and timers, or turn alarms on or off. Set them by voice or on a display's screen, and the integration picks them up.

It doesn't play media, change the media volume, speak messages or send Assistant commands. The media volume is separate from the [alarm volume](entities.md#alarm-volume). Home Assistant's own integrations, such as Google Cast and the Google Assistant SDK, do these alongside this one; see [Other integrations](other-integrations.md#other-integrations-for-the-same-devices).
{ #other-integrations-for-the-same-devices }

It doesn't add the other devices in your Google Home app, such as lights, plugs, thermostats or cameras. See [Other Google Home devices](other-integrations.md#other-google-home-devices) for how to add them to Home Assistant.
{ #other-google-home-devices }

## What you need { #get-started }

- A Google account that is a member of the home your devices belong to in the Google Home app.
- Home Assistant on the same local network as your devices, so it finds them automatically. For devices on another network, see [Add devices on another network](configuration.md#add-devices-on-another-network).

[Before you start](installation.md#before-you-start) has the full list, including the minimum Home Assistant version. If something doesn't work, check [Troubleshooting](troubleshooting.md) or [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose).

## How it works

The integration uses your Google account to get access tokens for your devices from Google, and renews them regularly. Everything else, such as reading alarms or changing the alarm volume, goes directly to the devices over your local network.

You can add the integration only once, so it works with one Google account. To use devices from several homes, [invite that account](https://support.google.com/googlenest/answer/9155535) to each home: the integration adds the devices of every home the account is a member of, unless you [choose homes](configuration.md#choose-homes). Devices that Home Assistant can't reach, for example in a home at another address, are added with only a device sensor, a reboot button, an update sensor and two Wi-Fi sensors that are disabled by default, and all of them are unavailable.

## Quality scale

Home Assistant's [integration quality scale](https://www.home-assistant.io/docs/quality_scale/) grades integrations on user experience, features and code quality, in tiers from Bronze to Platinum. This integration follows every rule up to Platinum, the highest tier. Home Assistant shows tiers only for its built-in integrations, so **Settings** > **Devices & services** > **Google Home** shows **Custom integration** instead. [`quality_scale.yaml`](https://github.com/leikoilja/ha-google-home/blob/master/custom_components/google_home/quality_scale.yaml) lists each rule, and why the few that don't apply are exempt.

## Languages

The integration's setup screens, options, entity names and action descriptions follow your Home Assistant language. Text that isn't translated yet is shown in English. To add or fix a translation, see [Translate the integration](contributing.md#translate-the-integration).

[quality-scale-badge]: https://img.shields.io/badge/quality%20scale-%F0%9F%8F%86%20platinum-e5e4e2.svg?style=for-the-badge

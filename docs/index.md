# Google Home for Home Assistant

This custom integration brings your Google Home and Nest speakers and displays into Home Assistant. You can:

- See every alarm and timer set on each device, and use them in automations.
- Delete alarms and timers.
- Turn Do Not Disturb on or off.
- Change the alarm volume.
- Reboot a device.

To start, follow **[Getting Started](installation.md)** to install the integration and sign in.

## What you can automate

The alarms and timers sensors show the time of the next alarm or timer, so an automation can start at that time or a set time before it. For example, you can:

- [Turn on the bedroom lights 10 minutes before the next alarm](automations.md#before-the-next-alarm).
- [Open the bedroom blinds when the alarm goes off](automations.md#when-an-alarm-goes-off).
- [Send a notification to your phone when the kitchen timer finishes](automations.md#when-a-timer-finishes).

[Automation examples](automations.md) has the YAML for each one. The full list of what the integration adds is on the [Entities](entities.md) and [Actions](actions.md) pages.

## What it can't do

It can't create, change or snooze alarms and timers, or turn alarms on or off. Set them by voice or on a display's screen, and the integration picks them up.

### Other integrations for the same devices

Home Assistant's own integrations work alongside this one. Use [Google Cast](https://www.home-assistant.io/integrations/cast/) to play media and change the media volume, which is separate from the [alarm volume](entities.md#alarm-volume). Use the [Speak](https://www.home-assistant.io/actions/tts.speak/) action to play a spoken message on the Google Cast media player, and the [Google Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) for Assistant commands and broadcasts; it can't set alarms or timers either. See [Other integrations](other-integrations.md#other-integrations-for-the-same-devices) for how to use them.

### Other Google Home devices

The integration doesn't add the other devices in your Google Home app, such as lights, plugs, thermostats or cameras. See [Other Google Home devices](other-integrations.md#other-google-home-devices) for how to add them to Home Assistant.

## What you need { #get-started }

- A Google account that is a member of the home your devices belong to in the Google Home app.
- Home Assistant on the same local network as your devices, so it finds them automatically. For devices on another network, see [Add devices on another network](installation.md#add-devices-on-another-network).

These are the main requirements; [Before you start](installation.md#before-you-start) has the full list, including the minimum Home Assistant version. Then follow [Getting Started](installation.md) to install the integration and sign in. If something doesn't work, check [Troubleshooting](troubleshooting.md).

## How it works

The integration uses your Google account to get access tokens for your devices from Google, and renews them regularly. Everything else, such as reading alarms or changing the alarm volume, goes directly to the devices over your local network.

You can add the integration only once, so it works with one Google account. To use devices from several homes, [invite that account](https://support.google.com/googlenest/answer/9155535) to each home: the integration adds the devices of every home the account is a member of. Devices that Home Assistant can't find on its network, for example in a home at another address, have only a device sensor and a reboot button, and both are unavailable.

## Languages

The integration's setup screens, options and action descriptions follow your Home Assistant language. Text that isn't translated yet is shown in English. To add or fix a translation, see [Translate the integration](contributing.md#translate-the-integration).

## Contributing

Ask questions in [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions), and report bugs or suggest features in [issues](https://github.com/leikoilja/ha-google-home/issues/new/choose). To translate the integration or change its code, see [Contributing](contributing.md).

# Google Home for Home Assistant

This custom integration brings your Google Home and Nest speakers and displays into Home Assistant. You can:

- See every alarm and timer set on each device, and use them in automations.
- Delete alarms and timers.
- Turn Do Not Disturb on or off.
- Change the alarm volume.
- Reboot a device.

The full list is on the [Entities](entities.md) and [Actions](actions.md) pages.

## How it works

The integration uses your Google account to get access tokens for your devices from Google, and renews them regularly. Everything else, such as reading alarms or changing the alarm volume, goes directly to the devices over your local network. For this to work:

- Home Assistant and your devices must be on the same network. See [Device offline or not compatible](troubleshooting.md#device-offline-or-not-compatible).
- The Google account you use must be a member of the home your devices belong to in the Google Home app.
- You can add the integration only once, so it works with one Google account.

The integration started from a [community discussion][community-discussion] about reading Google Home alarms and timers in Home Assistant.

## Get started

1. [Install the integration and sign in](installation.md).
2. Look up which [entities](entities.md) you get for each device.
3. If something doesn't work, check [Troubleshooting](troubleshooting.md).

## Languages

The integration's setup screens, options and action descriptions are translated into:

- Catalan
- Danish
- Dutch
- English
- French
- German
- Greek
- Italian
- Norwegian (bokmål and nynorsk)
- Polish
- Portuguese (Brazil)
- Portuguese (Portugal)
- Russian
- Slovak
- Spanish
- Ukrainian

To add your language, follow the [Localization guide](https://github.com/leikoilja/ha-google-home/blob/master/LOCALIZATION.md).

## Contributing

To report a bug or suggest a feature, [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose). To contribute code, read the [Contribution guidelines](https://github.com/leikoilja/ha-google-home/blob/master/CONTRIBUTING.md).

[community-discussion]: https://community.home-assistant.io/t/solution-to-track-your-google-home-alarms-and-timers-and-trigger-different-home-assistant-events/61534/74

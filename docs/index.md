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

## Get started

1. [Install the integration and sign in](installation.md).
2. Look up which [entities](entities.md) you get for each device.
3. If something doesn't work, check [Troubleshooting](troubleshooting.md).

## Languages

The integration's setup screens, options and action descriptions follow your Home Assistant language. Text that isn't translated yet is shown in English. To add or fix a translation, see [Translate the integration](contributing.md#translate-the-integration).

## Contributing

Ask questions in [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions), and report bugs or suggest features in [issues](https://github.com/leikoilja/ha-google-home/issues/new/choose). To translate the integration or change its code, see [Contributing](contributing.md).

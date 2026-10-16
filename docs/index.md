# Google Home for Home Assistant

This custom integration brings your Google Home and Nest speakers and displays into Home Assistant. You can:

- See every alarm and timer set on each device, and use them in automations.
- Delete alarms and timers.
- Turn Do Not Disturb on or off.
- Change the alarm volume.
- Reboot a device.

The full list is on the [Entities](entities.md) and [Actions](actions.md) pages, and [Automation examples](automations.md) shows how to use them.

It can't create, change or snooze alarms and timers. Set them by voice or on a display's screen, and the integration picks them up. It doesn't play media either; for that, use the [Google Cast integration](https://www.home-assistant.io/integrations/cast/).

!!! note "Only for Google speakers and displays"

    The integration doesn't add the other devices in your Google Home app, such as lights, plugs, thermostats or cameras. See [Other Google Home devices](#other-google-home-devices) for how to add them to Home Assistant.

## How it works

The integration uses your Google account to get access tokens for your devices from Google, and renews them regularly. Everything else, such as reading alarms or changing the alarm volume, goes directly to the devices over your local network. For this to work:

- Home Assistant must be able to reach your devices. It finds them automatically on the same network; for devices on another network, see [Add devices on another network](installation.md#add-devices-on-another-network).
- The Google account you use must be a member of the home your devices belong to in the Google Home app.
- You can add the integration only once, so it works with one Google account.

## Other Google Home devices

The Google Home app lists every device you've linked to it, including lights, plugs and thermostats from other brands. This integration doesn't read that list. It works only with Google Cast devices, which it talks to directly over your network. To bring your other devices into Home Assistant:

- **Most devices:** add them with their own integration. Go to **Settings** > **Devices & services** > **Add integration** and search for the brand.
- **Matter devices:** share them from Google Home, so they work in both. In the Home Assistant app on your phone, go to **Settings** > **Connectivity** > **Matter** > **Add device**, select **Yes. It's already in use.**, and choose **Google Home**. See the [Matter integration](https://www.home-assistant.io/integrations/matter/) for what you need.
- **Nest thermostats, cameras and doorbells:** use the [Google Nest integration](https://www.home-assistant.io/integrations/nest/). It needs Google's Device Access, which has a one-time, non-refundable US$5 registration fee. Nest smoke and CO alarms aren't supported.
- **Media on your speakers, displays and Chromecasts:** use the [Google Cast integration](https://www.home-assistant.io/integrations/cast/), which comes with Home Assistant.

The [Google Assistant integration](https://www.home-assistant.io/integrations/google_assistant/) works the other way round: it lets Google Assistant control your Home Assistant devices.

## Get started

1. [Install the integration and sign in](installation.md).
2. Look up which [entities](entities.md) you get for each device.
3. If something doesn't work, check [Troubleshooting](troubleshooting.md).

## Languages

The integration's setup screens, options and action descriptions follow your Home Assistant language. Text that isn't translated yet is shown in English. To add or fix a translation, see [Translate the integration](contributing.md#translate-the-integration).

## Contributing

Ask questions in [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions), and report bugs or suggest features in [issues](https://github.com/leikoilja/ha-google-home/issues/new/choose). To translate the integration or change its code, see [Contributing](contributing.md).

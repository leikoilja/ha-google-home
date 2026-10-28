# Other integrations

This integration handles the alarms, timers, Do Not Disturb, alarm volume and reboots of your Google speakers and displays. This page lists what to use for media, spoken messages, Google Assistant commands and the other devices in your Google Home app.

## Other integrations for the same devices

Integrations that come with Home Assistant do more with your speakers and displays. You can use them alongside this one:

- **Play music, radio and other media:** use the [Google Cast integration](https://www.home-assistant.io/integrations/cast/). It adds a media player for each speaker, display and Chromecast.
- **Change or mute the media volume:** use the [Set media player volume](https://www.home-assistant.io/actions/media_player.volume_set/) and [Mute/unmute media player](https://www.home-assistant.io/actions/media_player.volume_mute/) actions on the Google Cast media player. This volume is separate from the [alarm volume](entities.md#alarm-volume). While nothing is casting to a device, its media player shows as **Off**, without a volume control or a `volume_level` attribute, but the Set media player volume action still changes the volume.
- **Speak a message:** use the [Speak](https://www.home-assistant.io/actions/tts.speak/) action with a text-to-speech entity, such as one from [Google Translate text-to-speech](https://www.home-assistant.io/integrations/google_translate/), to play the message on the Google Cast media player. If nothing plays, see [Troubleshooting](https://www.home-assistant.io/integrations/tts/#troubleshooting) in the text-to-speech docs.
- **Send Google Assistant commands and broadcasts:** use the [Google Assistant SDK integration](https://www.home-assistant.io/integrations/google_assistant_sdk/). Its [Send text command](https://www.home-assistant.io/actions/google_assistant_sdk.send_text_command/) action works as if you'd said the command, and [`notify.google_assistant_sdk`](https://www.home-assistant.io/integrations/google_assistant_sdk/#broadcast-message) broadcasts a message to your speakers and displays. You set it up with your own Google Cloud credentials. It can't set alarms or timers (see [Actions](actions.md)), and some other commands, such as routines, don't work either; see its [known issues](https://www.home-assistant.io/integrations/google_assistant_sdk/#limitationsknown-issues).

## Other Google Home devices

The Google Home app lists every device you've linked to it, including lights, plugs and thermostats from other brands. This integration doesn't read that list. It works only with Google Cast devices, which it talks to directly over your network. To bring your other devices into Home Assistant:

- **Most devices:** add them with the integration for their brand or platform, such as [Philips Hue](https://www.home-assistant.io/integrations/hue/) for bulbs on a Hue Bridge, [Philips Hue BLE](https://www.home-assistant.io/integrations/hue_ble/) for Bluetooth bulbs without one, or [Tuya](https://www.home-assistant.io/integrations/tuya/) for devices in the Smart Life app. Go to **Settings** > **Devices & services** > **Add integration** and search for the brand or platform.
- **Matter devices:** share them from Google Home, so they work in both. In the Home Assistant app on your phone, go to **Settings** > **Connectivity** > **Matter** > **Add device**, select **Yes. It's already in use.**, and choose **Google Home**. See the [Matter integration](https://www.home-assistant.io/integrations/matter/) for what you need.
- **Nest thermostats, cameras and doorbells:** use the [Google Nest integration](https://www.home-assistant.io/integrations/nest/). It needs Google's Device Access, which has a one-time, non-refundable US$5 registration fee. Nest smoke and CO alarms aren't supported.

The [Google Assistant integration](https://www.home-assistant.io/integrations/google_assistant/) works the other way round: it lets Google Assistant control your Home Assistant devices.

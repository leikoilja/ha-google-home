# Bluetooth tracking

Your Google speakers can tell Home Assistant whether your phone, or another Bluetooth device, is home. The speakers scan for nearby Bluetooth devices, and each device you track gets a tracker entity that shows `home` or `not_home`.

Bluetooth tracking is off until you turn it on. While it's off, the integration sends no Bluetooth requests to your speakers.

It tells home from away, not which room you're in. Bluetooth signal strength changes a lot even when a phone doesn't move, so the integration doesn't use it to place you in a room.

## Turn on Bluetooth tracking

1. Go to **Settings** > **Devices & services** > **Google Home** and select **Configure**.
2. Under **Bluetooth**, turn on **Bluetooth tracking** and select **Submit**.
3. On the same page, select **Add Bluetooth device** for each device you want to track. See [Add a device to track](#add-a-device-to-track).

The speakers start scanning once you've added the first device, and stop when you remove the last one.

If you turn Bluetooth tracking off again, the devices you added stay, and their trackers show `unavailable` until you turn it back on. To stop tracking a device for good, delete it as described in [Add a device to track](#add-a-device-to-track).

## Add a device to track

Give the device a name, such as _Alex's phone_, and under **IRK or MAC address** enter one of these. The integration tells them apart by their format:

- **IRK** (Identity Resolving Key): use this for phones. Phones change their Bluetooth address every few minutes, and the IRK lets the integration recognize every address the phone uses. To find the IRK of your phone, follow [Getting your Identity Resolving Key](https://www.home-assistant.io/integrations/private_ble_device/#getting-your-identity-resolving-key-irk) in the Private BLE Device documentation. You can paste it as 32 hex digits or in base64, as you find it there.
- **MAC address**: use this for devices whose address never changes, such as some watches, tags and headphones, in the form `AA:BB:CC:DD:EE:FF` or `AA-BB-CC-DD-EE-FF`. A phone's MAC address stops matching within minutes.

The tracker is named after the device, such as `device_tracker.alexs_phone`. Home Assistant lists it under **Diagnostic** on the device's page, as it does for its own Bluetooth trackers.

Once you track a device, the **Google Home** page lists each tracked device on its own, and your speakers and displays under **Devices that don't belong to a sub-entry**. That's how Home Assistant shows every integration with sub-entries: your speakers and displays are still there.

To stop tracking a device, delete it: open it on the **Google Home** page, open the **⋮** menu and select **Delete**. Deleting it from its device page does the same. To change its name, IRK or MAC address, delete it and add it again.

## How the tracker works

Every 30 seconds, each speaker reports what it heard since the last check and starts a new scan. Bluetooth devices that are weaker than -80 dBm are ignored, so a phone heard faintly from outside doesn't count.

| State         | When                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `home`        | A speaker heard the device in the last 90 seconds.                                                                                          |
| `not_home`    | Every speaker has scanned without a break for the last 90 seconds, and none heard the device.                                               |
| `unknown`     | Right after Home Assistant starts or the integration reloads, until the speakers have scanned long enough to tell. This takes 30-90 seconds. |
| `unavailable` | A speaker has stopped answering for 5 minutes, so the integration can't tell whether the device is gone. See [Tracker is unavailable](#tracker-is-unavailable). Also while Bluetooth tracking is off. |

So a phone shows `home` within 60 seconds of arriving, and `not_home` 60 to 90 seconds after it leaves.

Starting as `unknown` after a restart keeps automations from seeing you leave and come back each time Home Assistant restarts.

## Tracker is unavailable

A tracker shows `not_home` only when every speaker has answered for the last 90 seconds. That includes every speaker that has returned scan results since the integration last loaded, as long as Google lists it. If one of them stops answering, it might be the one that hears you, so the integration can't tell whether you left.

While it can't tell, the tracker keeps its last state for 5 minutes, so a speaker that misses a scan or comes online doesn't make it flap. If you arrive in that time and only the silent speaker can hear you, `home` waits until another speaker hears you. After 5 minutes the tracker shows `unavailable`, and the integration logs a warning that names the speaker.

If that speaker is unplugged or out of service, tell the integration not to use it:

1. Go to **Settings** > **Devices & services** > **Google Home** and select **Configure**.
2. Under **Speakers not used for Bluetooth tracking**, select the speaker, then select **Submit**.

You can't delete a speaker that Google still lists in your home, even when it's offline, so excluding it is the way to stop it from blocking `not_home`.

A silent speaker also stops blocking `not_home` once Google no longer lists it, for example after you remove it from the Google Home app. Reloading the integration (**Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**) or restarting Home Assistant has the same effect until the speaker answers again.

Devices that don't support Bluetooth scans, such as a Chromecast Audio or an Android TV, are left out automatically. So is any device that hasn't returned scan results since the integration last loaded, for example because it was offline.

## Privacy

- The IRKs and MAC addresses you enter are stored in Home Assistant's configuration, like the master token. The integration doesn't log them or show them in entity attributes.
- The speakers hear every Bluetooth device nearby, including your neighbors'. The integration keeps only whether your tracked devices were heard. It doesn't store or log other addresses.
- The integration gets the scan results from your speakers over your local network and doesn't send them anywhere.

## Known limitations

- Whether scanning affects audio that a speaker plays over Bluetooth hasn't been tested. If you notice dropouts, turn off Bluetooth tracking or exclude that speaker.
- A speaker that sits near a wall can hear a phone outside, as long as the signal is stronger than -80 dBm. The phone then shows `home` while you're just outside.

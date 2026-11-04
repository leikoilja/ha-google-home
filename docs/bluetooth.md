# Bluetooth tracking

Your Google speakers can tell Home Assistant whether your phone, or another Bluetooth device, is home. The speakers scan for nearby Bluetooth devices, and each device you track gets a tracker entity that shows `home` or `not_home`.

Bluetooth tracking is off until you turn it on. While it's off, the integration sends no Bluetooth requests to your speakers.

It tells home from away, not which room you're in. Bluetooth signal strength changes a lot even when a phone doesn't move, so the integration doesn't use it to place you in a room. Each tracker does show [which speakers hear the device, and how strongly](#see-which-speakers-hear-a-device).

## Turn on Bluetooth tracking

1. Go to **Settings** > **Devices & services** > **Google Home** and select **Configure**.
2. Under **Bluetooth**, turn on **Bluetooth tracking** and select **Submit**.
3. Back on the **Google Home** page, select **Track a Bluetooth device** for each device you want to track. See [Add a device to track](#add-a-device-to-track).

The speakers start scanning once you've added the first device, and stop when you remove the last one.

If you turn Bluetooth tracking off again, the devices you added stay, and their trackers show `unavailable` until you turn it back on. To stop tracking a device for good, delete it as described in [Add a device to track](#add-a-device-to-track).

## Add a device to track

Give the device a name, such as _Alex's phone_, and under **IRK or MAC address** enter one of these. The integration tells them apart by their format:

- **IRK** (Identity Resolving Key): use this for phones. Phones change their Bluetooth address from time to time, and the IRK lets the integration recognize every address the phone uses. To find the IRK of your phone, follow [Getting your Identity Resolving Key](https://www.home-assistant.io/integrations/private_ble_device/#getting-your-identity-resolving-key-irk) in the Private BLE Device documentation. You can paste it as 32 hex digits or in base64, as you find it there.
- **MAC address**: use this for devices whose address never changes, such as some watches, tags and headphones, in the form `AA:BB:CC:DD:EE:FF` or `AA-BB-CC-DD-EE-FF`. A phone's MAC address stops matching once the phone changes it.

The tracker is named after the device, such as `device_tracker.alex_s_phone`. Home Assistant lists it under **Diagnostic** on the device's page, as it does for its own Bluetooth trackers.

Once you track a device, the **Google Home** page lists each tracked device on its own, and your speakers and displays under **Devices that don't belong to a sub-entry**. That's how Home Assistant shows every integration with sub-entries: your speakers and displays are still there.

To stop tracking a device, delete it: open it on the **Google Home** page, open the **⋮** menu and select **Delete**. Deleting it from its device page does the same.

To rename a tracked device, open its device page, select the pencil icon (**Edit settings**), change **Name** and select **Update**. The tracker takes the new name straight away and keeps its entity ID. The **Google Home** page still lists the device under the name you first gave it: to change that too, open its **⋮** menu there and select **Rename**. To change its IRK or MAC address, delete it and add it again.

## How the tracker works

About every 30 seconds, whatever the [update interval](configuration.md#change-the-update-interval), each speaker reports what it heard since the last check and starts a new scan. Bluetooth devices that are weaker than -80 dBm are ignored, so a phone heard faintly from outside doesn't count.

| State         | When                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `home`        | A speaker heard the device in the last 90 seconds.                                                                                          |
| `not_home`    | Every speaker has scanned without a break for the last 90 seconds, and none heard the device.                                               |
| `unknown`     | The speakers haven't confirmed `home` or `not_home` since Home Assistant started or the integration reloaded. This normally takes about 30 to 90 seconds. If it takes longer, see [Tracker doesn't show `home` or stays `unknown`](#tracker-doesnt-show-home-or-stays-unknown). |
| `unavailable` | The tracker showed `home` or `not_home`, but the speakers haven't confirmed either for 5 minutes, for example because a speaker stopped answering. See [Tracker is unavailable](#tracker-is-unavailable). Also while Bluetooth tracking is off. |

In the best case, a phone shows `home` within about a minute of arriving, and `not_home` about 60 to 90 seconds after it leaves.

Starting as `unknown` after a restart keeps automations from seeing you leave and come back each time Home Assistant restarts. While Bluetooth tracking is on, trackers also start as `unknown` again after any reload, such as after you add or delete a tracked device or change an option under **Bluetooth**.

While [polling is turned off](configuration.md#turn-off-polling) in the integration's system options, the speakers don't scan on their own, and [Refresh devices](actions.md#refresh-devices) doesn't make them scan, so trackers usually stay `unknown`.

## See which speakers hear a device

Each tracker has a `speakers` attribute. It lists the speakers that hear the device, by their names in the Google Home app, with the signal strength of each in dBm. Values closer to 0 are stronger, and the strongest speaker comes first:

```yaml
speakers:
  Speaker A: -58
  Speaker B: -74
```

You can see it in [**Settings** > **Tools** > **States**](https://my.home-assistant.io/redirect/tools_states/), or use it in templates, such as `{{ state_attr('device_tracker.example_device', 'speakers') }}`.

Each value is the median of what that speaker heard over 5 minutes. A speaker is listed only if it heard the device in at least two scans in that time, at -80 dBm or stronger: the same readings that count for `home`. The attribute updates every 5 minutes.

The attribute is empty (`{}`):

- While the device is away.
- For the first 5 minutes after the tracker changes to `home`, including after Home Assistant starts.
- After 5 minutes in which no speaker heard the device in two scans, even if the tracker still shows `home`.

Treat the values as a rough guide. In testing, one speaker's readings varied by about 20 dB with a phone lying still. The median smooths this out, but the strongest speaker isn't necessarily the nearest, so don't rely on the attribute to tell which room you're in. It's useful for checking how well your speakers cover the places where you keep the device: a device that only one speaker hears, at close to -80 dBm, can show `not_home` when its signal stays below that for about 90 seconds.

Home Assistant doesn't keep the attribute's values in its history, so only the current value is available.

## Tracker is unavailable

A tracker shows `not_home` only when every speaker has answered for the last 90 seconds. That includes every speaker that has returned scan results since the integration last loaded, as long as Google lists it and you haven't disabled it. If one of them stops answering, it might be the one that hears you, so the integration can't tell whether you left.

While it can't tell, the tracker keeps its last state for 5 minutes from when the speakers last confirmed it, so a speaker that misses a scan or comes online doesn't make it flap. If you arrive in that time and only the silent speaker can hear you, `home` waits until another speaker hears you. After the 5 minutes, the tracker shows `unavailable` until the speakers can tell again.

Once a speaker has kept trackers from showing `not_home` for 5 minutes, the integration logs a warning that names it, such as "Kitchen hasn't answered Bluetooth scans for 5 minutes, so Bluetooth trackers can't show away". The 5 minutes start when the speaker misses a scan, and start over only once it has answered every scan for 90 seconds. So a speaker that answers some scans but misses others gets the warning too. They're the speaker's own 5 minutes, so the warning can come before or after a tracker shows `unavailable`, and also while another speaker hears the device and the tracker shows `home`.

If that speaker is unplugged or out of service, tell the integration not to use it:

1. Go to **Settings** > **Devices & services** > **Google Home** and select **Configure**.
2. Under **Bluetooth**, select the speaker in **Speakers not used for Bluetooth tracking**, then select **Submit**.

You can't delete a speaker that Google still lists in your home, even when it's offline. To stop it from blocking `not_home`, exclude it, or disable it as described below.

A speaker that you [disable in Home Assistant](configuration.md#stop-checking-some-devices) stops scanning until you enable it again, and no longer keeps trackers from showing `not_home`. If no other speaker scans, trackers can't tell whether you're home, as described above.

A silent speaker also stops blocking `not_home` once Google no longer lists it, for example after you remove it from the Google Home app. The integration notices when it next fetches Google's device list: normally within about 20 minutes, or later with a long [update interval](configuration.md#change-the-update-interval) or after a fetch fails. Reloading the integration or restarting Home Assistant stops a silent speaker from blocking `not_home` straight away, until it answers again.

Devices that don't support Bluetooth scans, such as a Chromecast Audio or an Android TV, are left out automatically. So is any device that hasn't returned scan results since the integration last loaded, for example because it was offline.

## Tracker doesn't show `home` or stays `unknown`

A tracker shows `unknown` until the speakers first confirm `home` or `not_home` after Home Assistant starts or the integration reloads. While Bluetooth tracking is on, only a tracker they've confirmed can become `unavailable`. If a speaker stops answering before then, the tracker stays `unknown` until a speaker hears the device or the silent speaker answers again. To stop the silent speaker from blocking it, reload the integration, which leaves the speaker out until it answers, or [exclude or disable it](#tracker-is-unavailable). After 5 minutes, the integration logs the warning described in [Tracker is unavailable](#tracker-is-unavailable).

The speakers can't confirm either state while none of them scans, for example while:

- Every speaker is [excluded](#tracker-is-unavailable) or [disabled](configuration.md#stop-checking-some-devices).
- None of your speakers and displays supports Bluetooth scans.
- Home Assistant [can't reach your speakers](troubleshooting.md#device-offline-or-not-compatible).
- [Polling is turned off](configuration.md#turn-off-polling).

If a tracker shows `not_home` while the device is near a speaker, the speakers that scan don't find the device:

- The speaker it's near doesn't scan: it's excluded or disabled, doesn't support Bluetooth scans, or hasn't answered since the integration loaded. The debug lines below show which speakers scan.
- Its signal is weaker than -80 dBm at every speaker that scans. Try it right next to one.
- The IRK or MAC address you entered doesn't match the device. Track a phone by its IRK, as its MAC address stops matching once the phone changes it.
- The speakers don't pick the device up in their scans. Which devices they pick up, and when, for example while a phone is asleep or connected to headphones, hasn't been tested.

To see what each speaker does:

1. [Turn on debug logging](troubleshooting.md#collect-debug-logs).
2. Reload the integration, so that the log starts with the first scans: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.
3. Wait a few minutes, then turn off debug logging. Your browser downloads the log file.
4. Look for these lines:
    - `Kitchen heard 12 Bluetooth devices`: the speaker scans. The count includes every device it heard, at any signal strength, not only yours.
    - `Kitchen doesn't support Bluetooth scans, not using it until reload`: the integration doesn't scan with it.
    - `Failed to start Bluetooth scan` or `Failed to read Bluetooth scan`, followed by the speaker's name and the reason: the speaker didn't answer, or answered with an error. If this keeps happening, see [Tracker is unavailable](#tracker-is-unavailable).
    - `Discarded Bluetooth scan of Kitchen read 50 seconds after it started`: the results came too late to use, which counts as a missed scan.

If no line names a speaker, the integration doesn't scan with it: it's excluded or disabled, or the integration hasn't found it on your network.

## Privacy

- The IRKs and MAC addresses you enter are stored in Home Assistant's configuration, like the master token. The integration doesn't send them to your speakers, log them, or show them in entity attributes or the [diagnostics file](troubleshooting.md#download-diagnostics).
- The speakers hear every Bluetooth device nearby, including your neighbors'. The integration keeps only whether your tracked devices were heard, by which speakers and how strongly. It doesn't store or log other addresses.
- The integration gets the scan results from your speakers over your local network and doesn't send them anywhere.

## Known limitations

- Whether scanning affects audio that a speaker plays over Bluetooth hasn't been tested. If you notice dropouts, turn off Bluetooth tracking or exclude that speaker.
- A speaker that sits near a wall can hear a phone outside, as long as the signal is stronger than -80 dBm. The phone then shows `home` while you're just outside.

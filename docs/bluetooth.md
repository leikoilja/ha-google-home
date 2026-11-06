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

## Change departure timing

If a device briefly shows away while it is still home, you can add a departure delay for that tracker:

1. Open **Settings** > **Devices & services** > **Google Home**.
2. Open the tracked Bluetooth device's **⋮** menu and select **Reconfigure**.
3. Set **Additional departure delay** to 0, 30, 60, 90 or 120 seconds, then select **Submit**. You can also set it when adding a device.

The default, **0**, keeps normal timing. A longer delay can suppress brief away transitions, but also slows detection of a real departure. It applies only to this tracker; arrival still shows home as soon as an accepted scan hears the device. Your tracker and its links to people stay in place, and you do not need to enter its IRK or MAC address again.

The delay extends the normal 90-second presence window, measured from the start of the last scan that heard the device. For example, 60 seconds makes the departure threshold 150 seconds from that scan start. The speakers must still provide current, continuous coverage before the tracker can show away. If coverage first becomes adequate after the threshold, it may show away then, without waiting another full delay.

Changes apply without reloading the integration or restarting the absence clock. Increasing the delay does not turn an already-away tracker home. Waiting does not refresh the last confirmed state: if scans cannot confirm absence, the tracker can still become unavailable. A delay does not fix missed Bluetooth advertisements or guarantee that every short away transition will disappear.

## How the tracker works

About every 30 seconds, whatever the [update interval](configuration.md#change-the-update-interval), each speaker reports what it heard since the last check and starts a new scan. Bluetooth devices that are weaker than -80 dBm are ignored, so a phone heard faintly from outside doesn't count.

| State         | When                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `home`        | A speaker heard the device in the last 90 seconds, or its previous home state is retained while awaiting a covered departure.                                                                                          |
| `not_home`    | At least one active speaker, and every other required speaker, has scanned without a break for the last 90 seconds, and none heard the device. When leaving `home`, any additional departure delay must also have elapsed. |
| `unknown`     | There is no recent saved confirmation and the speakers haven't confirmed `home` or `not_home` yet. Fresh scans normally take about 30 to 90 seconds. If it takes longer, see [Tracker doesn't show `home` or stays `unknown`](#tracker-doesnt-show-home-or-stays-unknown). |
| `unavailable` | The tracker showed `home` or `not_home`, but the speakers haven't confirmed either for 5 minutes, for example because a speaker stopped answering. See [Tracker is unavailable](#tracker-is-unavailable). Also while Bluetooth tracking is off. |

With no additional departure delay, in the best case a phone shows `home` within about a minute of arriving, and `not_home` about 60 to 90 seconds after it leaves.

After a successful Home Assistant restart or integration reload, a tracker can start with its recently confirmed `home` or `not_home` state. It keeps only the unused part of the original five minutes since confirmation: restarting repeatedly never makes that evidence newer. Without usable saved evidence, including on first installation or after a long shutdown, it starts `unknown`.

A normal startup can publish the saved state first. An explicit integration reload, a late setup or a failed setup can still show `unavailable` while Home Assistant removes or waits for the entity. Saved state reduces avoidable relearning after the entity returns; it cannot hide those Home Assistant availability transitions. The speakers must rebuild live scan coverage after every restart/reload, and a new sighting can show `home` immediately.

Turning tracking, polling or the integration off invalidates saved tracker state when the integration observes that change. Re-enabling starts fresh. Renaming a tracker keeps its saved state; deleting and re-adding it does not.

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

Treat the values as a rough guide. In testing, one speaker's readings varied by about 20 dB with a phone lying still. The median smooths this out, but the strongest speaker isn't necessarily the nearest, so don't rely on the attribute to tell which room you're in. It's useful for checking how well your speakers cover the places where you keep the device: a device that only one speaker hears, at close to -80 dBm, can show `not_home` when its signal stays below that for about 90 seconds with no additional departure delay.

Home Assistant doesn't keep the attribute's values in its history, so only the current value is available.

## Tracker is unavailable

A tracker makes a new `not_home` decision only with at least one active speaker and continuous 90-second coverage from every required speaker. A speaker joins after returning usable scan results. Failed requests provide no absence evidence; a single missed response does not by itself make a recently confirmed away tracker `unknown` or `unavailable`.

A speaker that stops returning usable results remains required for **five minutes from its last usable scan reply**, then stops blocking away. Reloading or restarting does not restart that timeout. If a saved scanner record can no longer be matched to its exact speaker, it expires sooner: **90 seconds from its original last reply**, or its earlier saved deadline. These timeouts are fixed, shared across trackers and separate from the normal 90-second departure window.

The integration keeps trying inactive speakers on its usual schedule. A new usable reply brings a still-listed speaker back, but it must rebuild continuous coverage from fresh scans. A fresh positive sighting can show `home` immediately. New Google Home devices start being tried automatically once their address and token are available, unless excluded or disabled; a device that has never answered supplies no evidence and does not block away forever.

While it can't tell, the tracker keeps its last state for 5 minutes from when the speakers last confirmed it, so a speaker that misses a scan or comes online doesn't make it flap. If you arrive in that time and only the silent speaker can hear you, `home` waits until another speaker hears you. After the 5 minutes, the tracker shows `unavailable` until the speakers can tell again.

[Download diagnostics](troubleshooting.md#download-diagnostics) to see which speakers are excluded or unsupported, have never returned scan results since the integration last loaded, or aren't currently covering the presence window.

A speaker that replies intermittently can remain active but repeatedly fail to build 90 seconds of unbroken scans. After five minutes without continuous coverage, the integration logs a warning such as "Kitchen has not provided continuous Bluetooth coverage for 5 minutes, so Bluetooth trackers cannot show away". This warning applies while that speaker still blocks away; a fully inactive speaker no longer blocks it. A complete coverage window resets the warning period.

If that speaker is unplugged or out of service, tell the integration not to use it:

1. Go to **Settings** > **Devices & services** > **Google Home** and select **Configure**.
2. Under **Bluetooth**, select the speaker in **Speakers not used for Bluetooth tracking**, then select **Submit**.

You can't delete a speaker that Google still lists in your home, even when it's offline. To stop using it immediately, exclude it, or disable it as described below.

A speaker that you [disable in Home Assistant](configuration.md#stop-checking-some-devices) stops scanning until you enable it again, and no longer keeps trackers from showing `not_home`. If no other speaker scans, trackers can't tell whether you're home, as described above.

A silent speaker also stops blocking `not_home` once Google no longer lists it, for example after you remove it from the Google Home app. The integration notices when it next fetches Google's device list: normally within about 20 minutes, or later with a long [update interval](configuration.md#change-the-update-interval) or after a fetch fails. Only a successful complete device list proves removal: a failed fetch or missing local token does not. After removal, late replies cannot add it back; a later successful list must include it again.

Devices that don't support Bluetooth scans, such as a Chromecast Audio or an Android TV, are left out automatically. A device that has never returned usable results cannot confirm absence.

## Tracker doesn't show `home` or stays `unknown`

Without an eligible saved state, a tracker shows `unknown` until the speakers first confirm `home` or `not_home`. Only a tracker with a confirmation can later become `unavailable` while tracking is on. A silent required speaker can delay that first away decision until its inactivity timeout or until you [exclude or disable it](#tracker-is-unavailable). Restarting is not a way to clear its original timeout.

The speakers can't confirm either state while none of them scans, for example while:

- Every speaker is [excluded](#tracker-is-unavailable) or [disabled](configuration.md#stop-checking-some-devices).
- None of your speakers and displays supports Bluetooth scans.
- Home Assistant [can't reach your speakers](troubleshooting.md#device-offline-or-not-compatible).
- [Polling is turned off](configuration.md#turn-off-polling).

If a tracker shows `not_home` while the device is near a speaker, the speakers that scan don't find the device:

- The speaker it's near doesn't scan: it's excluded or disabled, doesn't support Bluetooth scans, has never answered, or has become inactive. The debug lines below show which speakers scan.
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
- For restart continuity, it keeps one latest snapshot per integration entry in Home Assistant's local `.storage` directory. It contains tracker state and original evidence/expiry times, plus opaque scanner registry or random record IDs and reply/expiry times. It does not contain radio readings, addresses, IRKs, speaker names, local tokens or a history of movements. Its size depends on tracked devices and recent scanner records; it is replaced and pruned, not appended daily. The file is private local storage, not encryption.

## Known limitations

- Whether scanning affects audio that a speaker plays over Bluetooth hasn't been tested. If you notice dropouts, turn off Bluetooth tracking or exclude that speaker.
- A speaker that sits near a wall can hear a phone outside, as long as the signal is stronger than -80 dBm. The phone then shows `home` while you're just outside.

- A silent speaker may be the only one hearing a device that is still home. Once that speaker's timeout expires, empty coverage from the others can incorrectly show `not_home`. If no active speaker has valid coverage, the integration never infers away: it retains the last confirmed state only until its original five-minute expiry, then shows `unavailable`; without any confirmation it stays `unknown`.
- Restored state may hide an arrival or departure during downtime until fresh evidence arrives or the original lease expires. Because a home confirmation can use a sighting almost 90 seconds earlier, saved home can represent a sighting nearly six and a half minutes old. Restart continuity keeps the normal 90-second presence window. The optional additional departure delay can postpone a covered departure, but neither feature guarantees that intermittent false-away transitions disappear.
- Local writes are best effort. A failed write or interrupted process can lose recent evidence, leave older still-unexpired state, or lose scanner requirements. A disable/re-enable completed before the integration could observe it cannot always be reconstructed after process loss. Wrong system time during downtime can also make saved ages unreliable; detected time discontinuities discard continuity and start fresh.

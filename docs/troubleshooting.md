# Troubleshooting

Find what you see, then start with the first check in its section:

- [Adding the integration shows an error](#setup-fails)
- [Home Assistant says that authentication expired](#sign-in-again), or [signing in again fails](#signing-in-again-fails)
- [The integration shows no devices](#no-devices-appear)
- [A device has only a device sensor and a reboot button](#no-alarms-or-timers-sensors)
- [All entities of a device are unavailable](#all-entities-of-a-device-are-unavailable)
- [A device's alarms, timers or settings stop changing](#alarms-timers-or-settings-stop-changing)
- [Deleting an alarm or timer, rebooting or changing a setting shows an error](#an-action-or-setting-fails)

If that doesn't help, see [Still stuck](#still-stuck). Some sections ask you to [collect debug logs](#collect-debug-logs) to find the cause.

## Setup fails

When you [sign in again](#sign-in-again), the form shows these errors too.

### "Username or password is incorrect"

[Update the integration](https://github.com/leikoilja/ha-google-home/releases/latest) and use [browser sign-in](installation.md#browser-sign-in). Older versions of the integration signed in with an app password, which Google rejects for many accounts.

### "Google didn't accept the cookie"

Close the private window and repeat [browser sign-in](installation.md#browser-sign-in) from step 1, then paste the new cookie straight away. Copy the whole value, starting with `oauth2_4/`. The `oauth_token` cookie expires within minutes and works only once.

### "Google didn't accept the master token"

Check that you pasted the token exactly as you got it. If it was correct before and has stopped working, for example after you changed your Google password, Google no longer accepts it: use [browser sign-in](installation.md#browser-sign-in) instead. If the integration is already set up, [sign in again](#sign-in-again) rather than deleting it.

### "Google didn't accept the sign-in"

Google refused the cookie or master token for a reason that the integration doesn't know or without a reason, or it answered in a way that the integration doesn't understand. Open the [log](https://my.home-assistant.io/redirect/logs/) and find the warning that starts with `Failed to sign in`; Google's reason, if it gave one, is at the end. [Open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with that line, after you replace any email address or token in it with `xxx`.

### "Couldn't reach Google"

Home Assistant couldn't connect to Google, or Google didn't answer in time. Check that Home Assistant is connected to the internet. The integration signs in at `android.clients.google.com`, and after setup gets your devices from `googlehomefoyer-pa.googleapis.com`. If a DNS filter or firewall, such as Pi-hole or AdGuard Home, blocks either, allow it. Then try again. With browser sign-in, get a new cookie if a few minutes have passed.

### "Google is busy or is limiting sign-ins"

Google answered with a server error, or asked the integration to slow down. This doesn't mean that your cookie or master token is wrong. Wait a few minutes, then sign in again. With browser sign-in, get a new cookie, as the old one expires within minutes.

## Sign in again

Google can stop accepting the integration's sign-in, for example after you change your Google account's password. Home Assistant then reports that authentication expired, and the Google Home card in **Settings** > **Devices & services** shows **Reconfigure**. Sign in again with the same Google account to keep your devices, their entity IDs and your automations:

1. Go to **Settings** > **Devices & services** and, on the Google Home card, select **Reconfigure**.
2. Choose how to sign in, and follow the same steps as for [browser sign-in](installation.md#browser-sign-in) or a [master token](installation.md#master-token). Use the same Google account as before.

Home Assistant then reloads the integration with the new sign-in.

Sign in again soon. Until you do, your devices can stop updating one by one, so what Home Assistant shows for them can be out of date, and new devices don't appear. After Home Assistant restarts, the integration doesn't start until you sign in again.

- If you closed the sign-in window, select **Reconfigure** again to continue where you left off.
- To choose another way to sign in after you picked one, reload the integration: go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu and select **Reload**. Sign-in starts again from the choice, but the integration stops until you finish, and its entities are unavailable.
- If Home Assistant says that you signed in to a different Google account, see ["You signed in to a different Google account"](#you-signed-in-to-a-different-google-account).

## Signing in again fails

The form for signing in again shows the same errors as setup; see [Setup fails](#setup-fails).

### "You signed in to a different Google account"

Google reports that you signed in to another account than the one the integration uses, so Home Assistant didn't change anything. The form stays open: sign in there with the account the integration uses. With browser sign-in, close the private window and repeat [browser sign-in](installation.md#browser-sign-in) from step 1, signing in to that account.

To use the other account instead, delete the integration and add it again.

Version 1.13 and older saved the email address you typed when you set up the integration. If that isn't your Google account's primary address, for example because you typed an alternate address, and the integration isn't named after the primary address either, Home Assistant refuses your own account. To keep the integration, name it after your primary address: close the sign-in window, go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu, select **Rename** and enter the address. Then select **Reconfigure** and [sign in again](#sign-in-again). Otherwise, delete the integration and add it again.

## Devices are missing

### No devices appear

The integration adds only Google Cast devices, such as Google speakers and displays. Lights, plugs, thermostats and other devices in your Google Home app don't appear; see [Other Google Home devices](other-integrations.md#other-google-home-devices).

The Google account you signed in with must be a member of the home your devices belong to. Open the Google Home app with that account and check that the devices are listed. If not, [invite the account](https://support.google.com/googlenest/answer/9155535) to your home and reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

If you signed in with a Google Workspace account, such as many work and school accounts, it can't be a member of your home: [Google doesn't allow inviting Workspace accounts](https://support.google.com/googlehome/answer/9155535). Sign in with a Gmail account, one ending in `@gmail.com`, that is a member of your home instead. Some users with personal Google accounts using non-Gmail addresses have also reported missing devices; [switching to a Gmail account resolved the problem](https://github.com/leikoilja/ha-google-home/issues/1014#issuecomment-4466736100).

If Google didn't give the integration your devices when it started, for example because Google was busy, the integration starts without devices, and the log shows `Failed to fetch Google's device list` with Google's reason at the end. The integration keeps asking Google by itself: after each failed attempt it waits longer, up to 20 minutes, and asks again at the first [update](configuration.md#change-the-update-interval) after that wait, so a long update interval makes the wait longer.

- If the reason is 429, a 5xx code such as 503, `RESOURCE_EXHAUSTED` or `UNAVAILABLE`, Google is busy, has a temporary problem or is limiting requests: wait.
- If `UNAVAILABLE` doesn't go away, check that Home Assistant can reach Google; see ["Couldn't reach Google"](#couldnt-reach-google).

Once the cause is fixed, you can reload the integration to ask Google straight away.

### No alarms or timers sensors

The integration adds the alarms sensor, timers sensor, Do Not Disturb switch and alarm volume for a device once the device answers successfully. Until then, a device that is offline, or that doesn't support these features, has only a device sensor and a reboot button. Check the device sensor:

- **It shows an IP address:** the entities appear at the next update the device answers successfully. If they don't, the device may have [no alarms and timers](#devices-without-alarms-and-timers).
- **It's unavailable on all your devices:** first check that Home Assistant can reach them on your network; see [Home Assistant can't reach your devices](#device-offline-or-not-compatible). For other causes, see [When entities are unavailable](entities.md#when-entities-are-unavailable).
- **It's unavailable on this device:** make sure the device is on and connected to your network. The entities appear at the first update it answers successfully. If the integration doesn't know the device's IP address, it gets it from the device's mDNS announcements, if Home Assistant receives them. Otherwise, it looks for the device, also at your [known hosts](configuration.md#add-devices-on-another-network), when it next asks Google for your devices, at the first [update](configuration.md#change-the-update-interval) at least 20 minutes after it last asked.

If you don't want to wait, make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. If that doesn't help, restart the Google Home device and then Home Assistant.

#### Devices without alarms and timers

Some Cast devices, such as Chromecast Audio, have no alarms, timers, Do Not Disturb or alarm volume. Such a device keeps only its device sensor and reboot button. If it had the other entities, they become unavailable.

If this happens to a device that has alarms and timers, or a device gains these features, make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. The integration adds the entities once the device answers for them. The integration checks the device again only when it starts, after you reload it or restart Home Assistant, so restarting the device or running `google_home.refresh_devices` doesn't bring them back.

??? note "Advanced: how the integration recognizes these devices"

    The integration finds that a device has none of these features from how it answers, not from a list of models: the device still answers "not found" when asked for its alarms at least 10 minutes after it first did, and its information lists its features without Google Assistant. A device that is starting answers "not found" for a while too, so until both are true, the integration keeps asking the device for alarms at every update, even while it doesn't answer. After a reload, a device that still answers this way is recognized again at least 10 minutes later.

    Once it has recognized such a device, it asks the device only for its information at each update, to see whether it answers; see [When entities are unavailable](entities.md#when-entities-are-unavailable). A firmware update that adds these features doesn't make it check again; reload the integration.

    When the integration stops asking a device, the [debug log](#collect-debug-logs) shows a line like this, with your device's name and model:

    ```
    Stereo (hardware='Chromecast Audio') still answers 404 for alarms after at least 10 minutes, and its info lists its features without Google Assistant. It won't be asked for alarms, timers and settings until the integration is reloaded.
    ```

### Home Assistant can't reach your devices {#device-offline-or-not-compatible}

If all your devices have only a device sensor and a reboot button, and both are unavailable, or all their entities became unavailable after they worked, first check that Home Assistant can find and reach the devices on your network. Entities can also be unavailable for other reasons, for example once Google no longer lists a device; see [When entities are unavailable](entities.md#when-entities-are-unavailable).

The integration finds your devices with multicast DNS (mDNS) and then talks to them directly. Only signing in and getting device tokens go through Google. Check that:

- Home Assistant and the devices are on the same network.
- If Home Assistant runs in Docker, the container uses `host` network mode.
- If your devices are on a separate network or VLAN, your router forwards mDNS between the networks, and Home Assistant can reach the devices on TCP port 8443.

If mDNS can't reach your devices but Home Assistant can reach them on TCP port 8443, add their IP addresses as [known hosts](configuration.md#add-devices-on-another-network) instead.

If Home Assistant can't find a device's IP address, the [debug log](#collect-debug-logs) shows this message for it once, after the integration starts. To see it, enable debug logging, then reload the integration:

```
Failed to fetch timers/alarms information from device Kitchen. We could not determine its IP address, the device is either offline or is not compatible Google Home device. Will try again later.
```

If only some devices are affected, check that Home Assistant can discover and reach those devices too.

## A device stops updating

### All entities of a device are unavailable

Check that the device is on and connected to your network. The entities become unavailable once the device hasn't answered 5 updates in a row, and come back at the next update it answers with anything other than "not found". A speaker that is starting answers "not found" for a while. See [When entities are unavailable](entities.md#when-entities-are-unavailable).

- If they become unavailable for a moment while a speaker restarts and you use a short update interval, [increase the interval](configuration.md#change-the-update-interval).
- If only the alarms sensor, timers sensor, switch and alarm volume are unavailable while the device sensor shows an IP address, the integration may have found that the device has [no alarms and timers](#devices-without-alarms-and-timers).
- An alarms or timers sensor on its own also shows `unavailable` when nothing is coming up; see [Alarms sensor](entities.md#alarms-sensor).
- If the entities of all your devices are unavailable, check that Home Assistant can still reach them on your network; see [Home Assistant can't reach your devices](#device-offline-or-not-compatible).

To check that the device doesn't answer, [collect debug logs](#collect-debug-logs) for a few updates while the entities are unavailable. For a device that doesn't answer, each update logs a line such as `Failed to connect to Kitchen device. The device is probably offline.` or `Kitchen device timed out while performing a request to it`. For a [device without alarms and timers](#devices-without-alarms-and-timers), which is asked only for its information, the line is `Kitchen didn't answer when asked for its info`, and there are no lines that start with `Requesting endpoint` for the device. If debug logging was already on when the entities became unavailable, the log also has this line, which appears only once:

```
Kitchen didn't answer 5 updates in a row. Its entities are unavailable until it answers with something other than "not found".
```

### Alarms, timers or settings stop changing

If a device's alarms, timers and settings stop changing in Home Assistant while its entities stay available, [collect debug logs](#collect-debug-logs) for a few updates. A line such as `Kitchen rejected its token` means that the device refuses the token the integration has for it.

A device's token can change, for example when the device restarts. The integration then gets the new token from Google straight away. If Google can't give it, the device's entities keep the values they had. The integration keeps asking Google by itself: after each failed attempt it waits longer, up to 20 minutes, and asks again at the first [update](configuration.md#change-the-update-interval) after that wait, so a long update interval makes the wait longer. If Google can't be reached at all, the devices keep updating with the tokens they have, and their entities stay available.

If Home Assistant asks you to [sign in again](#sign-in-again), do that first. Otherwise, to find out why Google didn't give the token, open the [log](https://my.home-assistant.io/redirect/logs/) and find the error that starts with `Failed to fetch Google's device list`. Google's reason is at the end:

- If the reason is 429, a 5xx code such as 503, `RESOURCE_EXHAUSTED` or `UNAVAILABLE`, Google is busy, has a temporary problem or is limiting requests: wait, as the integration keeps asking by itself.
- If `UNAVAILABLE` doesn't go away, or there is no such error, check that Home Assistant can reach Google; see ["Couldn't reach Google"](#couldnt-reach-google).

Once the cause is fixed, you can reload the integration to ask Google straight away: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

## An action or setting fails

Deleting alarms or timers, rebooting, turning Do Not Disturb on or off and setting the alarm volume fail with an error, rather than look successful, when a device may not have done what you asked. Most errors name the device and say why. To let your automation or script carry on after an error, see [Continue after an error](actions.md#continue-after-an-error).

### A delete fails

The four [delete actions](actions.md#delete-alarm) fail when an alarm or timer may still be set. The error names each device that failed, and the action still runs for the other devices you target before it fails. Delete alarm and Delete timer also fail when no device has the ID, or when it isn't a valid ID.

- "Couldn't get the current alarms and timers from Kitchen, so nothing was deleted from it. Check that it's online and try again later". The device didn't send its current alarms and timers, for example because it has just become unreachable or rejects its token, so it got no delete request. Once it hasn't answered 5 updates in a row, its alarms and timers sensors are unavailable instead, and Home Assistant skips them without an error; see [Unavailable sensors](actions.md#unavailable-sensors).
- "Kitchen didn't confirm deleting the alarms or timers, so they may still be set. Check that it's online and try again later". The device stopped answering, refused or sent an unexpected reply. It may still have deleted them. Unless `skip_refresh` is `true`, the action asks for an update of the device, which shows what it has once it answers.
- If several devices fail, one error names them all. When none of them sent its current alarms and timers: "Couldn't get the current alarms and timers from these devices, so nothing was deleted from them: Bedroom, Kitchen. Check that they're online and try again later". Otherwise: "Couldn't delete alarms or timers from these devices, or confirm that they were deleted: Bedroom, Kitchen. Check that they're online and try again later".
- "Couldn't find the alarm alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51 on the devices you targeted. It may already have gone off or been deleted", or the same for a timer. Delete alarm and Delete timer report this when every device the action checks sends its current list without the ID. Home Assistant skips unavailable sensors, and with a device, area, floor or label target also hidden or disabled ones, so a device it skipped may still have the alarm or timer. Retrying after a device didn't confirm can give this error if the alarm or timer is gone by then.
- "“alarm/123” isn't an alarm ID. Copy the ID, which starts with alarm/, from the alarms attribute of the device's alarms sensor", or the same for a timer. The ID doesn't start with `alarm/` or `timer/`, or has the wrong length, so no device was asked.

### A setting or reboot fails

Turning Do Not Disturb on or off, setting the alarm volume, pressing Reboot and the [Reboot device](actions.md#reboot-device) action fail with an error, rather than look successful, when the request to the device fails. The error names the device and says why:

- "Couldn't reach Living Room. Check that it's on and connected to your network, then try again". The device refused the connection or your network reports it as unreachable, or Home Assistant doesn't know its IP address.
- "Living Room didn't confirm that it did this: it didn't answer in time, or its answer was cut off. Check that it's online and try again". The device didn't answer within about 5 seconds, or didn't even accept the connection in that time, or it closed the connection or stopped its answer partway. The next update shows the device's current Do Not Disturb setting and alarm volume.
- "Living Room rejected its token, and getting a new one from Google didn't help. The integration keeps asking Google for one, so try again later". The integration has already asked Google for a new token. It asks again at the next update or, if Google didn't answer, at the first update after a wait that grows from 1 minute to 20 minutes, so try again after that; see [Alarms, timers or settings stop changing](#alarms-timers-or-settings-stop-changing). If Home Assistant asks you to [sign in again](#sign-in-again), do that first.
- "Living Room answered “not found”. It may still be starting up, so try again later, or it may not support this".
- "Couldn't do this on Living Room. For details, see the Home Assistant log". The device answered with another error, or the request failed for another reason. Open the [log](https://my.home-assistant.io/redirect/logs/) to see what it was.
- "These devices didn't confirm that they'll reboot: Bedroom, Kitchen. Check that they're online and try again later". Reboot device gives this when more than one device fails. It still reboots every device that answers.

### An action fails while the integration isn't loaded

While the integration isn't loaded, its [actions](actions.md), such as `google_home.delete_alarm`, fail whatever you target, and nothing is sent to your devices: "Config entry you@example.com for integration google_home is not loaded". Instead of you@example.com, it shows the integration's name, usually your Google account. This happens, for example, when Google didn't accept the master token at startup, while Home Assistant waits to try setting up the integration again, or while it's still setting it up after a restart.

Open **Settings** > **Devices & services** > **Google Home** to see why it isn't loaded, and if Home Assistant asks you to, [sign in again](#sign-in-again). Once the integration is loaded, the actions run again.

## Download diagnostics

The diagnostics file shows:

- The integration's options.
- For each device: its model, whether it answers, whether Home Assistant has received its mDNS announcements since the integration loaded, and its last reply about alarms and timers, as the device sent it.
- How many other Cast devices on your network have announced themselves since the integration loaded but aren't in Google's device list, such as TVs with Chromecast built in, or speakers in another Google account. Only the number, not their names or addresses.
- When you downloaded it.

Attach the file, as well as [debug logs](#collect-debug-logs), when you [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose).

1. Go to **Settings** > **Devices & services** > **Google Home**.
2. Open the **⋮** menu and select **Download diagnostics**. Your browser downloads the file.

The menu has **Download diagnostics** only while the integration is set up. If setup fails, [collect debug logs](#collect-debug-logs) instead.

!!! warning "Check the file before sharing it"

    The file replaces your email address, password, master token and Android ID, your devices' local tokens and IP addresses, and your known hosts with `**REDACTED**`. It keeps your device names and the times and labels of your alarms and timers. Home Assistant also adds details about your system, such as its version, your time zone and the custom integrations you use. Open the file and replace anything you don't want to share with `xxx` before you attach it to a public issue.

## Collect debug logs

Debug logs show what the integration is doing. Attach them when you [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose).

1. Go to **Settings** > **Devices & services** > **Google Home**.
2. Open the **⋮** menu and select **Enable debug logging**.
3. Reproduce the problem.
4. Open the **⋮** menu again and select **Disable debug logging**. Your browser downloads the log file.

If setup fails, the integration has no **⋮** menu yet. Instead, run this action in [**Settings** > **Tools** > **Actions**](https://my.home-assistant.io/redirect/tools_actions/), then try to add the integration again and open the [log](https://my.home-assistant.io/redirect/logs/). The action also logs `glocaltokens`, the library the integration uses to sign in:

```yaml
action: logger.set_level
data:
  custom_components.google_home: debug
  glocaltokens: debug
```

!!! warning "Remove secrets before sharing logs"

    Debug logs can contain your email address, tokens and the IP addresses of your devices. Replace them with `xxx` before you post the log.

## Still stuck

Search [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions) and the [issues](https://github.com/leikoilja/ha-google-home/issues?q=is%3Aissue) for your problem. If nobody has reported it, ask in [Q&A](https://github.com/leikoilja/ha-google-home/discussions/categories/q-a), or [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with your [diagnostics](#download-diagnostics) and [debug logs](#collect-debug-logs).

# Troubleshooting

Find what you see, then start with the first check in its section:

- [Adding the integration shows an error](#setup-fails)
- [The integration doesn't load after you update Home Assistant or the integration](#the-integration-doesnt-load-after-an-update)
- [The Google Home card shows **1 entry failed to set up, retrying**](#failed-setup-will-retry)
- [Home Assistant says that authentication expired](#sign-in-again), or [signing in again fails](#signing-in-again-fails)
- [The integration shows no devices](#no-devices-appear)
- [A device has only a device sensor, a reboot button, an update sensor, and disabled Wi-Fi and uptime sensors](#no-alarms-or-timers-sensors)
- [All entities of a device are unavailable](#all-entities-of-a-device-are-unavailable)
- [A device's alarms, timers or settings stop changing](#alarms-timers-or-settings-stop-changing)
- [Deleting an alarm or timer, rebooting or changing a setting shows an error](#an-action-or-setting-fails)
- [An automation didn't run at an alarm's or timer's time](automations.md#when-the-trigger-runs)
- [A Bluetooth tracker shows `unavailable`](bluetooth.md#tracker-is-unavailable)

If that doesn't help, see [Still stuck](#still-stuck). Some sections ask you to [collect debug logs](#collect-debug-logs) to find the cause.

## Setup fails

When you [sign in again](#sign-in-again), the form shows the same sign-in errors.

### "Username/Password is incorrect" {#username-or-password-is-incorrect}

[Update the integration](installation.md#install-the-integration), from the Marketplace or manually, and use [browser sign-in](installation.md#browser-sign-in). Older versions of the integration signed in with an app password, which Google rejects for many accounts.

### Browser sign-in asks for a new cookie {#google-didnt-accept-the-cookie}

Close the private window and repeat [browser sign-in](installation.md#browser-sign-in) from step 1, then paste the new cookie straight away. Copy the whole value, starting with `oauth2_4/`. The `oauth_token` cookie can expire quickly and works only once. The error can also appear after Google accepted the cookie but refused the next part of the sign-in.

### "Google didn't accept the master token"

Check that you pasted the token exactly as you got it. If it was correct before and has stopped working, for example after you changed your Google password, Google no longer accepts it: use [browser sign-in](installation.md#browser-sign-in) instead. If the integration is already set up, [sign in again](#sign-in-again) rather than deleting it.

### "Google didn't accept the sign-in"

Google refused the cookie or master token for a reason that the integration doesn't know or without a reason, or it answered in a way that the integration doesn't understand. Open the [log](https://my.home-assistant.io/redirect/logs/) and find the warning that starts with `Failed to sign in`; Google's reason, if it gave one, is at the end. [Open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with that line, after you replace any email address or token in it with `xxx`.

### "Couldn't reach Google"

Home Assistant couldn't connect to Google, or Google didn't answer in time. Check that Home Assistant is connected to the internet. The integration signs in at `android.clients.google.com`, and gets your homes and devices from `googlehomefoyer-pa.googleapis.com`. If a DNS filter or firewall, such as Pi-hole or AdGuard Home, blocks either, allow it. Then try again. With browser sign-in, get a new cookie for the next attempt.

If only `googlehomefoyer-pa.googleapis.com` is blocked, adding the integration shows no error, but doesn't ask you to [choose homes](configuration.md#choose-homes), and the integration starts without devices; see [No devices appear](#no-devices-appear). Once you allow it, reload the integration, and choose homes in its options if you want only some of them.

Once the integration is added, [System information](#check-system-information) shows whether Home Assistant reaches both.

### "Google is busy or is limiting sign-ins"

Google answered with a server error, or asked the integration to slow down. This doesn't mean that your cookie or master token is wrong. Wait a few minutes, then sign in again. With browser sign-in, get a new cookie, as the old one can expire quickly.

### "This integration allows only one configuration"

You can add the integration only once, so it works with one Google account. Adding it again shows this message, or "Already configured. Only a single configuration is possible." To add devices from several homes, [invite the account](https://support.google.com/googlenest/answer/9155535) you signed in with to each home: the integration adds the devices of every home that account is a member of. To use another account instead, see [Remove the integration](configuration.md#remove-the-integration).

### "Failed setup, will retry"

When Home Assistant couldn't connect to Google as the integration started, or Google didn't answer in time, the Google Home card in **Settings** > **Devices & services** shows **1 entry failed to set up, retrying**, and the integration's page shows **Failed setup, will retry**. Home Assistant tries again by itself, after a wait that grows up to 10 minutes. The log shows nothing about it unless [debug logging](#collect-debug-logs) is on, so **Check the logs** on that page finds nothing. Until the integration starts, its entities are unavailable and its [actions fail](#an-action-fails-while-the-integration-isnt-loaded).

Check that Home Assistant can reach Google; see ["Couldn't reach Google"](#couldnt-reach-google). [System information](#check-system-information) shows whether Google's servers answer, though `ok` doesn't show that Google accepts the sign-in. Once Google answers, the next try starts the integration. To try straight away, reload it: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

### The integration doesn't load after an update

An update can stop the integration from loading: a new Home Assistant version may not be able to install the libraries that an older version of the integration needs, and a new release of the integration needs a recent Home Assistant. **Settings** > **Devices & services** > **Google Home** then shows **Not loaded**. After a restart, an **Invalid config** notification lists `google_home` under "The following integrations and platforms could not be set up". The [log](https://my.home-assistant.io/redirect/logs/) shows an error such as `Setup failed for custom integration 'google_home': Requirements for google_home not found`, and adding the integration can show "Config flow could not be loaded".

1. Check that your Home Assistant version is supported; see [Before you start](installation.md#before-you-start). If it's older, update Home Assistant first.
2. [Update the integration](installation.md#install-the-integration) to the latest release, then restart Home Assistant.

If the latest release doesn't load either, search the [issues](https://github.com/leikoilja/ha-google-home/issues?q=is%3Aissue) for the error, or [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with the error from the log.

## Sign in again

Google can stop accepting the integration's sign-in, for example after you change your Google account's password. Home Assistant then reports that authentication expired, and the Google Home card in **Settings** > **Devices & services** shows **Reconfigure**. Sign in again with the same Google account to keep your devices, their entity IDs and your automations:

1. Go to **Settings** > **Devices & services** and, on the Google Home card, select **Reconfigure**.
2. Choose how to sign in, and follow the same steps as for [browser sign-in](installation.md#browser-sign-in) or a [master token](installation.md#master-token). Use the same Google account as before.

Home Assistant then reloads the integration with the new sign-in.

Sign in again soon. Until you do, your devices can stop updating one by one, so what Home Assistant shows for them can be out of date, and new devices don't appear. After Home Assistant restarts, the integration doesn't start until you sign in again, and **Settings** > **Devices & services** > **Google Home** shows a message such as "Google didn't accept the sign-in (BadAuthentication). Sign in again."

- If you closed the sign-in window, select **Reconfigure** again to continue where you left off.
- To choose another way to sign in after you picked one, reload the integration: go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu and select **Reload**. Sign-in starts again from the choice, but the integration stops until you finish, and its entities are unavailable.
- If Home Assistant says that you signed in to a different Google account, see ["You signed in to a different Google account"](#you-signed-in-to-a-different-google-account).

### Signing in again fails

The form for signing in again shows the same errors as setup; see [Setup fails](#setup-fails).

#### "You signed in to a different Google account"

Google reports that you signed in to another account than the one the integration uses, so Home Assistant didn't change anything. The form stays open: sign in there with the account the integration uses. With browser sign-in, close the private window and repeat [browser sign-in](installation.md#browser-sign-in) from step 1, signing in to that account.

To use the other account instead, delete the integration and add it again.

Version 1.13 and older saved the email address you typed when you set up the integration. If that isn't your Google account's primary address, for example because you typed an alternate address, and the integration isn't named after the primary address either, Home Assistant refuses your own account. To keep the integration, name it after your primary address: close the sign-in window, go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu, select **Rename** and enter the address. Then select **Reconfigure** and [sign in again](#sign-in-again). Otherwise, delete the integration and add it again.

## Devices are missing

### No devices appear

The integration adds only Google Cast devices, such as Google speakers and displays. Lights, plugs, thermostats and other devices in your Google Home app don't appear; see [Other Google Home devices](other-integrations.md#other-google-home-devices).

The Google account you signed in with must be a member of the home your devices belong to. Open the Google Home app with that account and check that the devices are listed. If not, [invite the account](https://support.google.com/googlenest/answer/9155535) to your home and reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. If the devices are in a home that you deselected, select it again; see [Choose homes](configuration.md#choose-homes).

If Google reports that the account isn't a member of any home when you add the integration, setup stops with "Google reports that this account isn't a member of any home, so there are no speakers or displays to add": invite the account to your home, then add the integration again. If Google reports this later, **Settings** > **System** > **Repairs** shows **Google reports no home for your account**. If the account is a member only of homes that you deselected, it shows **None of your Google account's homes is selected**. Each repair says how to fix it.

If you signed in with a Google Workspace account, such as many work and school accounts, it can't be a member of your home: [Google doesn't allow inviting Workspace accounts](https://support.google.com/googlehome/answer/9155535). Sign in with a Gmail account, one ending in `@gmail.com`, that is a member of your home instead. Some users with personal Google accounts using non-Gmail addresses have also reported missing devices; [switching to a Gmail account resolved the problem](https://github.com/leikoilja/ha-google-home/issues/1014#issuecomment-4466736100).

To see what Google lists for the account, [collect debug logs](#collect-debug-logs) while you reload the integration. These lines come from `glocaltokens`, the library the integration uses to sign in and get your devices:

- `Iterating in 12 homegraph devices`: how many devices Google lists in all the account's homes, including lights and other devices that the integration doesn't add. With `0`, Google gave no devices for the account: check that it's a member of your home, as described above.
- `'Hallway light' local_auth_token is not found in Homegraph, skipping`: Google has no local token for the device, as for lights, plugs and thermostats, so the integration can't add it.
- A line that ends with `local_auth_token isn't 108 characters as expected for a Cast device, skipping it`: the device's token isn't a Cast device's, as for Google and Nest Wifi routers, so the integration can't add it.

If a skipped device is a speaker or display that you expected, that's why it's missing: [get help](#still-stuck) with the debug logs.

If Google didn't give the integration your devices when it started, for example because Google was busy, the integration starts without devices, and the log shows `Failed to fetch Google's device list` with the reason the attempt failed at the end. The integration keeps asking Google by itself: after a wait of up to 20 minutes, it asks again at the next [update](configuration.md#change-the-update-interval), so a long update interval makes the wait longer. The error says when it asks next, or to [sign in again](#sign-in-again). While [polling is turned off](configuration.md#turn-off-polling), it doesn't ask again by itself, so the error says to reload it instead, as described below. Only the first failure is logged; later ones show in [debug logs](#collect-debug-logs) until one works.

- If the reason is 429, a 5xx code such as 503, `RESOURCE_EXHAUSTED` or `UNAVAILABLE`, Google is busy, has a temporary problem or is limiting requests: wait.
- If the reason is `DEADLINE_EXCEEDED`, or if `UNAVAILABLE` doesn't go away, check that Home Assistant can reach Google; see ["Couldn't reach Google"](#couldnt-reach-google).

Once the cause is fixed, you can reload the integration to ask Google straight away.

### No alarms or timers sensors

The integration adds the alarms sensor, timers sensor, Do Not Disturb switch and alarm volume for a device once the device answers successfully. Until then, a device that is offline, or that doesn't support these features, has only a device sensor, a reboot button, an update sensor, and disabled Wi-Fi and uptime sensors. Check the device sensor:

- **It shows an IP address:** the entities appear at the next update the device answers successfully. If they don't, the device may have [no alarms and timers](#devices-without-alarms-and-timers).
- **It's unavailable on all your devices:** first check that Home Assistant can reach them on your network; see [Home Assistant can't reach your devices](#device-offline-or-not-compatible). For other causes, see [When entities are unavailable](entities.md#when-entities-are-unavailable).
- **It's unavailable on this device:** make sure the device is on and connected to your network. The entities appear at the first update it answers successfully. If the integration doesn't know the device's IP address, it gets it from the device's mDNS announcements or from your [known hosts](configuration.md#add-devices-on-another-network), which it asks again about every 5 minutes. It also looks for the device again each time it asks Google for your devices, about every 20 minutes.

If you don't want to wait, make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. If that doesn't help, restart the Google Home device and then Home Assistant.

#### Devices without alarms and timers

Some Cast devices, such as Chromecast Audio, have no alarms, timers, Do Not Disturb or alarm volume. Such a device keeps only its device sensor, reboot button, update sensor, [Wi-Fi sensors](entities.md#wi-fi-sensors) and [uptime sensor](entities.md#uptime-sensor). If it had the other entities, they become unavailable.

If this happens to a device that has alarms and timers, or a device gains these features, make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. The integration adds the entities once the device answers for them. The integration checks the device again only when it starts, after you reload it or restart Home Assistant, so restarting the device or running `google_home.refresh_devices` doesn't bring them back.

??? note "Advanced: how the integration recognizes these devices"

    The integration recognizes such a device from how it answers, not from a list of models: the device still answers "not found" when asked for its alarms at least 10 minutes after it first did, and its information lists its features without Google Assistant. A speaker that is starting answers "not found" for a while too, so the integration keeps asking it for alarms until both are true. It then stops, and the [debug log](#collect-debug-logs) shows a line like this, with your device's name and model:

    ```
    Stereo (hardware='Chromecast Audio') still answers 404 for alarms after at least 10 minutes, and its info lists its features without Google Assistant. It won't be asked for alarms, timers and settings until the integration is reloaded.
    ```

### Home Assistant can't reach your devices {#device-offline-or-not-compatible}

If all your devices have only a device sensor, a reboot button, an update sensor, and disabled Wi-Fi and uptime sensors, and all of them are unavailable, or all their entities became unavailable after they worked, first check that Home Assistant can find and reach the devices on your network. Entities can also be unavailable for other reasons, for example once Google no longer lists a device; see [When entities are unavailable](entities.md#when-entities-are-unavailable).

Check that:

- Home Assistant and the devices are on the same network.
- If Home Assistant runs in Docker, the container uses `host` network mode.
- If your devices are on a separate network or VLAN, Home Assistant can find them and reach them on TCP port 8443; see [Add devices on another network](configuration.md#add-devices-on-another-network).

If Home Assistant can't find a device's IP address, the [debug log](#collect-debug-logs) shows this message for it once, after the integration starts. To see it, enable debug logging, then reload the integration:

```
Failed to fetch timers/alarms information from device Kitchen. We could not determine its IP address, the device is either offline or is not compatible Google Home device. Will try again later.
```

If only some devices are affected, check that Home Assistant can discover and reach those devices too.

## A device stops updating

### All entities of a device are unavailable

Check that the device is on and connected to your network. The entities become unavailable once the device hasn't answered 5 updates in a row, and come back at the next update it answers with anything other than "not found", which a speaker answers for a while as it starts. See [When entities are unavailable](entities.md#when-entities-are-unavailable).

- If they become unavailable for a moment while a speaker restarts and you use a short update interval, [increase the interval](configuration.md#change-the-update-interval).
- If only the alarms sensor, timers sensor, switch and alarm volume are unavailable while the device sensor shows an IP address, the integration may have found that the device has [no alarms and timers](#devices-without-alarms-and-timers).
- An alarms or timers sensor on its own also shows `unavailable` when nothing is coming up; see [Alarms sensor](entities.md#alarms-sensor).
- If the entities of all your devices are unavailable, check that Home Assistant can still reach them on your network; see [Home Assistant can't reach your devices](#device-offline-or-not-compatible).

To check that the device doesn't answer, [collect debug logs](#collect-debug-logs) for a few updates while the entities are unavailable. For a device that doesn't answer, each update logs a line such as `Failed to connect to Kitchen device. The device is probably offline.` or `Kitchen device timed out while performing a request to it`, usually followed by `Kitchen didn't answer when asked for its info`. A [device without alarms and timers](#devices-without-alarms-and-timers) is asked only for its information, so it logs only that last line, and no lines that start with `Requesting endpoint`. If debug logging was already on when the entities became unavailable, the log also has this line, which appears only once:

```
Kitchen didn't answer 5 updates in a row. Its entities are unavailable until it answers with something other than "not found".
```

A device whose IP address Home Assistant doesn't know isn't asked, so it logs none of these lines; see [Home Assistant can't reach your devices](#device-offline-or-not-compatible).

### Alarms, timers or settings stop changing

If a device's alarms, timers and settings stop changing in Home Assistant while its entities stay available, [collect debug logs](#collect-debug-logs) for a few updates. A line such as `Kitchen rejected its token` means that the device refuses the token the integration has for it.

A device's token can change, for example when the device restarts. The integration then gets the new token from Google straight away. If Google can't give it, the device's entities keep the values they had, and the integration keeps asking Google by itself. While [polling is turned off](configuration.md#turn-off-polling), it asks only at an update you ask for: run [Refresh devices](actions.md#refresh-devices) after the time that [System information](#check-system-information) shows under **Retry not before**.

If Home Assistant asks you to [sign in again](#sign-in-again), do that first. Otherwise, to find out why Google didn't give the token, open the [log](https://my.home-assistant.io/redirect/logs/) and find the error that starts with `Failed to fetch Google's device list`. The reason the attempt failed is at the end of the error:

- If the reason is 429, a 5xx code such as 503, `RESOURCE_EXHAUSTED` or `UNAVAILABLE`, Google is busy, has a temporary problem or is limiting requests: wait, as the integration keeps asking by itself.
- If the reason is `Cannot connect to host ...`, `TimeoutError` or `DEADLINE_EXCEEDED`, or if `UNAVAILABLE` doesn't go away, check that Home Assistant can reach Google; see ["Couldn't reach Google"](#couldnt-reach-google).

If the log instead has an error such as `Kitchen rejected the token that Google gave it. Google is asked for a new one at the first update after 2 min; further rejections are logged at debug level until it accepts one`, Google answered, but with a token that the device rejects too. Right after a device restarts, Google can give its old token for a short while, so the integration asks Google again a minute later, and logs this error only if the device rejects that token as well.

The integration then doesn't ask Google for that device at every update: it asks again at the first update after the time in the error, then after 5 and 10 minutes, and then every 20 minutes, until the device accepts a token. Meanwhile, another device whose token changes still gets its new token straight away. [System information](#check-system-information) shows the device list as `fetched`, without **Retry not before**. Once the device accepts a token, its alarms, timers and settings change again, and with [debug logging](#collect-debug-logs) on, the log shows `Updating Kitchen works again`. While [polling is turned off](configuration.md#turn-off-polling), the integration doesn't wait like this: each [Refresh devices](actions.md#refresh-devices) asks Google. If the device's alarms, timers and settings still don't change, or the error comes back, [get help](#still-stuck) with debug logs.

Once the cause is fixed, you can reload the integration to ask Google straight away: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

If the log instead has an error such as `Failed to parse fetched alarms and timers for device Kitchen - API returned unknown json structure`, `Kitchen sent a reply to setup/assistant/alarms that isn't valid JSON`, `Kitchen sent a reply to setup/assistant/alarms/volume that isn't a JSON object` or `Kitchen sent an alarm volume that isn't a number`, the device answered with something the integration can't read. The entities that reply is for keep the values they had, which may be out of date, until a reply can be read again, and the device's other entities still update. If the error keeps coming back, [get help](#still-stuck) and attach [diagnostics](#download-diagnostics).

## An action or setting fails

Deleting alarms or timers, rebooting, turning Do Not Disturb on or off and setting the alarm volume fail with an error, rather than look successful, when a device may not have done what you asked. Most errors name the device and say why. To let your automation or script carry on after an error, see [Continue after an error](actions.md#continue-after-an-error).

### A delete fails

The four [delete actions](actions.md#if-a-delete-fails) show these errors:

- "Couldn't get the current alarms and timers from Kitchen, so nothing was deleted from it. Check that it's online and try again later". The device didn't send its current alarms and timers, for example because it has just become unreachable or, while polling is on, rejects its token, so it got no delete request.
- "Kitchen didn't confirm deleting the alarms or timers, so they may still be set. Check that it's online and try again later". The device stopped answering, refused or sent an unexpected reply, and may still have deleted them. Unless `skip_refresh` is `true`, the action asks the device for an update, which shows what it has.
- While [polling is turned off](configuration.md#turn-off-polling), when the device rejected its token, either error ends with this instead of "Check that it's online and try again later": "It rejected its token. Polling is turned off, so the integration doesn't ask Google again by itself: run the Refresh devices action, then try again". Run [Refresh devices](actions.md#refresh-devices) once, then try the delete again. If that doesn't help, see the same message under [A setting or reboot fails](#a-setting-or-reboot-fails).
- If several devices fail, one error names them all. When none of them sent its current alarms and timers: "Couldn't get the current alarms and timers from these devices, so nothing was deleted from them: Bedroom, Kitchen. Check that they're online and try again later". Otherwise: "Couldn't delete alarms or timers from these devices, or confirm that they were deleted: Bedroom, Kitchen. Check that they're online and try again later". While polling is turned off, the error is this instead when at least one of them rejected its token: "Couldn't delete alarms or timers from these devices, or confirm that they were deleted: Bedroom, Kitchen. At least one of them rejected its token. Polling is turned off, so the integration doesn't ask Google again by itself: run the Refresh devices action, check that the devices are online, then try again". Refresh devices updates all of them, so you don't need to know which one it was.
- "Couldn't find the alarm alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51 on the devices you targeted. It may already have gone off or been deleted", or the same for a timer. Every device the action checked sent its current list without the ID. A device that Home Assistant skipped, because its sensor is unavailable, hidden or disabled, may still have it. After a device didn't confirm a delete, this error on a retry means that the devices it checked no longer have it.
- "“alarm/123” isn't an alarm ID. Copy the ID, which starts with alarm/, from the alarms attribute of the device's alarms sensor", or the same for a timer. The ID doesn't start with `alarm/` or `timer/`, or has the wrong length, so no device was asked.

### A setting or reboot fails

Turning Do Not Disturb on or off, setting the alarm volume, pressing Reboot and the [Reboot device](actions.md#reboot-device) action show these errors:

- "Couldn't reach Living Room. Check that it's on and connected to your network, then try again". The device refused the connection or your network reports it as unreachable, or Home Assistant doesn't know its IP address.
- "Living Room didn't confirm that it did this: it didn't answer in time, or its answer was cut off. Check that it's online and try again". The device didn't answer within about 5 seconds, or its answer was cut off. The next update shows the device's current Do Not Disturb setting and alarm volume.
- "Living Room rejected its token. The integration keeps asking Google for one, so try again later". The integration keeps asking Google for a new token by itself, at the first update after a wait of up to 20 minutes; see [Alarms, timers or settings stop changing](#alarms-timers-or-settings-stop-changing). If Home Assistant asks you to [sign in again](#sign-in-again), do that first.
- "Living Room rejected its token. Polling is turned off, so the integration doesn't ask Google again by itself: run the Refresh devices action, then try again". Run [Refresh devices](actions.md#refresh-devices) once, then try the action again. If [System information](#check-system-information) shows **Retry not before**, a refresh before that time doesn't help. If the action still fails after that, see [Alarms, timers or settings stop changing](#alarms-timers-or-settings-stop-changing) to find out why the token is still being rejected. If Home Assistant asks you to [sign in again](#sign-in-again), do that first.
- "Living Room answered “not found”. It may still be starting up, so try again later, or it may not support this".
- "Couldn't do this on Living Room. For details, see the Home Assistant log". The device answered with another error, or the request failed for another reason. Open the [log](https://my.home-assistant.io/redirect/logs/) to see what it was.
- "These devices didn't confirm that they'll reboot: Bedroom, Kitchen. Check that they're online and try again later". Reboot device gives this when more than one device fails. It still reboots every device that answers.

### An action fails while the integration isn't loaded

While the integration isn't loaded, its [actions](actions.md), such as `google_home.delete_alarm`, fail whatever you target, and nothing is sent to your devices: "Config entry you@example.com for integration google_home is not loaded". Instead of you@example.com, it shows the integration's name, usually your Google account. This happens, for example, when Google didn't accept the master token at startup, while Home Assistant waits to try setting up the integration again, or while it's still setting it up after a restart.

Open **Settings** > **Devices & services** > **Google Home** to see why it isn't loaded, and if Home Assistant asks you to, [sign in again](#sign-in-again). Once the integration is loaded, the actions run again.

## Check System information

Home Assistant's System information has a **Google Home** section. It shows whether Home Assistant can reach Google, whether the integration has your devices from Google, and how many of them don't answer. Unlike [diagnostics](#download-diagnostics), it's there once you've added the integration, even if it then fails to set up. It isn't there while you add the integration for the first time, so it can't help when [adding the integration shows an error](#setup-fails). It isn't there either if your integration version is 1.16.0 or earlier.

To open it, go to **Settings** > **System** > **Repairs**, open the **⋮** menu and select **System information**.

The section shows:

- **Reach Google sign-in server** and **Reach Google device list server**: each shows `ok` if its host, `android.clients.google.com` or `googlehomefoyer-pa.googleapis.com`, answered a plain web request. Otherwise it shows `unreachable` or `timeout`, with a **more info** link to ["Couldn't reach Google"](#couldnt-reach-google). Any answer counts as `ok`, so `ok` doesn't show that Google accepts the sign-in or gives your devices.
- **Google's device list**:
    - `fetched`: the integration's devices come from a time when Google gave the list. It doesn't say when that was.
    - `not fetched`: Google hasn't given the list since the integration started, or a device's token changed and the list is to be fetched again.
    - `sign-in rejected`: Google rejected the master token during an earlier attempt, and no attempt has worked since. It stays even if Google later answers with a server error or asks to try later. [Sign in again](#sign-in-again).
- **Retry not before**: while the list needs to be fetched again and the integration waits after a failed attempt, the earliest time it asks Google again, at the first [update](configuration.md#change-the-update-interval) after that time. While [polling is turned off](configuration.md#turn-off-polling), it asks only when something updates the devices, such as [Refresh devices](actions.md#refresh-devices).
- **Polling for changes**: `false` while [polling is turned off](configuration.md#turn-off-polling). **Bluetooth tracking**: `true` if you [turned it on](bluetooth.md#turn-on-bluetooth-tracking) in the options.
- **Devices in Google's list** and **Devices not answering**: how many devices the integration has from Google, without those in homes that you [deselected](configuration.md#choose-homes), and how many of them don't answer. These show once Google has given the list, even an empty one.
    - A device without an IP address doesn't answer; see [Home Assistant can't reach your devices](#device-offline-or-not-compatible).
    - A device that missed 5 updates in a row counts until it answers again after it finishes starting.
    - A device that you [disabled](configuration.md#stop-checking-some-devices) isn't asked, so it isn't counted as not answering. It's still in Google's list.

If the integration fails to set up, the section shows only whether Home Assistant can reach Google. Open **Settings** > **Devices & services** > **Google Home** to see why setup failed.

The values are in English in every language. The Google Home section has no names, email addresses, IDs or IP addresses. **Copy** copies the whole of System information, though, with the other integrations' sections and details about your system: check the text before you post it.

## Download diagnostics

The diagnostics file shows:

- The integration's options.
- For each device: its model, whether it answers, whether Home Assistant has received its mDNS announcements since the integration loaded, its last reply about alarms and timers, as the device sent it, its firmware versions and release channel, whether it says a firmware update is waiting, its Wi-Fi signal strength, and its estimated last boot time (`booted_at`, before Home Assistant smooths it).
- Bluetooth tracking (`bluetooth`): whether each speaker is `excluded` (including disabled speakers) or `unsupported`, whether it has ever returned scan results since the integration last loaded (`answered`), whether its scans currently cover the presence window (`covers_presence_window`), and the end of its covered scan interval (`covered_until`, not the time results were read). Each tracker shows its latest `state`, including `unavailable`. The summary is `null` when Bluetooth tracking is off or no devices are tracked.
- How many other Cast devices on your network have announced themselves since the integration loaded but aren't in Google's device list, such as TVs with Chromecast built in, or speakers in another Google account. Only the number, not their names or addresses. Devices in homes that you [deselected](configuration.md#choose-homes) don't count.
- When you downloaded it.

Attach the file and [debug logs](#collect-debug-logs) when you [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose), and paste the **Google Home** section of [System information](#check-system-information). Versions 1.16.0 and earlier have neither the diagnostics file nor that section.

1. Go to **Settings** > **Devices & services** > **Google Home**.
2. Open the **⋮** menu and select **Download diagnostics**. Your browser downloads the file.

The menu has **Download diagnostics** only while the integration is set up. If setup fails, [collect debug logs](#collect-debug-logs) instead. Once the integration is added, [System information](#check-system-information) also works while it fails to set up.

!!! warning "Check the file before sharing it"

    The file replaces your email address, password, master token and Android ID, your devices' local tokens, IP addresses and Wi-Fi network names, and your known hosts with `**REDACTED**`. It keeps your device names and the times and labels of your alarms and timers. Home Assistant also adds details about your system, such as its version, your time zone and the custom integrations you use. Open the file and replace anything you don't want to share with `xxx` before you attach it to a public issue.

## Collect debug logs

Debug logs show what the integration is doing. Attach them when you [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose).

1. Go to **Settings** > **Devices & services** > **Google Home**.
2. Open the **⋮** menu and select **Enable debug logging**.
3. Reproduce the problem.
4. Open the **⋮** menu again and select **Disable debug logging**. Your browser downloads the log file.

While you add the integration for the first time, it has no **⋮** menu yet. Instead, run this action in [**Settings** > **Tools** > **Actions**](https://my.home-assistant.io/redirect/tools_actions/), then try to add the integration again. The action also logs `glocaltokens`, the library the integration uses to sign in:

```yaml
action: logger.set_level
data:
  custom_components.google_home: debug
  glocaltokens: debug
```

Then open the [log](https://my.home-assistant.io/redirect/logs/). It first shows only warnings and errors: select **Download logs** to save the whole log, or open its **⋮** menu and select **Show raw logs**.

!!! warning "Remove secrets before sharing logs"

    Debug logs can contain your email address, tokens and the IP addresses of your devices. Replace them with `xxx` before you post the log.

## Still stuck

Search the [issues](https://github.com/leikoilja/ha-google-home/issues?q=is%3Aissue) for your problem. If nobody has reported it, [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with your [diagnostics](#download-diagnostics), the Google Home section of [System information](#check-system-information) and [debug logs](#collect-debug-logs). Versions 1.16.0 and earlier have neither the diagnostics file nor that section.

# Troubleshooting

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

## Setup fails

When you [sign in again](installation.md#sign-in-again), the form shows these errors too.

### "Username or password is incorrect"

Older versions of the integration signed in with an app password, which Google rejects for many accounts. [Update the integration](https://github.com/leikoilja/ha-google-home/releases/latest) and use [browser sign-in](installation.md#browser-sign-in) instead.

### "Google didn't accept the cookie"

The `oauth_token` cookie expires within minutes and works only once. Close the private window and repeat [browser sign-in](installation.md#browser-sign-in) from step 1, then paste the new cookie straight away. Copy the whole value, starting with `oauth2_4/`.

### "Google didn't accept the master token"

Check that you pasted the token exactly as you got it. If it was correct before and has stopped working, for example after you changed your Google password, Google no longer accepts it: use [browser sign-in](installation.md#browser-sign-in) instead. If the integration is already set up, [sign in again](installation.md#sign-in-again) rather than deleting it.

### "Google didn't accept the sign-in"

Google refused the cookie or master token for a reason that the integration doesn't know or without a reason, or it answered in a way that the integration doesn't understand. Open the [log](https://my.home-assistant.io/redirect/logs/) and find the warning that starts with `Failed to sign in`; Google's reason, if it gave one, is at the end. [Open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with that line.

### "Couldn't reach Google"

Home Assistant couldn't connect to Google, or Google didn't answer in time. Check that Home Assistant is connected to the internet. The integration signs in at `android.clients.google.com`, and after setup gets your devices from `googlehomefoyer-pa.googleapis.com`. If a DNS filter or firewall, such as Pi-hole or AdGuard Home, blocks either, allow it. Then try again. With browser sign-in, get a new cookie if a few minutes have passed.

### "Google is busy or is limiting sign-ins"

Google answered with a server error, or asked the integration to slow down. This doesn't mean that your cookie or master token is wrong. Wait a few minutes, then sign in again. With browser sign-in, get a new cookie, as the old one expires within minutes.

## Signing in again fails

The form for signing in again shows the same errors as setup; see [Setup fails](#setup-fails).

### "You signed in to a different Google account"

Google reports that you signed in to another account than the one the integration uses, so Home Assistant didn't change anything. To sign in with the original account:

- If the integration is still running, you don't need to reload it. Home Assistant asks you to sign in again by itself when the integration next updates your devices, every 15 seconds by default. Then select **Reconfigure** and [sign in again](installation.md#sign-in-again).
- If the integration isn't running, for example when Home Assistant restarted and shows **Failed to set up** for it, reload it: go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu and select **Reload**. Then select **Reconfigure** and sign in again.

Reloading also works while the integration is running, but it stops the integration: its entities are unavailable until you sign in again.

To use that account instead, delete the integration and add it again.

Version 1.13 and older saved the email address you typed when you set up the integration. If that isn't your Google account's primary address, for example because you typed an alternate address, and the integration isn't named after the primary address either, Home Assistant refuses your own account. To keep the integration, name it after your primary address: go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu, select **Rename** and enter the address. Then sign in again as described above. Otherwise, delete the integration and add it again.

## Devices are missing

### No devices appear

The integration adds only Google Cast devices, such as Google speakers and displays. Lights, plugs, thermostats and other devices in your Google Home app don't appear; see [Other Google Home devices](index.md#other-google-home-devices).

If you signed in with a Google Workspace account, such as many work and school accounts, it can't be a member of your home: [Google doesn't allow inviting Workspace accounts](https://support.google.com/googlehome/answer/9155535). Sign in with a Gmail account, one ending in `@gmail.com`, that is a member of your home instead. Some users with personal Google accounts using non-Gmail addresses have also reported missing devices; [switching to a Gmail account resolved the problem](https://github.com/leikoilja/ha-google-home/issues/1014#issuecomment-4466736100).

The Google account you signed in with must be a member of the home your devices belong to. Open the Google Home app with that account and check that the devices are listed. If not, [invite the account](https://support.google.com/googlenest/answer/9155535) to your home and reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

If Google didn't give the integration your devices when it started, for example because Google was busy, the integration starts without devices, and the log shows `Failed to fetch Google's device list` with Google's reason. The integration asks Google again until it gets your devices. The minimum retry delay grows from 1 minute to 20 minutes; the first [update](installation.md#change-the-update-interval) after the delay makes the attempt, so actual gaps can be longer. To ask Google straight away, reload the integration.

### No alarms or timers sensors

The integration adds the alarms sensor, timers sensor, Do Not Disturb switch and alarm volume for a device once the device answers. Until then, a device that is offline, or that doesn't support these features, has only a device sensor and a reboot button.

When the device answers, the integration adds the missing entities:

- If the device sensor shows an IP address, this happens at the next update, unless the integration has found that the device has none of these features.
- If the device sensor is unavailable, the integration doesn't know the device's IP address. It looks for the device again every 20 minutes, when it asks Google for your devices.

If you don't want to wait, make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. If that doesn't help, restart the Google Home device and then Home Assistant.

#### Devices without alarms and timers

Some Cast devices, such as Chromecast Audio, have no alarms, timers, Do Not Disturb or alarm volume. Once the integration finds that a device has none of these features, it stops asking the device for them. The device keeps only its device sensor and reboot button. If it had the other entities, they become unavailable.

The integration decides this from how the device answers, not from a list of models:

- The device answers "not found" when asked for its alarms, and still does at an update at least 10 minutes later. A device that is starting answers "not found" for a while too, so one answer isn't enough.
- In that later update, the device's information lists its features without Google Assistant.

Until then, the integration keeps asking the device on every update, even while it doesn't answer, for example while it restarts.

When it stops asking a device, the [debug log](#collect-debug-logs) shows a line like this, with your device's name and model:

```
Stereo (hardware='Chromecast Audio') still answers 404 for alarms after at least 10 minutes, and its info lists its features without Google Assistant. It won't be asked for alarms, timers and settings until the integration is reloaded.
```

The integration checks such a device again only when it starts: when Home Assistant restarts, or when you reload the integration. While it runs, it doesn't ask the device again, even if the device restarts or a firmware update adds these features. The `google_home.refresh_devices` action doesn't check it again either.

If the integration stopped asking a device that has alarms and timers, or a device gains these features, make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. The integration asks the device as usual again and adds the entities once it answers. If its alarms still answer "not found" 10 minutes later, and its information still lists no Google Assistant, the integration stops asking it again.

### Device offline or not compatible

If the debug log shows this message for **all** of your devices, Home Assistant can't find them on your network:

```
Failed to fetch timers/alarms information from device Kitchen. We could not determine its IP address, the device is either offline or is not compatible Google Home device. Will try again later.
```

The integration finds your devices on your network with multicast DNS (mDNS) and then talks to them directly. Only signing in and getting device tokens go through Google. Check that:

- Home Assistant and the devices are on the same network.
- If Home Assistant runs in Docker, the container uses `host` network mode.
- If your devices are on a separate network or VLAN, your router forwards mDNS between the networks, and Home Assistant can reach the devices on TCP port 8443.

If mDNS can't reach your devices but Home Assistant can reach them on TCP port 8443, add their IP addresses as [known hosts](installation.md#add-devices-on-another-network) instead.

If only some devices show the message, those devices are offline or don't support this integration.

## A device stops updating

If a device's alarms, timers and settings stop changing in Home Assistant while its entities stay available, check the `available` attribute of its [device sensor](entities.md#device-sensor). If it's `false` while the device is on, the [debug log](#collect-debug-logs) shows why. A line such as `Kitchen rejected its token` means that the device refuses the token the integration has for it.

A device's token can change, for example when the device restarts. The integration then gets the new token from Google straight away. If Google can't give it, the device's entities keep the values they had, and the integration asks Google again until it can. The minimum retry delay grows from 1 minute to 20 minutes; the first [update](installation.md#change-the-update-interval) after the delay makes the attempt, so actual gaps can be longer. While Google can't be reached at all, each update that asks Google fails, which makes every entity of the integration unavailable until the next update.

Check that Home Assistant is connected to the internet; see ["Couldn't reach Google"](#couldnt-reach-google). To ask Google straight away, reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

## Still stuck

Search [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions) and the [issues](https://github.com/leikoilja/ha-google-home/issues?q=is%3Aissue) for your problem. If nobody has reported it, ask in [Q&A](https://github.com/leikoilja/ha-google-home/discussions/categories/q-a), or [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with your [debug logs](#collect-debug-logs).

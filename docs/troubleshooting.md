# Troubleshooting

## Collect debug logs

Debug logs show what the integration is doing. Attach them when you [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose).

1. Go to **Settings** > **Devices & services** > **Google Home**.
2. Open the **⋮** menu and select **Enable debug logging**.
3. Reproduce the problem.
4. Open the **⋮** menu again and select **Disable debug logging**. Your browser downloads the log file.

If setup fails, the integration has no **⋮** menu yet. Instead, run this action in [**Developer tools** > **Actions**](https://my.home-assistant.io/redirect/developer_services/), then try to add the integration again and open the [log](https://my.home-assistant.io/redirect/logs/). The action also logs `glocaltokens`, the library the integration uses to sign in:

```yaml
action: logger.set_level
data:
  custom_components.google_home: debug
  glocaltokens: debug
```

!!! warning "Remove secrets before sharing logs"

    Debug logs can contain your email address, tokens and the IP addresses of your devices. Replace them with `xxx` before you post the log.

## Setup fails

### "Username or password is incorrect"

Older versions of the integration signed in with an app password, which Google rejects for many accounts. [Update the integration](https://github.com/leikoilja/ha-google-home/releases/latest) and use [browser sign-in](installation.md#browser-sign-in) instead.

### "Google didn't accept the cookie"

The `oauth_token` cookie expires within minutes and works only once. Close the private window and repeat [browser sign-in](installation.md#browser-sign-in) from step 1, then paste the new cookie straight away. Copy the whole value, starting with `oauth2_4/`.

### "Master token invalid"

Paste the whole token, including the `aas_et/` at the start. If it was correct before and has stopped working, for example after you changed your Google password, delete the integration and add it again with [browser sign-in](installation.md#browser-sign-in).

## Devices are missing

### No devices appear

The integration adds only Google Cast devices, such as Google speakers and displays. Lights, plugs, thermostats and other devices in your Google Home app don't appear; see [Other Google Home devices](index.md#other-google-home-devices).

If you signed in with a Google Workspace account, such as many work and school accounts, it can't be a member of your home: [Google doesn't allow inviting Workspace accounts](https://support.google.com/googlehome/answer/9155535). Sign in with a Gmail account, one ending in `@gmail.com`, that is a member of your home instead. Some users with personal Google accounts using non-Gmail addresses have also reported missing devices; [switching to a Gmail account resolved the problem](https://github.com/leikoilja/ha-google-home/issues/1014#issuecomment-4466736100).

The Google account you signed in with must be a member of the home your devices belong to. Open the Google Home app with that account and check that the devices are listed. If not, [invite the account](https://support.google.com/googlenest/answer/9155535) to your home and reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

### No alarms or timers sensors

The integration adds the alarms sensor, timers sensor, Do Not Disturb switch and alarm volume for a device once the device answers. Until then, a device that is offline, or that doesn't support these features, has only a device sensor and a reboot button.

When the device answers, the integration adds the missing entities:

- If the device sensor shows an IP address, this happens at the next update.
- If the device sensor is unavailable, the integration doesn't know the device's IP address. It looks for the device again every 10 updates, which is every 30 minutes with the default [update interval](installation.md#change-the-update-interval).

If you don't want to wait, make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. If that doesn't help, restart the Google Home device and then Home Assistant.

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

## Still stuck

Search [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions) and the [issues](https://github.com/leikoilja/ha-google-home/issues?q=is%3Aissue) for your problem. If nobody has reported it, ask in [Q&A](https://github.com/leikoilja/ha-google-home/discussions/categories/q-a), or [open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose) with your [debug logs](#collect-debug-logs).

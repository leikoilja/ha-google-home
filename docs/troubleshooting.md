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

1. Check that the username and app password belong to the same Google account.
2. Use an [app password](installation.md#create-an-app-password), not your normal password.
3. If it still fails, Google is rejecting this sign-in method for your account. That happens even with correct details. [Get a master token](installation.md#get-a-master-token) and use it instead.

### "The setting you are looking for is not available for your account"

Google shows this on the App passwords page when your account can't create app passwords. Usually 2-Step Verification is off. [Turn it on](https://myaccount.google.com/signinoptions/twosv) and try again.

Accounts that use only security keys, use Advanced Protection, or belong to work or school can't create app passwords at all. Use a [master token](installation.md#get-a-master-token) instead.

### "Master token invalid"

Paste the whole token, including the `aas_et/` at the start. If it was correct before and has stopped working, for example after you changed your Google password, get a new master token, then delete the integration and add it again.

## Devices are missing

### No devices appear

The Google account you signed in with must be a member of the home your devices belong to. Open the Google Home app with that account and check that the devices are listed. If not, [invite the account](https://support.google.com/googlenest/answer/9155535) to your home and reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**.

### No alarms or timers sensors

The integration creates the alarms sensor, timers sensor, Do Not Disturb switch and alarm volume only for devices it can reach when it starts. If a device was offline then, it has only a device sensor.

Make sure the device is online, then reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. If that doesn't help, restart the Google Home device and then Home Assistant.

### Device offline or not compatible

If the debug log shows this message for **all** of your devices, Home Assistant can't find them on your network:

```
Failed to fetch timers/alarms information from device Kitchen. We could not determine its IP address, the device is either offline or is not compatible Google Home device. Will try again later.
```

The integration finds your devices on your network with multicast DNS (mDNS) and then talks to them directly. Only signing in and getting device tokens go through Google. Check that:

- Home Assistant and the devices are on the same network.
- If Home Assistant runs in Docker, the container uses `host` network mode.
- If your devices are on a separate network or VLAN, your router forwards mDNS between the networks, and Home Assistant can reach the devices on TCP port 8443.

If only some devices show the message, those devices are offline or don't support this integration.

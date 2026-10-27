# Getting Started

## Before you start

You need:

- Home Assistant 2026.10.0 or later.
- Google speakers or displays, such as a Nest Mini, Nest Audio or Nest Hub. The integration doesn't add the other devices in your Google Home app, such as lights or thermostats. See [Other Google Home devices](index.md#other-google-home-devices).
- A Google account that is a member of your home in the Google Home app, or of each home if your devices are in several. Open the Google Home app with that account and check that your devices are listed.
- Home Assistant on the same local network as your devices, so the integration finds them automatically. If you run Home Assistant in Docker, set the container's network mode to `host`, as the [official installation guide](https://www.home-assistant.io/installation/linux) does. If your devices are on another network, or the container can't use `host` mode, [add them as known hosts](#add-devices-on-another-network) instead.

!!! tip "Use a separate Google account"

    The integration needs credentials that give full access to the Google account you sign in with. Instead of your main account, create a new Gmail account, one ending in `@gmail.com`, and [invite it to your home](https://support.google.com/googlenest/answer/9155535) in the Google Home app. If its credentials leak, only that account is exposed. See [issue #124](https://github.com/leikoilja/ha-google-home/issues/124#issuecomment-921773489) for the discussion.

    [Google Workspace accounts can't be invited to a home](https://support.google.com/googlehome/answer/9155535). Some users with personal Google accounts using non-Gmail addresses have also reported missing devices; [switching to a Gmail account resolved the problem](https://github.com/leikoilja/ha-google-home/issues/1014#issuecomment-4466736100).

## Install the integration

=== "HACS (recommended)"

    1. Open HACS in Home Assistant.
    2. Search for **Google Home** and open it.
    3. Select **Download**.
    4. Restart Home Assistant.

    HACS tells you when an update is available.

=== "Manual"

    1. Download the source code ZIP of the [latest release](https://github.com/leikoilja/ha-google-home/releases/latest) and unpack it.
    2. Find your Home Assistant configuration folder, the one that contains `configuration.yaml`. If it has no `custom_components` folder, create one.
    3. Copy the `custom_components/google_home` folder from the release into that `custom_components` folder.
    4. Restart Home Assistant.

    To update, repeat these steps with the new release. Delete the old `google_home` folder first.

## Add the integration

1. [Add the Google Home integration](https://my.home-assistant.io/redirect/config_flow_start?domain=google_home), or go to **Settings** > **Devices & services** > **Add integration** and search for **Google Home**.
2. Choose how to sign in, and follow its steps below:
    - **Browser sign-in (recommended):** you sign in to Google in a desktop browser and copy a cookie from it.
    - **Master token:** if you already have one, for example from another tool.

Home Assistant then adds a device for each Google Cast device in your home, with the [entities](entities.md) for it. Devices that have no alarms or timers, such as an NVIDIA Shield, get only a device sensor and a reboot button.

If Google stops accepting the sign-in, [sign in again](#sign-in-again). To use another Google account, delete the integration and add it again.

!!! warning "Keep your sign-in details secret"

    The cookie and the master token each give access to your Google account. Don't share them or post them in an issue.

### Browser sign-in

You need a computer with a desktop browser, such as Chrome, Edge or Firefox. Phones don't show the cookies you need.

1. In a private browser window, open [accounts.google.com/EmbeddedSetup](https://accounts.google.com/EmbeddedSetup) and sign in with the Google account you want to use.
2. Accept the prompt. The page may then keep loading forever; that is expected.
3. Press `F12`, or `Cmd+Option+I` on a Mac, to open the browser's developer tools. Then open the cookies for `https://accounts.google.com`:
    - Chrome or Edge: **Application** > **Cookies**. If you can't see the **Application** tab, select `>>` to show more tabs.
    - Firefox: **Storage** > **Cookies**.
4. Find the `oauth_token` row, double-click its value to select all of it, and copy it. It starts with `oauth2_4/`.
5. In Home Assistant, select **Browser sign-in (recommended)**, paste the cookie into **oauth_token cookie**, and select **Submit**.

The cookie expires within minutes and works only once, so paste it straight away. If setup says "Google didn't accept the cookie", close the private window and repeat from step 1.

Home Assistant exchanges the cookie for a master token, names the entry after the account Google reports, and keeps only the master token.

### Master token

Select **Master token**, paste the token into **Google account master token**, and select **Submit**. A master token starts with `aas_et/` and is 223 characters long. The integration looks up which Google account the token belongs to and names the entry after it.

## Sign in again

Google can stop accepting the integration's sign-in, for example after you change your Google account's password. Home Assistant then reports that authentication expired, and the Google Home card in **Settings** > **Devices & services** shows **Reconfigure**. Sign in again with the same Google account to keep your devices, their entity IDs and your automations:

1. Go to **Settings** > **Devices & services** and, on the Google Home card, select **Reconfigure**.
2. Choose how to sign in, and follow the same steps as for [browser sign-in](#browser-sign-in) or a [master token](#master-token). Use the same Google account as before.

Home Assistant then reloads the integration with the new sign-in.

Sign in again soon. Until you do, the integration can't get the device list or new device tokens from Google. It keeps asking your devices for updates, and some may keep answering, but what Home Assistant shows for your devices can be out of date. After Home Assistant restarts, the integration doesn't start until you sign in again.

- If you closed the sign-in window, select **Reconfigure** again to continue where you left off.
- To choose another way to sign in after you picked one, reload the integration: go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu and select **Reload**. Sign-in starts again from the choice, but the integration stops until you finish, and its entities are unavailable.
- If Home Assistant says that you signed in to a different Google account, see [Troubleshooting](troubleshooting.md#you-signed-in-to-a-different-google-account).

## Change the update interval

The integration checks your devices for changes every 15 seconds by default.

To change the interval, go to **Settings** > **Devices & services** > **Google Home** and select **Configure**. Shorter intervals update alarms and timers sooner but send more requests to your devices.

If a speaker or display with alarms and timers often shows `false` in the `available` attribute of its [device sensor](entities.md#device-sensor) while it's on, increase the interval, for example to 180 seconds, the default before version 1.16. A device without alarms and timers, such as a Chromecast Audio, shows `false` there anyway, because it answers "not found" when asked for alarms; see [Devices without alarms and timers](troubleshooting.md#devices-without-alarms-and-timers).

**Configure** shows the interval in use. If you saved these options in version 1.15 or older, for example to add known hosts, it's the interval you saved, which was 180 seconds unless you changed it. To use the new default, enter 15 and select **Submit**.

To update immediately, use the [Refresh devices](actions.md#refresh-devices) action.

## Add a device

When you add a speaker or display in the Google Home app, the integration normally adds it within about 20 minutes, without a reload. It asks Google for your devices at the first update 20 minutes after it last asked. If it can't reach Google then, it tries again 20 minutes later.

To add the device straight away, reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. The integration then asks Google for your devices. The device appears only once Google lists it, and some of its entities only once Home Assistant can reach it; see [Entities](entities.md).

To add back a speaker or display that you removed from the Google Home app:

1. Wait until the integration has noticed the removal, or reload it; see [Remove a device](#remove-a-device).
2. Delete the old device in Home Assistant: open the device's page, open the **⋮** menu and select **Delete**. If you skip this, the new device's entities get IDs such as `sensor.kitchen_alarms_2` instead of `sensor.kitchen_alarms`.
3. [Factory reset the device](https://support.google.com/googlenest/answer/7073477). Restarting it isn't enough.
4. Set it up again in the Google Home app. Give it the same name to keep its entity IDs.

Google gives the device a new ID, so the integration adds it as a new device, normally within about 20 minutes.

If you deleted a device in Home Assistant and the Google Home app lists it again without a factory reset, the integration doesn't add it back by itself: reload the integration.

## Add devices on another network

The integration finds your devices on your network with multicast DNS (mDNS). mDNS usually doesn't reach other networks, such as a separate VLAN for smart home devices, or a Home Assistant container that doesn't use `host` network mode. Those devices then have only a [device sensor](entities.md#device-sensor) and a [reboot button](entities.md#reboot-button), and both are unavailable.

For devices on another network, Home Assistant needs:

- **A way to find the devices.** Choose one:
    - Give Home Assistant a network interface on the devices' network, such as a second network adapter or a VLAN interface. Home Assistant usually uses only one interface for mDNS, so go to **Settings** > **System** > **Network**, clear **Autoconfigure** under **Network adapter**, also select the interface on the devices' network, select **Save** and restart Home Assistant. With this interface, Home Assistant also connects to the devices directly, so a firewall on your router doesn't need to allow TCP 8443.
    - Set up an mDNS reflector or repeater between the networks, for example on your router.
    - Add the devices' IP addresses as known hosts, as described below.
- **TCP port 8443 on each device.** The integration connects to the devices over HTTPS on this port. If a firewall is in between, allow these connections from Home Assistant and their replies. A rule that allows only the Google Cast port, TCP 8009, isn't enough. The devices don't need to connect to Home Assistant.
- **Internet access for Home Assistant.** The integration gets the device list and the devices' access tokens from Google when it loads, and again later, for example when the tokens expire.

To add devices as known hosts:

1. Go to **Settings** > **Devices & services** > **Google Home** and select **Configure**.
2. Under **Known hosts**, add the IP address of each device that the integration can't find.
3. Select **Submit**. The integration reloads, asks each address which device it is, and uses the address for that device.

Give these devices fixed IP addresses in your router, so the addresses don't change. For a speaker pair, add the addresses of both speakers. Only the speaker that leads the pair reports it, so the integration uses that one and ignores the other.

## Remove a device

When you remove a device from the Google Home app or factory reset it, the integration normally notices within about 20 minutes, when it next asks Google for your devices, and the device's entities become unavailable. Removing a device from the Google Home app doesn't reset it: it stays on your network, and the integration keeps updating it until it next asks Google for your devices. To make the integration notice straight away, reload it: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. Once it has noticed, open the device's page in Home Assistant, open the **⋮** menu and select **Delete**.

Home Assistant offers **Delete** for every device of the integration, but you can't delete one that Google still lists in your home, even if it shows as unavailable: it would come back the next time the integration loads. Home Assistant then shows "Failed to remove device entry, rejected by integration".

To use a removed device again, factory reset it first; see [Add a device](#add-a-device).

## Remove the integration

1. Go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu and select **Delete**. Home Assistant deletes the master token it stored.
2. If you installed with HACS, open HACS, select **Google Home**, open the **⋮** menu and select **Remove**. If you installed manually, delete the `custom_components/google_home` folder.
3. Restart Home Assistant.

Deleting the integration doesn't stop the master token from working, and the integration can't revoke it. If the token might have been copied, for example from a Home Assistant backup:

- If you created a separate Google account for the integration, delete that account.
- Otherwise, [change the Google account's password](https://support.google.com/accounts/answer/41078). Google then signs you out on most devices and apps, but it lists exceptions, so this isn't guaranteed to stop the master token.

# Getting Started

## Before you start

You need:

- Home Assistant 2026.10.0 or later.
- Google speakers or displays, such as a Nest Mini, Nest Audio or Nest Hub. The integration doesn't add the other devices in your Google Home app, such as lights or thermostats. See [Other Google Home devices](index.md#other-google-home-devices).
- A Google account that is a member of your home in the Google Home app. Open the Google Home app with that account and check that your devices are listed.
- Home Assistant on the same local network as your devices. If you run Home Assistant in Docker, set the container's network mode to `host`, as the [official installation guide](https://www.home-assistant.io/installation/linux) does. Otherwise the integration can't find your devices.

!!! tip "Use a separate Google account"

    The integration needs credentials that give full access to the Google account you sign in with. Instead of your main account, create a new Google account and [invite it to your home](https://support.google.com/googlenest/answer/9155535) in the Google Home app. If its credentials leak, only that account is exposed. See [issue #124](https://github.com/leikoilja/ha-google-home/issues/124#issuecomment-921773489) for the discussion.

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

Home Assistant then adds a device for each Google Cast device in your home, with the [entities](entities.md) for it. Devices that have no alarms or timers, such as an NVIDIA Shield, get only a device sensor.

To change the account or sign in again, delete the integration and add it again.

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
5. In Home Assistant, select **Browser sign-in (recommended)**. Enter the account's email address in **Google account email address**, paste the cookie into **oauth_token cookie**, and select **Submit**.

The cookie expires within minutes and works only once, so paste it straight away. If setup says "Google didn't accept the cookie", close the private window and repeat from step 1.

Home Assistant exchanges the cookie for a master token and keeps only that.

### Master token

Select **Master token**, paste the token into **Google account master token**, and select **Submit**. A master token starts with `aas_et/` and is 223 characters long. The integration looks up which Google account the token belongs to and names the entry after it.

## Change the update interval

The integration checks your devices for changes every 180 seconds.

To change the interval, go to **Settings** > **Devices & services** > **Google Home** and select **Configure**. If your devices time out, increase the interval until they stay stable. Shorter intervals update alarms and timers sooner but send more requests to your devices.

To update immediately, use the [Refresh devices](actions.md#refresh-devices) action.

## Remove the integration

1. Go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu and select **Delete**. Home Assistant deletes the master token it stored.
2. If you installed with HACS, open HACS, select **Google Home**, open the **⋮** menu and select **Remove**. If you installed manually, delete the `custom_components/google_home` folder.
3. Restart Home Assistant.

Deleting the integration doesn't stop the master token from working. If the token might have been copied, for example from a Home Assistant backup, change the Google account's password: Google then signs you out on most devices and apps, which stops the master token. If you created a separate Google account for the integration, you can delete that account instead.

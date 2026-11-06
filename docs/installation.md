# Getting Started

## Before you start

You need:

- Home Assistant 2026.11.0 or later.
- Google speakers or displays. The integration is known to work with the original Google Home, Google Home Mini, Nest Mini, Nest Audio and Nest Hub. It doesn't add the other devices in your Google Home app, such as lights or thermostats. See [Other Google Home devices](other-integrations.md#other-google-home-devices).
- A Google account that is a member of your home in the Google Home app, or of each home if your devices are in several. Open the Google Home app with that account and check that your devices are listed.
- Home Assistant on the same local network as your devices, so the integration finds them automatically. If you run Home Assistant in Docker, set the container's network mode to `host`, as the [official installation guide](https://www.home-assistant.io/installation/linux) does. If your devices are on another network, or the container can't use `host` mode, [add them as known hosts](configuration.md#add-devices-on-another-network) instead.

!!! tip "Use a separate Google account"

    The integration needs credentials that give full access to the Google account you sign in with. Instead of your main account, create a new Gmail account, one ending in `@gmail.com`, and [invite it to your home](https://support.google.com/googlenest/answer/9155535) in the Google Home app. If its credentials leak, only that account is exposed. See [issue #124](https://github.com/leikoilja/ha-google-home/issues/124#issuecomment-921773489) for the discussion.

    [Google Workspace accounts can't be invited to a home](https://support.google.com/googlehome/answer/9155535), and some personal accounts with non-Gmail addresses have had missing devices; see [No devices appear](troubleshooting.md#no-devices-appear).

## Install the integration

=== "Marketplace (recommended)"

    The Marketplace replaced HACS in Home Assistant 2026.11. If you installed the integration with HACS, Home Assistant moved it to the Marketplace when you updated Home Assistant, so you don't need to install it again.

    The first time you open the Marketplace, it asks you to accept a notice about community content before you can search or install: select **I understand the risks and agree**, then **Continue**.

    1. [Open Google Home in the Marketplace](https://my.home-assistant.io/redirect/marketplace_repository/?owner=leikoilja&repository=ha-google-home&category=integration), or go to **Settings** > **Marketplace**, search for **Google Home** and open it.
    2. Select **Install**, then **Install** again in the dialog.

    Home Assistant then opens the integration's setup: continue from step 2 of [Add the integration](#add-the-integration). If the Marketplace says that Home Assistant needs a restart instead, select **Restart Home Assistant**, then add the integration.

    Updates appear in **Settings**, with Home Assistant's own updates. After you install one, restart Home Assistant; a repair offers to do it for you.

=== "Manual"

    1. Download the source code ZIP of the [latest release](https://github.com/leikoilja/ha-google-home/releases/latest) and unpack it.
    2. Find your Home Assistant configuration folder, the one that contains `configuration.yaml`. If it has no `custom_components` folder, create one.
    3. Copy the `custom_components/google_home` folder from the release into that `custom_components` folder.
    4. Restart Home Assistant.

    To update, repeat these steps with the new release. Delete the old `google_home` folder first.

To see which version you have, open [**Settings** > **Devices & services** > **Google Home**](https://my.home-assistant.io/redirect/integration/?domain=google_home). The version is under the title.

## Add the integration

1. [Add the Google Home integration](https://my.home-assistant.io/redirect/config_flow_start?domain=google_home), or go to **Settings** > **Devices & services** > **Add integration** and search for **Google Home**. If that page shows a **Google Home** card under **Discovered**, you can select **Add** on it instead.
2. Choose how to sign in, and follow its steps below:
    - **Browser sign-in (recommended):** you sign in to Google in a desktop browser and copy a cookie from it.
    - **Master token:** if you already have one, for example from another tool.
3. If your Google account is a member of several homes, choose the homes whose speakers and displays to add, and select **Submit**. All homes are selected at first. If Google doesn't give the integration your homes at that moment, Home Assistant skips this step and adds every home's devices. Either way, you can change this later; see [Choose homes](configuration.md#choose-homes).

Home Assistant then adds a device for each Google Cast device in the homes you chose, with the [entities](entities.md) for it. Devices that have no alarms or timers, such as an NVIDIA Shield, get fewer entities. A speaker pair is added once, as one device with the pair's name from the Google Home app.

Home Assistant shows the **Google Home** card under **Discovered** when it finds a Google Cast device on your network and the integration isn't set up. The card doesn't mean that your account or devices were found: you still sign in. If you don't want to set up the integration, select **Ignore**. If you delete the integration but keep it installed, the card can come back.

!!! warning "Keep your sign-in details secret"

    The cookie and the master token each give access to your Google account. Don't share them or post them in an issue.

### Browser sign-in

You need a computer with a desktop browser, such as Chrome, Edge or Firefox. Phones don't show the cookies you need. You sign in on Google's own page, so you don't need an app password, a script or any change to 2-Step Verification.

1. In a private browser window, open [accounts.google.com/EmbeddedSetup](https://accounts.google.com/EmbeddedSetup) and sign in with the Google account you want to use.
2. Accept the prompt. The page may then keep loading forever; that is expected.
3. Press `F12`, or `Cmd+Option+I` on a Mac, to open the browser's developer tools. Then open the cookies for `https://accounts.google.com`:
    - Chrome or Edge: **Application** > **Cookies**. If you can't see the **Application** tab, select `>>` to show more tabs.
    - Firefox: **Storage** > **Cookies**.
4. Find the `oauth_token` row, double-click its value to select all of it, and copy it. It starts with `oauth2_4/`.
5. In Home Assistant, on the **Browser sign-in** form, paste the cookie into **oauth_token cookie** and select **Submit**.

The cookie can expire quickly and works only once, so paste it straight away. If setup asks for a new cookie, close the private window and repeat from step 1.

Home Assistant exchanges the cookie for a master token, names the entry after the account Google reports, and keeps only the master token.

### Master token

Select **Master token**, paste the token into **Google account master token**, and select **Submit**. A master token starts with `aas_et/` and is 223 characters long. The integration looks up which Google account the token belongs to and names the entry after it.

## Check that it works

Set a timer on one speaker and check that Home Assistant shows it:

1. Go to **Settings** > **Devices & services** > **Google Home** and select one of your speakers or displays.
2. On its device page, find the **Timers** sensor. It shows **Unavailable** while no timer is running; that is expected, not an error. If **Timers** shows a time, a timer is already running on that speaker: choose another speaker, or wait until the timer finishes.
3. Ask that speaker to set a timer, for example "Hey Google, set a timer for 10 minutes". A timer belongs to the speaker that set it, so ask the one whose page you opened.
4. Wait for the next update. The integration checks your devices every 15 seconds, unless you [changed the update interval](configuration.md#change-the-update-interval). **Timers** then shows when the timer goes off.
5. Say "Hey Google, cancel the timer". After the next update, **Timers** shows **Unavailable** again.

If it doesn't work:

- If the Google Home integration shows no devices in Home Assistant, see [No devices appear](troubleshooting.md#no-devices-appear).
- If the speaker has only a device sensor, a reboot button, an update sensor, and disabled Wi-Fi and uptime sensors, Home Assistant hasn't reached it yet, or it has no alarms and timers. See [No alarms or timers sensors](troubleshooting.md#no-alarms-or-timers-sensors).
- If **Timers** still shows **Unavailable** after the update, check that you asked the speaker whose page you opened, and that it's on and connected to your network. Then see [A device stops updating](troubleshooting.md#a-device-stops-updating).

## Use it in an automation

[When a timer finishes](automations.md#when-a-timer-finishes) sends a notification to your phone when a speaker's timer finishes. [Automation examples](automations.md) has more, such as turning on lights before an alarm.

The examples use entity IDs such as `sensor.kitchen_timers`. Replace them with your own: on the device page, select **Timers**, then the settings (gear) icon. **Entity ID** shows the sensor's ID. If it has the room name twice, see [Room name twice in entity IDs](entities.md#room-name-twice-in-entity-ids).

## Manage the integration

- [Change the update interval](configuration.md#change-the-update-interval){#change-the-update-interval}, for example if a speaker often misses updates.
- [Add a device](configuration.md#add-a-device){#add-a-device} that you set up in the Google Home app later.
- [Add devices on another network](configuration.md#add-devices-on-another-network){#add-devices-on-another-network}, such as a separate VLAN.
- [Choose homes](configuration.md#choose-homes){#choose-homes} whose devices to add, if your account is a member of several.
- [Remove a device](configuration.md#remove-a-device){#remove-a-device}, and what happens when you remove one from the Google Home app.
- [Sign in again](troubleshooting.md#sign-in-again){#sign-in-again} if Home Assistant reports that authentication expired.
- [Remove the integration](configuration.md#remove-the-integration){#remove-the-integration}, and what to do about its master token.

## Try a fix before it's released

A fix merged into `master` reaches the Home Assistant Marketplace with the next release. To try it sooner, install `master` in place of your current version. Only `master` is supported, not other branches or pull requests.

While you run `master`, **Settings** > **Devices & services** > **Google Home** still shows the version number of the latest release, so if you report a problem, say that you run `master`.

=== "Marketplace"

    These steps work only if you installed the integration from the Marketplace, or with HACS before Home Assistant moved it to the Marketplace. Otherwise, use the **Manual** steps.

    1. Find the entity ID of the Google Home update entity: in [**Settings** > **Devices & services** > **Entities**](https://my.home-assistant.io/redirect/entities/), search for `update.google_home`. It's usually `update.google_home` or `update.google_home_update`.
    2. Open [**Settings** > **Tools** > **Actions**](https://my.home-assistant.io/redirect/tools_perform_action/?service=update.install) and switch to **YAML mode**.
    3. Enter this action, with your entity ID in place of `update.google_home`:

        ```yaml
        action: update.install
        target:
          entity_id: update.google_home
        data:
          version: master
        ```

    4. Select **Perform action**, then restart Home Assistant.

    This installs `master` as it is at that moment. To get newer commits, run the action again.

    !!! warning "An update replaces `master`"

        While you run `master`, Home Assistant may offer the latest release as an update, in **Settings** or on the integration's Marketplace page. Installing it replaces `master` with that release, so a fix that isn't released yet is gone. Install it only when you want to go back, then restart Home Assistant. While you test, you can open the update in **Settings** and select **Skip**: this hides only that release, and Home Assistant offers the next one as usual.

    To go back when **Settings** offers no update, or the update can't be installed, [open Google Home in the Marketplace](https://my.home-assistant.io/redirect/marketplace_repository/?owner=leikoilja&repository=ha-google-home&category=integration) and select **⋮** > **Install another version**. Under **Version**, choose the release marked **Latest**, then select **Update**. Restart Home Assistant afterwards.

=== "Manual"

    Follow the **Manual** steps under [Install the integration](#install-the-integration), but download [`master` as a ZIP](https://github.com/leikoilja/ha-google-home/archive/refs/heads/master.zip) instead of the release, and delete the old `google_home` folder first. To get newer commits, repeat them. To go back, repeat them with the latest release.

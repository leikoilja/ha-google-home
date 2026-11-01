# Configuration and management

After you [set up the integration](installation.md), you can change how often it checks your devices, add and remove devices, reach devices on another network, and remove the integration. If Home Assistant asks you to sign in again, see [Sign in again](troubleshooting.md#sign-in-again).

## Change the update interval

The integration checks your devices for changes every 15 seconds by default.

To change the interval, go to **Settings** > **Devices & services** > **Google Home** and select **Configure**. Shorter intervals update alarms and timers sooner but send more requests to your devices.

If a speaker or display with alarms and timers often shows `false` in the `available` attribute of its [device sensor](entities.md#device-sensor) while it's on, or its entities become unavailable for a moment while it restarts, increase the interval, for example to 180 seconds, the default before version 1.16.

**Configure** shows the interval in use. If you saved these options in version 1.15 or older, for example to add known hosts, it's the interval you saved, which was 180 seconds unless you changed it. To use the new default, enter 15 and select **Submit**.

To update immediately, use the [Refresh devices](actions.md#refresh-devices) action.

## Add a device

When you add a speaker or display in the Google Home app, the integration adds it without a reload:

- If Home Assistant receives the device's mDNS announcements, for example because it's on the same network, the device appears about a minute after it joins your network, if Google lists it by then. If another Cast device that the integration didn't know, such as a TV, appeared shortly before, it can take up to 5 minutes.
- Otherwise, or if Google doesn't list the device yet by then, it appears within about 20 minutes, when the integration next asks Google for your devices.

To add the device straight away, reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. The integration then asks Google for your devices. The device appears only once Google lists it, and some of its entities only once Home Assistant can reach it; see [Entities](entities.md).

If the integration finds your devices only through [known hosts](#add-devices-on-another-network), add the new device's IP address there instead. Saving it reloads the integration, which then reaches the device at that address.

To add back a speaker or display that you removed from the Google Home app:

1. Wait until the integration has removed the old device from Home Assistant, usually 20 to 40 minutes after you removed it from the app, or delete it yourself; see [Remove a device](#remove-a-device). If the old device is still there when the new one appears, the new device's entities get IDs such as `sensor.kitchen_alarms_2` instead of `sensor.kitchen_alarms`.
2. [Factory reset the device](https://support.google.com/googlenest/answer/7073477). Restarting it isn't enough.
3. Set it up again in the Google Home app. Give it the same name to keep its entity IDs.

Google gives the device a new ID, so the integration adds it as a new device, as described at the start of this section.

If you deleted a device in Home Assistant yourself and it doesn't come back when the Google Home app lists it again, reload the integration.

## Add devices on another network

The integration finds your devices on your network with multicast DNS (mDNS). mDNS usually doesn't reach other networks, such as a separate VLAN for smart home devices, or a Home Assistant container that doesn't use `host` network mode. Those devices then have only a [device sensor](entities.md#device-sensor), a [reboot button](entities.md#reboot-button) and an [update sensor](entities.md#update-sensor), and all three are unavailable.

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

After that, the integration asks your known hosts only when it asks Google for your devices, and only for devices that still have no address. For example, a device that was offline when the integration loaded is looked up at your known hosts at the first update 20 minutes after the integration last asked Google. With a network interface on the devices' network or an mDNS reflector, the integration gets a device's address as soon as the device announces itself, as on the same network.

Give these devices fixed IP addresses in your router, so the addresses don't change. For a speaker pair, add the addresses of both speakers. Only the speaker that leads the pair reports it, so the integration uses that one and ignores the other.

## Remove a device

When you remove a device from the Google Home app, or Google drops it from your home after a factory reset, the integration removes it from Home Assistant, with its entities, once Google's device list has lacked it twice in a row. The integration asks Google for your devices every 20 minutes, so this usually takes 20 to 40 minutes. It doesn't remove a device while Google still has it in your home, even if the integration can't use the device.

As soon as Google's device list first lacks the device, its entities are unavailable. Removing a device from the Google Home app doesn't reset it: it stays on your network, and the integration keeps updating it until it next asks Google for your devices. After a factory reset, a device forgets your Wi-Fi network and usually stops answering, so its entities can become unavailable sooner, once it hasn't answered 5 updates in a row, before the integration has noticed.

When the integration can't get your device list from Google, for example while Google can't be reached, that attempt doesn't count. Reloading the integration or restarting Home Assistant starts the count again, and a device that Google dropped while Home Assistant was off is usually removed about 20 minutes after the integration loads.

To remove a device sooner, delete it yourself. First reload the integration so that it notices straight away: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. Then open the device's page in Home Assistant, open the **⋮** menu and select **Delete**.

Home Assistant offers **Delete** for every device of the integration, but you can't delete one that Google still lists in your home, even if it shows as unavailable: it would come back the next time the integration loads. Until the integration has noticed that Google no longer lists a device, you can't delete that one either. Home Assistant then shows "Failed to remove device entry, rejected by integration".

If Google briefly leaves a working device out of your home in two lists in a row, the integration removes it and adds it back the next time Google lists it. Home Assistant then restores the settings you changed, such as the device's area and name and its entities' names, IDs and disabled state, as long as no other entity has taken those entity IDs meanwhile.

To use a device again that you removed from the Google Home app, factory reset it first; see [Add a device](#add-a-device).

## Remove the integration

1. Go to **Settings** > **Devices & services** > **Google Home**, open the **⋮** menu and select **Delete**. Home Assistant deletes the master token it stored.
2. If you installed with HACS, open HACS, select **Google Home**, open the **⋮** menu and select **Remove**. If you installed manually, delete the `custom_components/google_home` folder.
3. Restart Home Assistant.

To use another Google account, delete the integration as in step 1 and add it again.

Deleting the integration doesn't stop the master token from working, and the integration can't revoke it. If the token might have been copied, for example from a Home Assistant backup:

- If you created a separate Google account for the integration, delete that account.
- Otherwise, [change the Google account's password](https://support.google.com/accounts/answer/41078). Google then signs you out on most devices and apps, but it lists exceptions, so this isn't guaranteed to stop the master token.

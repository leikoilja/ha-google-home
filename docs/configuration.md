# Configuration and management

After you [set up the integration](installation.md), you can change how often it checks your devices, add and remove devices, reach devices on another network, choose the homes whose devices it adds, and remove the integration. If Home Assistant asks you to sign in again, see [Sign in again](troubleshooting.md#sign-in-again).

## Change the update interval

The integration checks your devices for changes every 15 seconds by default.

To change the interval, go to **Settings** > **Devices & services** > **Google Home** and select **Configure**. Shorter intervals update alarms and timers sooner but send more requests to your devices.

If a speaker or display with alarms and timers often shows `false` in the `available` attribute of its [device sensor](entities.md#device-sensor) while it's on, or its entities become unavailable for a moment while it restarts, increase the interval, for example to 180 seconds, the default before version 1.16.

**Configure** shows the interval in use. If you saved these options in version 1.15 or older, for example to add known hosts, it's the interval you saved, which was 180 seconds unless you changed it. To use the new default, enter 15 and select **Submit**.

To update immediately, use the [Refresh devices](actions.md#refresh-devices) action.

## Add a device

When you add a speaker or display in the Google Home app, the integration adds it without a reload, unless it's in a home that you [deselected](#choose-homes):

- If Home Assistant receives the device's mDNS announcements, for example because it's on the same network, the device appears about a minute after it joins your network, if Google lists it by then. If another Cast device that the integration didn't know, such as a TV, appeared shortly before, it can take up to 5 minutes.
- Otherwise, or if Google doesn't list the device yet by then, it appears within about 20 minutes, when the integration next asks Google for your devices.

To add the device straight away, reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. The integration then asks Google for your devices. The device appears only once Google lists it, and some of its entities only once Home Assistant can reach it; see [Entities](entities.md).

If the integration finds your devices only through [known hosts](#add-devices-on-another-network), add the new device's IP address there instead. Saving it reloads the integration, which then reaches the device at that address.

To add back a speaker or display that you removed from the Google Home app, or to replace one with another device:

1. If you're replacing a device, remove the old one from the Google Home app, even if it no longer works. Until you do, the integration keeps it and you can't delete it.
2. If the old device is still in Home Assistant, delete it. First reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. Then open the old device's page, open the **⋮** menu and select **Delete**. You can also wait until the integration removes it, usually 20 to 40 minutes after you removed it from the app; see [Remove a device](#remove-a-device). If the old device is still there when the new one appears, the new device's entities get IDs such as `sensor.kitchen_alarms_2` instead of `sensor.kitchen_alarms`, and keep them after the old device is removed.
3. If you're adding back the same device, [factory reset it](https://support.google.com/googlenest/answer/7073477). Restarting it isn't enough.
4. Set up the device in the Google Home app. To get entity IDs like the old device's, give it the same name.

Google gives the device a new ID, so the integration adds it as a new device with new entities, as described at the start of this section. Home Assistant doesn't carry over the old device's settings, such as its area, its name in Home Assistant and the entity IDs you changed.

Home Assistant builds the new entity IDs from the device's name in the Google Home app, as for any new device. With the same name, they're usually the old device's original entity IDs, such as `sensor.kitchen_alarms`. In the languages where Home Assistant builds entity IDs from translated names, though, the new entities get translated IDs, such as `sensor.kitchen_wecker` in German, even if the old ones are in English. See [Entity names in other languages](entities.md#entity-names-in-other-languages).

If an automation, script or manually configured dashboard card uses an old entity ID that the new device doesn't have, update it. You can also give the new entity the old ID once the old device is gone: on the device page, select the entity, then the settings (gear) icon, change **Entity ID** and select **Update**.

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

## Choose homes

If your Google account is a member of several homes, you can choose the homes whose speakers and displays the integration adds. It adds every home's devices unless you deselect some. Google still sends the integration the devices of every home. The integration doesn't add the devices of homes you deselect, even if it finds them on your network or at a known host, and doesn't check them for alarms and timers.

When you add the integration, it asks which homes to add if your account has more than one. If Google doesn't give the integration your homes at that point, it adds every home's devices, and you can choose later.

You can change the homes later under **Homes** in the integration's options. **Homes** appears when your account has more than one home, or when the only home left is one that you deselected, so that you can select it again. The integration needs to have got your homes from Google since it last loaded: if **Homes** is missing although your account has several homes, reload the integration first.

Homes are listed by the names they have in the Google Home app. If two of your homes have the same name, rename one of them in the app first, so that you can tell them apart. The `home` attribute of each device's [device sensor](entities.md#device-sensor) shows the name of its home, so automations and templates can tell which home a device is in. The attribute is hidden while the sensor is unavailable, for example for a device in a home at another address that Home Assistant can't find on its network.

To change the homes:

1. Go to **Settings** > **Devices & services** > **Google Home** and select **Configure**.
2. Under **Homes**, select the homes whose devices to add.
3. Select **Submit**. If you changed the homes, the integration reloads.

When you deselect a home, the integration removes its devices from Home Assistant, with their entities, as it reloads. Automations, scripts and dashboards that use them stop working. If Google doesn't give the integration your device list as it reloads, the devices stay, unavailable, until the integration next gets the list.

When you select a home again, its devices come back with the names, areas and other settings you gave them. A device that was factory reset and set up again meanwhile has a new ID from Google, so it's added as a new device, without them. As with a [removed device](#remove-a-device), an entity gets its old ID back only if no other entity has taken that ID meanwhile.

Homes that your account joins later are added. A new home appears under **Homes** once the integration next gets your device list from Google, usually within about 20 minutes. To see it sooner, reload the integration: **Settings** > **Devices & services** > **Google Home** > **⋮** > **Reload**. If the options were already open, close them and select **Configure** again. To leave the new home out, deselect it.

## Remove a device

When you remove a device from the Google Home app, or Google drops it from your home after a factory reset, the integration removes it from Home Assistant, with its entities, once Google's device list has lacked it twice in a row. The integration asks Google for your devices every 20 minutes, so this usually takes 20 to 40 minutes. It doesn't remove a device while Google still has it in one of your homes, even if the integration can't use the device, unless you [deselect that home](#choose-homes).

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

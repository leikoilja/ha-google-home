[![GitHub Release][releases-shield]][releases]
[![Home Assistant quality scale: Platinum][quality-scale-shield]][quality-scale]
[![Marketplace][marketplace-shield]][marketplace]
[![Installs][installs-shield]][installs]

<p align="center">
  <a href="https://github.com/leikoilja/ha-google-home">
    <img src="https://brands.home-assistant.io/google_home/icon.png" alt="Logo" height="200">
  </a>
</p>

<h3 align="center">Home Assistant Google Home community integration</h3>

<p align="center">
  Alarms, timers and more from your Google Home and Nest speakers and displays.
</p>

## About

This integration brings your Google Home and Nest speakers and displays into Home Assistant. You can:

- See and delete [alarms](https://ha-google-home.pages.dev/entities/#alarms-sensor) and [timers](https://ha-google-home.pages.dev/entities/#timers-sensor).
- Turn [Do Not Disturb](https://ha-google-home.pages.dev/entities/#do-not-disturb-switch) on or off and change the [alarm volume](https://ha-google-home.pages.dev/entities/#alarm-volume).
- [Reboot](https://ha-google-home.pages.dev/entities/#reboot-button) a device.
- See each device's [firmware version](https://ha-google-home.pages.dev/entities/#firmware-version) and whether it says [a firmware update is waiting](https://ha-google-home.pages.dev/entities/#update-sensor).
- See each device's [Wi-Fi network and signal strength](https://ha-google-home.pages.dev/entities/#wi-fi-sensors).
- Tell whether your phone or another Bluetooth device is home, with [Bluetooth tracking](https://ha-google-home.pages.dev/bluetooth/).

Use the alarms and timers in automations, for example to:

- Turn on the bedroom lights 10 minutes before the next alarm.
- Open the bedroom blinds when the alarm goes off.
- Send a notification to your phone when the kitchen timer finishes.

[Automation examples](https://ha-google-home.pages.dev/automations/) has the YAML for each one.

It can't create, change or snooze alarms and timers, or turn alarms on or off; set them by voice or on a display's screen. It doesn't add the other devices in your Google Home app, such as lights or thermostats; see [Other Google Home devices](https://ha-google-home.pages.dev/other-integrations/#other-google-home-devices). It doesn't play media, change the media volume, speak messages or send Google Assistant commands either; see [Other integrations for the same devices](https://ha-google-home.pages.dev/other-integrations/#other-integrations-for-the-same-devices) for what does.

<a name="hacs-installation"></a>

## Installation

You need a Google account that is a member of your home in the Google Home app. Home Assistant finds your speakers and displays on its local network; devices on another network need extra setup.

Install the integration from the Marketplace, which replaced HACS in Home Assistant 2026.11: [open Google Home in the Marketplace][marketplace], or go to **Settings** > **Marketplace**, search for **Google Home** and open it. Then follow **[Getting Started](https://ha-google-home.pages.dev/installation/)** to add it and sign in. It also lists all the requirements and covers manual installation.

## Documentation

The **[documentation site](https://ha-google-home.pages.dev/)** has these pages:

- [Getting Started](https://ha-google-home.pages.dev/installation/): prerequisites, installation, sign-in and a first check with a timer
- [Configuration and management](https://ha-google-home.pages.dev/configuration/): update interval, polling, adding and removing devices, devices on another network, homes and removing the integration
- [Automation examples](https://ha-google-home.pages.dev/automations/): lights before an alarm, blinds when it goes off and timer notifications
- [Entities](https://ha-google-home.pages.dev/entities/): alarms, timers, Do Not Disturb, alarm volume, reboot, firmware updates, firmware version and Wi-Fi
- [Bluetooth tracking](https://ha-google-home.pages.dev/bluetooth/): whether your phone and other Bluetooth devices are home, using your speakers
- [Actions](https://ha-google-home.pages.dev/actions/): delete alarms and timers, reboot and refresh devices
- [Other integrations](https://ha-google-home.pages.dev/other-integrations/): media, media volume, spoken messages, Assistant commands and other Google Home devices
- [Troubleshooting](https://ha-google-home.pages.dev/troubleshooting/): setup errors, missing devices, unavailable entities, diagnostics and debug logs
- [Community](https://ha-google-home.pages.dev/community/): dashboard cards and Node-RED flows
- [Contributing](https://ha-google-home.pages.dev/contributing/): questions, bug reports, translations and development

## Contribution

Ask questions, report bugs or suggest features in [issues](https://github.com/leikoilja/ha-google-home/issues/new/choose). To translate the integration or change its code, see [Contributing](https://ha-google-home.pages.dev/contributing/).

## Credits

- The integration started from a [community discussion][community-discussion] about reading Google Home alarms and timers in Home Assistant.
- This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.
- Code template was mainly taken from [@Ludeeus](https://github.com/ludeeus)'s [integration_blueprint][integration_blueprint] template.
- Under the hood the integration uses [glocaltokens](https://github.com/leikoilja/glocaltokens) python package.

[community-discussion]: https://community.home-assistant.io/t/solution-to-track-your-google-home-alarms-and-timers-and-trigger-different-home-assistant-events/61534/74
[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[marketplace-shield]: https://img.shields.io/badge/Marketplace-Install-7C4DFF.svg?style=for-the-badge&logo=data:image/svg%2Bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiwxOEg2VjE0SDEyTTIxLDE0VjEyTDIwLDdINEwzLDEyVjE0SDRWMjBIMTRWMTRIMThWMjBIMjBWMTRNMjAsNEg0VjZIMjBWNFoiLz48L3N2Zz4=
[marketplace]: https://my.home-assistant.io/redirect/marketplace_repository/?owner=leikoilja&repository=ha-google-home&category=integration
[quality-scale-shield]: https://img.shields.io/badge/quality%20scale-%F0%9F%8F%86%20platinum-e5e4e2.svg?style=for-the-badge
[quality-scale]: https://ha-google-home.pages.dev/#quality-scale
[releases-shield]: https://img.shields.io/github/release/leikoilja/ha-google-home.svg?style=for-the-badge
[releases]: https://github.com/leikoilja/ha-google-home/releases
[installs-shield]: https://img.shields.io/badge/dynamic/json?style=for-the-badge&color=blue&logo=home-assistant&label=installs&cacheSeconds=3600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.google_home.total
[installs]: https://www.home-assistant.io/integrations/analytics/

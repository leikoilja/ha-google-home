[![GitHub Workflow Status][workflow-shield]][workflow]
[![GitHub Release][releases-shield]][releases]
[![hacs][hacsbadge]][hacs]
[![GitHub Activity][commits-shield]][commits]
[![Installs][installs-shield]][installs]

<p align="center">
  <a href="https://github.com/leikoilja/ha-google-home">
    <img src="https://brands.home-assistant.io/google_home/icon.png" alt="Logo" height="200">
  </a>
</p>

<h3 align="center">Home Assistant Google Home community integration</h3>

<p align="center">
  This custom integration aims to provide plug-and-play Google Home
  experience for Home Assistant enthusiasts.
</p>

## Documentation

Read the full documentation at **[ha-google-home.pages.dev](https://ha-google-home.pages.dev/)**:

- [Getting Started](https://ha-google-home.pages.dev/installation/): prerequisites, master token, installation and setup
- [Entities](https://ha-google-home.pages.dev/entities/): alarms, timers, Do Not Disturb and alarm volume
- [Actions](https://ha-google-home.pages.dev/actions/): delete alarms and timers, reboot and refresh devices
- [Troubleshooting](https://ha-google-home.pages.dev/troubleshooting/)
- [Community](https://ha-google-home.pages.dev/community/): dashboard cards and Node-RED flows

## About

This integration brings your Google Home and Nest speakers and displays into Home Assistant. You can see and delete their alarms and timers, turn Do Not Disturb on or off, change the alarm volume and reboot them. It started from a [community discussion][community-discussion] about reading Google Home alarms and timers in Home Assistant.

## HACS Installation

You can find it in the default HACS repo. Just search `Google Home`.

For manual installation and setup, see [Getting Started](https://ha-google-home.pages.dev/installation/).

## Contribution

If you encounter issues or have any suggestions consider opening issues and contributing through PR.
If you are ready to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md).

## Credits

- This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.
- Code template was mainly taken from [@Ludeeus](https://github.com/ludeeus)'s [integration_blueprint][integration_blueprint] template.
- Under the hood the integration uses [glocaltokens](https://github.com/leikoilja/glocaltokens) python package.

[commits-shield]: https://img.shields.io/github/commit-activity/y/leikoilja/ha-google-home.svg?style=for-the-badge
[commits]: https://github.com/leikoilja/ha-google-home/commits/master
[community-discussion]: https://community.home-assistant.io/t/solution-to-track-your-google-home-alarms-and-timers-and-trigger-different-home-assistant-events/61534/74
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge
[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[releases-shield]: https://img.shields.io/github/release/leikoilja/ha-google-home.svg?style=for-the-badge
[releases]: https://github.com/leikoilja/ha-google-home/releases
[workflow-shield]: https://img.shields.io/github/actions/workflow/status/leikoilja/ha-google-home/linting.yaml?branch=master&style=for-the-badge
[workflow]: https://github.com/leikoilja/ha-google-home/actions
[installs-shield]: https://img.shields.io/badge/dynamic/json?style=for-the-badge&color=blue&label=installs&cacheSeconds=3600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.google_home.total
[installs]: https://analytics.home-assistant.io/custom_integrations.json

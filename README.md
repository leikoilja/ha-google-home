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
  Alarms, timers and more from your Google Home and Nest speakers and displays.
</p>

## Documentation

Read the full documentation at **[ha-google-home.pages.dev](https://ha-google-home.pages.dev/)**:

- [Getting Started](https://ha-google-home.pages.dev/installation/): prerequisites, installation and sign-in
- [Entities](https://ha-google-home.pages.dev/entities/): alarms, timers, Do Not Disturb, alarm volume and reboot
- [Actions](https://ha-google-home.pages.dev/actions/): delete alarms and timers, reboot and refresh devices
- [Troubleshooting](https://ha-google-home.pages.dev/troubleshooting/)
- [Community](https://ha-google-home.pages.dev/community/): dashboard cards and Node-RED flows
- [Contributing](https://ha-google-home.pages.dev/contributing/): questions, bug reports, translations and development

## About

This integration brings your Google Home and Nest speakers and displays into Home Assistant. You can see and delete their alarms and timers, turn Do Not Disturb on or off, change the alarm volume and reboot them. It doesn't add the other devices in your Google Home app, such as lights or thermostats; see [Other Google Home devices](https://ha-google-home.pages.dev/#other-google-home-devices). It started from a [community discussion][community-discussion] about reading Google Home alarms and timers in Home Assistant.

## HACS Installation

You can find it in the default HACS repo. Just search `Google Home`.

For manual installation and setup, see [Getting Started](https://ha-google-home.pages.dev/installation/).

## Contribution

Ask questions in [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions), and report bugs or suggest features in [issues](https://github.com/leikoilja/ha-google-home/issues/new/choose). To translate the integration or change its code, see [Contributing](https://ha-google-home.pages.dev/contributing/).

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

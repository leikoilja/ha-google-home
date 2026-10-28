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

## About

This integration brings your Google Home and Nest speakers and displays into Home Assistant. You can see and delete their alarms and timers, turn Do Not Disturb on or off, change the alarm volume and reboot them.

Use the alarms and timers in automations, for example to:

- Turn on the bedroom lights 10 minutes before the next alarm.
- Open the bedroom blinds when the alarm goes off.
- Send a notification to your phone when the kitchen timer finishes.

[Automation examples](https://ha-google-home.pages.dev/automations/) has the YAML for each one.

It can't create, change or snooze alarms and timers, or turn alarms on or off; set them by voice or on a display's screen. It doesn't add the other devices in your Google Home app, such as lights or thermostats; see [Other Google Home devices](https://ha-google-home.pages.dev/other-integrations/#other-google-home-devices). It doesn't play media, change the media volume, speak messages or send Google Assistant commands either; see [Other integrations for the same devices](https://ha-google-home.pages.dev/other-integrations/#other-integrations-for-the-same-devices) for what does.

<a name="hacs-installation"></a>

## Get started

You need a Google account that is a member of your home in the Google Home app. Home Assistant finds your speakers and displays on its local network; devices on another network need extra setup.

Install the integration from HACS: search for **Google Home**. Then follow **[Getting Started](https://ha-google-home.pages.dev/installation/)** to add it and sign in. It also lists all the requirements and covers manual installation.

## Documentation

Read the full documentation at **[ha-google-home.pages.dev](https://ha-google-home.pages.dev/)**:

- [Getting Started](https://ha-google-home.pages.dev/installation/): prerequisites, installation and sign-in
- [Automation examples](https://ha-google-home.pages.dev/automations/): lights before an alarm, blinds when it goes off and timer notifications
- [Entities](https://ha-google-home.pages.dev/entities/): alarms, timers, Do Not Disturb, alarm volume and reboot
- [Actions](https://ha-google-home.pages.dev/actions/): delete alarms and timers, reboot and refresh devices
- [Other integrations](https://ha-google-home.pages.dev/other-integrations/): media, media volume, spoken messages, Assistant commands and other Google Home devices
- [Troubleshooting](https://ha-google-home.pages.dev/troubleshooting/)
- [Community](https://ha-google-home.pages.dev/community/): dashboard cards and Node-RED flows
- [Contributing](https://ha-google-home.pages.dev/contributing/): questions, bug reports, translations and development

## Contribution

Ask questions in [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions), and report bugs or suggest features in [issues](https://github.com/leikoilja/ha-google-home/issues/new/choose). To translate the integration or change its code, see [Contributing](https://ha-google-home.pages.dev/contributing/).

## Credits

- The integration started from a [community discussion][community-discussion] about reading Google Home alarms and timers in Home Assistant.
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

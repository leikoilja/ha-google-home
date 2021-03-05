[![GitHub Workflow Status][workflow-shield]][workflow]
[![Contributors][contributors-shield]][contributors]
[![hacs][hacsbadge]][hacs]
[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]

<br />
<p>
  <p align="center">
    <a href="https://github.com/leikoilja/ha-google-home">
      <img src="https://brands.home-assistant.io/ha-google-home/icon.png" alt="Logo" height="200">
    </a>
  </p>

  <h3 align="center">Home Assistant Google Home community integration</h3>

  <p align="center">
    This custom integration aims to provide plug-and-play Google Home
    experience for Home Assistant enthusiasts.
  </p>

**[!] Beta version alert.**
Please note this integration is in the early stage of it's development.
See <a href="#contribution">Contribution</a> section for more information.

</p>

<!-- TABLE OF CONTENTS -->
<details open="open">
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about">About The Project</a>
    </li>
    <li>
      <a href="#features">Features</a>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#hacs-installation">HACS Installation</a></li>
        <li>
	  <a href="#manual-installation">Manual Installation</a>
	  <ul>
            <li><a href="#git-clone-method">Git clone method</a></li>
            <li><a href="#copy-method">Copy method</a></li>
	  </ul>
	</li>
        <li><a href="#integration-setup">Integration Setup</a></li>
        <li><a href="#running-in-home-assistant-docker-container">
	  Running in Home Assistant Docker container
	</a></li>
      </ul>
    </li>
    <li><a href="#contribution">Contribution</a></li>
    <li><a href="#credits">Credits</a></li>
  </ol>
</details>

## About

This is a custom component that is emerging from the
[community discussion][community-discussion] of a need to be able to retrieve
local google assistant device (like Google Home/Nest etc) authentication
tokens and use those tokens making API calls to Google Home devices.

## Features

This component will set up the following platforms:

| Platform | Sample sensor               | Description                                               |
| -------- | --------------------------- | --------------------------------------------------------- |
| `sensor` | `sensor.living_room_timers` | Sensor with timers from the device                        |
| `sensor` | `sensor.living_room_alarms` | Sensor with alarms from the device                        |
| `sensor` | `sensor.living_room_token`  | Sensor with the local authentication token for the device |

### Timers
You can have multiple timers on your Google Home device. The Home Assistant
timers sensor will represent all of them in the state attributes as a list "timers".
Each of timers has the following keys:

| Key | Value type               | Description                                               |
| -------- | --------------------------- | --------------------------------------------------------- |
| `id` | Google Home corresponding ID | Used to delete/modify timer                        |
| `fire_time` | Seconds | Raw value coming from Google Home device until the timer goes off  |
| `local_time` | Time  | Time when the timer goes off, in respect to the Home Assistant's timezone |
| `local_time_iso` | Time in ISO 8601 standard  | Useful for automations|
| `duration` | Seconds  | Timer duration in seconds|


### Alarms
You can have multiple alarms on your Google Home device. The Home Assistant
alarms sensor will represent all of them in the state attributes as a list
"alarms".
Each of alarms has the following keys:

| Key | Value type               | Description                                               |
| -------- | --------------------------- | --------------------------------------------------------- |
| `id` | Google Home corresponding ID | Used to delete/modify alarm                        |
| `fire_time` | Seconds | Raw value coming from Google Home device until the alarm goes off  |
| `local_time` | Time  | Time when the alarm goes off, in respect to the Home Assistant's timezone |
| `local_time_iso` | Time in ISO 8601 standard  | Useful for automations|
| `recurrence` | List of integers  | Days of the week when the alarm will go off.  Please note, respecting Google set standard, the week starts from Sunday, therefore is denoted by 0. Correspondingly, Monday is 1, Saturday is 6 and so on |

## Getting Started

### Prerequisites

Use Home Assistant build 2021.3 or above.

### HACS Installation

_Since the integration is under active development, it is not yet added to HACS default repository, only manual installation is availabe for early testers_

To install the integration follow [HACS description](https://hacs.xyz/docs/faq/custom_repositories) to add custom repository.
Provide `https://github.com/leikoilja/ha-google-home` as repository URL and select "Integration" category.
We recommend you select the latest stable release.

### Manual Installation

1. Open the directory with your Home Assistant configuration (where you find `configuration.yaml`,
   usually `~/.homeassistant/`).
2. If you do not have a `custom_components` directory there, you need to create it.

#### Git clone method

This is a preferred method of manual installation, because it allows you to keep the `git` functionality,
allowing you to manually install updates just by running `git pull origin master` from the created directory.

Now you can clone the repository somewhere else and symlink it to Home Assistant like so:

1. Clone the repo.

```shell
git clone https://github.com/leikoilja/ha-google-home.git
```

2. Create the symlink to `ha-google-home` in the configuration directory.
   If you have non standard directory for configuration, use it instead.

```shell
ln -s ha-google-home/custom_components/ha-google-home ~/.homeassistant/custom_components/ha-google-home
```

#### Copy method

1. Download [ZIP](https://github.com/leikoilja/ha-google-home/archive/master.zip) with the code.
2. Unpack it.
3. Copy the `custom_components/ha-google-home/` from the unpacked archive to `custom_components`
   in your Home Assistant configuration directory.

### Integration Setup

1. Restart Home Assistant after installation.
2. In the Home Assistant UI go to "Configuration" -> "Integrations" click "+" and search for "Google Home".

### Running in Home Assistant Docker container

Make sure that you have your Home Assistant Container network set to 'host', as perscribed in the official docker installation for Home Assistant.

## Contribution

This integration is still in the early stage of it's development. Please use it
at your own risk. If you encounter issues or have any suggestions consider
opening issues and contributing through PR. If you are ready to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

## Credits

This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.

Code template was mainly taken from [@Ludeeus](https://github.com/ludeeus)'s [integration_blueprint][integration_blueprint] template.

Under the hood the integration uses [glocaltokens](https://github.com/leikoilja/glocaltokens) python package.

---

[buymecoffee]: https://www.buymeacoffee.com/leikoilja
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/leikoilja/ha-google-home.svg?style=for-the-badge
[commits]: https://github.com/leikoilja/ha-google-home/commits/master
[community-discussion]: https://community.home-assistant.io/t/solution-to-track-your-google-home-alarms-and-timers-and-trigger-different-home-assistant-events/61534/74
[contributors-shield]: https://img.shields.io/github/contributors/leikoilja/ha-google-home?style=for-the-badge
[contributors]: https://github.com/leikoilja/ha-google-home/graphs/contributors
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[license-shield]: https://img.shields.io/github/license/leikoilja/ha-google-home.svg?style=for-the-badge
[license]: https://github.com/leikoilja/ha-google-home/blob/master/LICENSE
[releases-shield]: https://img.shields.io/github/release/leikoilja/ha-google-home.svg?style=for-the-badge
[releases]: https://github.com/leikoilja/ha-google-home/releases
[workflow-shield]: https://img.shields.io/github/workflow/status/leikoilja/ha-google-home/Running%20tests?style=for-the-badge
[workflow]: https://github.com/leikoilja/ha-google-home/actions

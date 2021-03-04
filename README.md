[![GitHub Workflow Status][workflow-shield]][workflow]
[![Contributors][contributors-shield]][contributors]
[![hacs][hacsbadge]][hacs]
[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]

<br />
<p>
  <!-- TODO: Add a logo -->
  <!-- <a href="https://github.com/leikoilja/ha-google-home"> -->
  <!--   <img src="images/logo.png" alt="Logo" height="200"> -->
  <!-- </a> -->

  <h3 align="center">Home Assistant Google Home community integration</h3>

  <p align="center">
    This custom integration aims to provide plug-and-play Google Home
    experience for Home Assistant enthusiasts.
  </p>
  <br />

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
        <li><a href="#hacs-installation">HACS</a></li>
        <li><a href="#manual-installation">Manual installation</a></li>
      </ul>
    </li>
    <li><a href="#configuration">Configuration</a></li>
    <li><a href="#contribution">Contribution</a></li>
    <li><a href="#credits">Credits</a></li>
  </ol>
</details>

## About

This is a custom component that is emerging from the
[community discussion][community-discussion] of a need to be able to retrieve
local google assistant device (like Google Home/Nest etc) authentication
tokens to be able to use those tokens making API calls to retrieve
Google Home device information.

## Features

This component will set up the following platforms:

| Platform | Description                                               |
| -------- | --------------------------------------------------------- |
| `sensor` | Sensor with timers from the device                        |
| `sensor` | Sensor with alarms from the device                        |
| `sensor` | Sensor with the local authentication token for the device |

## Getting Started

### Prerequisites

Use Homeassistant build 2021.3 or above.

### HACS installation

**[!!] Since this is WIP, HACS installation is unavailable yet, only manual installation for early testers**

### Manual Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called
   `ha-google-home`.
4. Download _all_ the files from the `custom_components/ha-google-home/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Homeassistant.
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Google-Home".

#### Running HA in Docker

Make sure that you have your Homeassistant Container network set to 'host', as perscribed in the official docker installation for homeassistant.

## Configuration

Configration is done through the UI.

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
[exampleimg1]: misc/images/example1.png
[exampleimg2]: misc/images/example2.png
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[license-shield]: https://img.shields.io/github/license/leikoilja/ha-google-home.svg?style=for-the-badge
[license]: https://github.com/leikoilja/ha-google-home/blob/master/LICENSE
[releases-shield]: https://img.shields.io/github/release/leikoilja/ha-google-home.svg?style=for-the-badge
[releases]: https://github.com/leikoilja/ha-google-home/releases
[workflow-shield]: https://img.shields.io/github/workflow/status/leikoilja/ha-google-home/Running%20tests?style=for-the-badge
[workflow]: https://github.com/leikoilja/ha-google-home/actions

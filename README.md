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

**[!!] Since this is WIP, HACS installation is unavailable yet, only manual installation for early testers**

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
        <!-- <li><a href="#hacs">HACS</a></li> -->
        <li><a href="#manual">Manual installation</a></li>
      </ul>
    </li>
    <li><a href="#configuration">Configuration</a></li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#google-home-alarm">Google Home alarm</a></li>
        <li><a href="#google-home-timer">Google Home timer</a></li>
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
tokens to be able to use those tokens making API calls to retrieve
Google Home device information.

## Features

This component will set up the following platforms:

| Platform | Description                                                 |
| -------- | ----------------------------------------------------------- |
| `sensor` | Sensor with periodically fetched local authentication token |

Integration page example with multiple created entities:
![example1][exampleimg1]

Sensor state example with authentication token:

![example2][exampleimg2]

## Getting Started

### Prerequisites

Depending on what operating system you are running your HomeAssistant instance
on, you might need to install additional system-wide packages/compilers in order to
be able to build wheels for `glocaltokens` python package, that is used by this
integration.

Please SSH to your system and run:

- On Raspberry Pi (which most likely runs on Alpine Linux)

`apk add gcc g++ linux-headers`

- On Ubuntu

`sudo apt install build-essential`

<!-- ### HACS -->
<!--  -->
<!-- The easiest way to add this to your Homeassistant installation is using [HACS](https://hacs.xyz/). -->
<!--  -->
<!-- In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "HA-Google-Home". -->
<!--  -->
<!-- It's recommended to restart Homeassistant directly after the installation without any change to the Configuration. -->
<!-- Homeassistant will install the dependencies during the next reboot. -->

### Manual Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called
   `ha-google-home`.
4. Download _all_ the files from the `custom_components/ha-google-home/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Homeassistant.
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "HA-Google-Home". (Please note, it might take up to 30 minutes to install on Raspberry Pi, because of underlying dependency installations)

## Configuration

When adding integration using HA Installation UI type in your google username
(Note: only the handle, without '@gmail.com') and google password. You can use
your master google account's password, but it is highly recommended to generate
app password and use it. It's safer/easier to generate an app password and use it instead of the actual password. It still has the same access as the regular password, but still better than using the real password while scripting. (https://myaccount.google.com/apppasswords).

## Usage

This custom component DOES NOT (yet) implement any [Google Home Local API](https://rithvikvibhu.github.io/GHLocalApi) directly. It simply obtains tokens for you to be able to use [Google Home Local API](https://rithvikvibhu.github.io/GHLocalApi). Basically giving you the keys to the playground to do what you wish with the api.

### Example usage

Now that you have local authentication token for your google home devices you
can use them making simple [REST API](https://www.home-assistant.io/integrations/rest/) calls like the following few examples:

**Important**
Please note that in the `resource` key `https` and port `:8443` are mandatory!

#### Google Home alarm

```yaml
sensor:
  - platform: rest
    resource: https://<IP-ADDRESS-OF-YOUR-GOOGLE-HOME>:8443/setup/assistant/alarms
    method: GET
    name: Google Nest alarm
    headers:
      cast-local-authorization-token: "{{ sensor.glocaltoken_kitchen.state }}"
      content-type: "application/json"
    value_template: "{{ value_json['alarm'] }}"
    verify_ssl: false
```

Sensor state example:

```yaml
"entity_id": "sensor.google_nest_alarm"
"state": "[{'date_pattern': {'day': 20, 'month': 1, 'year': 2021}, 'fire_time': 1611126007000.0, 'id': 'alarm/606fa170-0000-27c9-9f87-089e0823c38c', 'status': 1, 'time_pattern': {'hour': 8, 'minute': 0, 'second': 7}}]"
```

#### Google Home timer

```yaml
sensor:
  - platform: rest
    resource: https://<IP-ADDRESS-OF-YOUR-GOOGLE-HOME>:8443/setup/assistant/alarms
    method: GET
    name: Google Nest timer
    headers:
      cast-local-authorization-token: "{{ sensor.glocaltoken_kitchen.state }}"
      content-type: "application/json"
    value_template: "{{ value_json['timer'] }}"
    verify_ssl: false
```

Sensor state example:

```yaml
"entity_id": "sensor.google_nest_timer"
"state": "[{'fire_time': 1611126011000.0, 'id': 'timer/617764ce-0000-2170-8ab3-2405887a817c', 'original_duration': 69062000.0, 'status': 1}]"
```

If you have any good examples, please open a PR to this README to share them with others

## Contribution

This integration is still in the early stage of it's development. Please use it
at your own risk. If you encounter issues or have any suggestions consider
opening issues and contributing through PR. If you are ready to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

## Credits

This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.

Code template was mainly taken from [@Ludeeus](https://github.com/ludeeus)'s [integration_blueprint][integration_blueprint] template.

Under the hood the integration uses [glocaltokens](https://github.com/leikoilja/glocaltokens) python package.

---

[community-discussion]: https://community.home-assistant.io/t/solution-to-track-your-google-home-alarms-and-timers-and-trigger-different-home-assistant-events/61534/74
[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[buymecoffee]: https://www.buymeacoffee.com/leikoilja
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/leikoilja/ha-google-home.svg?style=for-the-badge
[commits]: https://github.com/leikoilja/ha-google-home/commits/master
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[exampleimg1]: misc/images/example1.png
[exampleimg2]: misc/images/example2.png
[license]: https://github.com/leikoilja/ha-google-home/blob/master/LICENSE
[license-shield]: https://img.shields.io/github/license/leikoilja/ha-google-home.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/leikoilja/ha-google-home.svg?style=for-the-badge
[releases]: https://github.com/leikoilja/ha-google-home/releases

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Community Forum][forum-shield]][forum]

# Home assistant google local authentication token fetching (Glocaltoken)

**[!] Beta version alert.**
Please note this integration is in the early stage of it's development. See
[Contribution](#Contribution) section for more information.

**[!!] Since this is WIP, HACS installation is unavailable yet, only manual installation for early testers**

## About

Custom component that is emerging from the [community discussion](https://community.home-assistant.io/t/solution-to-track-your-google-home-alarms-and-timers-and-trigger-different-home-assistant-events/61534/74) of a need to be able to retrieve local google assistant device (like Google Home/Nest etc) authentication tokens to be able to use those tokens making API calls to retrieve Google Assistant device information.
This custom component is fetching local google assistant authentication tokens
every 30 minutes and saves them in Homeassistant instance as sensors.

**This component will set up the following platforms:**

| Platform | Description                                                 |
| -------- | ----------------------------------------------------------- |
| `sensor` | Sensor with periodically fetched local authentication token |

Integration page example with multiple created entities:
![example1][exampleimg1]

Sensor state example with authentication token:

![example2][exampleimg2]

## Installation

<!-- ### HACS -->
<!--  -->
<!-- The easiest way to add this to your Homeassistant installation is using [HACS](https://hacs.xyz/). -->
<!--  -->
<!-- In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Google local authentication token fetching (Glocaltokens)". -->
<!--  -->
<!-- It's recommended to restart Homeassistant directly after the installation without any change to the Configuration. -->
<!-- Homeassistant will install the dependencies during the next reboot. -->

### Manual

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called
   `glocaltokens`.
4. Download _all_ the files from the `custom_components/glocaltokens/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Homeassistant.
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Google local authentication token fetching (Glocaltokens)".

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

[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[buymecoffee]: https://www.buymeacoffee.com/leikoilja
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/leikoilja/ha-glocaltokens.svg?style=for-the-badge
[commits]: https://github.com/leikoilja/ha-glocaltokens/commits/main
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[exampleimg1]: example1.png
[exampleimg2]: example2.png
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license]: https://github.com/leikoilja/ha-glocaltokens/blob/main/LICENSE
[license-shield]: https://img.shields.io/github/license/leikoilja/ha-glocaltokens.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40leikoilja-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/leikoilja/ha-glocaltokens.svg?style=for-the-badge
[releases]: https://github.com/leikoilja/ha-glocaltokens/releases
[user_profile]: https://github.com/leikoilja

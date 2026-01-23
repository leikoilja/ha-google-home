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

<details open="open">
  <summary>Table of Contents</summary>

1. [About The Project](#about)
2. [Sensors](#sensors)
3. [Switches](#switches)
4. [Numbers](#numbers)
5. [Services](#services)
6. [Getting Started](#getting-started)
   - [Prerequisites](#prerequisites)
   - [HACS Installation](#hacs-installation)
   - [Manual Installation](#manual-installation)
   - [Integration Setup](#integration-setup)
   - [Running in Home Assistant Docker container](#running-in-home-assistant-docker-container)
   - [Installing ARM Docker Container Dependencies (Workaround)](#arm-docker-container-dependencies-workaround)
7. [Lovelace Cards](#lovelace-cards)
8. [Node-RED Flows](#node-red-flows)
9. [Troubleshooting](#troubleshooting)
10. [Contribution](#contribution)
11. [Localization](#localization)
12. [Credits](#credits)

</details>

## About

This is a custom component that is emerging from the
[community discussion][community-discussion] of a need to be able to retrieve
local Google Assistant device (like Google Home/Nest etc) authentication
tokens and use those tokens making API calls to Google Home devices.

## IMPORTANT

With version 1.6 we have changed the update interval from 10 seconds to 180 seconds.
This is due to [#202](https://github.com/leikoilja/ha-google-home/issues/202). Some people are
experiencing devices timing out when trying to fetch data from them.

You can manually change the update interval by pressing the `configure` button on the integration
page. Default is 180 seconds. Change this at your own risk! If your devices are timing out,
please increase this until it is stable again.

## Sensors

This component will set up the following sensors:

| Platform | Sample sensor               | Description                                                                |
| -------- | --------------------------- | -------------------------------------------------------------------------- |
| `sensor` | `sensor.living_room_alarms` | Sensor with a list of alarms from the device                               |
| `sensor` | `sensor.living_room_timers` | Sensor with a list of timers from the device                               |
| `sensor` | `sensor.living_room_device` | Sensor with the IP address for the device, as well as some info attributes |

### Alarms

You can have multiple alarms on your Google Home device. Home Assistant
alarms sensor will represent all of them in the state attributes as a list
`alarms`.
Each of the alarms has the following keys:

| Key              | Value type                   | Description                                                                                                                                                                                             |
| ---------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `alarm_id`       | Google Home corresponding ID | Used to identify the alarm                                                                                                                                                                              |
| `fire_time`      | Seconds                      | Raw value coming from Google Home device until the alarm goes off                                                                                                                                       |
| `local_time`     | Time                         | Time when the alarm goes off, in respect to the Home Assistant's timezone                                                                                                                               |
| `local_time_iso` | Time in ISO 8601 standard    | Useful for automations                                                                                                                                                                                  |
| `status`         | Status (string)              | The current status of the alarm, either `none`, `set`, `ringing`, `snoozed` or `inactive`                                                                                                               |
| `label`          | Name                         | Name of the alarm, this can be set when making the alarm                                                                                                                                                |
| `recurrence`     | List of integers             | Days of the week when the alarm will go off. Please note, respecting Google set standard, the week starts from Sunday, therefore is denoted by 0. Correspondingly, Monday is 1, Saturday is 6 and so on |

The state value shows the next alarm as a time string (i.e.: `2021-03-07T15:26:17+01:00`) if there is at least one alarm set, otherwise it is set to `unavailable`.
This matches state format of [standard next alarm sensor](https://companion.home-assistant.io/docs/core/sensors/#next-alarm-sensor) provided by `mobile_app`.

This sensor is formatted to be compatible with the mobile app sensor, e.g. `sensor.phone_next_alarm`.

### Timers

You can have multiple timers on your Google Home device. Home Assistant
timers sensor will represent all of them in the state attributes as a list `timers`.
Each of the timers has the following keys:

| Key              | Value type                   | Description                                                                  |
| ---------------- | ---------------------------- | ---------------------------------------------------------------------------- |
| `timer_id`       | Google Home corresponding ID | Used to identify the timer                                                   |
| `fire_time`      | Seconds                      | Raw value coming from Google Home device until the timer goes off            |
| `local_time`     | Time                         | Time when the timer goes off, in respect to the Home Assistant's timezone    |
| `local_time_iso` | Time in ISO 8601 standard    | Useful for automations                                                       |
| `duration`       | Seconds                      | Timer duration in seconds                                                    |
| `status`         | Status (string)              | The current status of the timer, either `none`, `set`, `ringing` or `paused` |
| `label`          | Name                         | Name of the timer, this can be set when making the timer                     |

The state value shows the next timer as a timestring (i.e.: `2021-03-07T15:26:17+01:00`) if there is at least one timer set, otherwise it is set to `unavailable`.

### Alarm/Timer status

Both alarms and timers have a property called status. The status of the next alarm/timer (which is used as sensor state value) is also available through sensor state attributes `next_alarm_status` and `next_timer_status` respectively.

| Status     | Meaning                                                            |
| ---------- | ------------------------------------------------------------------ |
| `none`     | Alarm or timer does not exist                                      |
| `set`      | Alarm or timer has been set                                        |
| `ringing`  | Alarm or timer is ringing right now                                |
| `snoozed`  | Alarm was ringing and has been snoozed (only available for alarms) |
| `inactive` | Alarm is inactive (only available for alarms)                      |
| `missed`   | Alarm was missed (only available for alarms)                       |

Note that timers lack the additional `snoozed` state due to a limitation of the API. If you actually snooze a timer it will just reset itself to the state `set` again.

## Switches

This component will set up the following switches:

| Platform | Sample switch                       | Description                                        |
| -------- | ----------------------------------- | -------------------------------------------------- |
| `switch` | `switch.living_room_do_not_disturb` | Toggle Do Not Disturb mode on a Google Home device |

## Numbers

This component will set up the following numbers:

| Platform | Sample number                     | Description                                      |
| -------- | --------------------------------- | ------------------------------------------------ |
| `number` | `number.living_room_alarm_volume` | Control the alarm volume on a Google Home device |

## Services

It is possible to delete an alarm or a timer with the `google_home.delete_alarm` or `google_home.delete_timer` services.
You can check it out in [Home Assistant Developer Services Tool](https://my.home-assistant.io/redirect/developer_services/).

See below for the more detailed information.

### Delete alarm

#### Example

```yaml
service: google_home.delete_alarm
data:
  entity_id: sensor.kitchen_alarms
  timer_id: alarm/47dc1fa0-5ec0-2cc7-9ead-a94b85e22769
  skip_refresh: true
```

#### Key Descriptions

| Key            | Example                                      | Description                                     |
| -------------- | -------------------------------------------- | ----------------------------------------------- |
| `entity_id`    | `sensor.kitchen_alarms`                      | Entity name of a Google Home alarms sensor.     |
| `alarm_id`     | `alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51` | ID of an alarm. See alarms description above.   |
| `skip_refresh` | `true`                                       | Boolean to skip refreshing Google Home devices. |

### Delete timer

#### Example

```yaml
service: google_home.delete_timer
data:
  entity_id: sensor.kitchen_timers
  timer_id: timer/47dc1fa0-5ec0-2cc7-9ead-a94b85e22769
  skip_refresh: true
```

#### Key Descriptions

| Key            | Example                                      | Description                                     |
| -------------- | -------------------------------------------- | ----------------------------------------------- |
| `entity_id`    | `sensor.kitchen_timers`                      | Entity name of a Google Home timers sensor.     |
| `timer_id`     | `timer/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51` | ID of a timer. See timers description above.    |
| `skip_refresh` | `true`                                       | Boolean to skip refreshing Google Home devices. |

### Reboot device

Note: Not all devices this integration supports can be rebooted, even if you get the message "Successfully asked xxxxx to reboot."

#### Example

```yaml
service: google_home.reboot_device
data:
  entity_id: sensor.kitchen_device
```

#### Key Descriptions

| Key         | Example                 | Description                                 |
| ----------- | ----------------------- | ------------------------------------------- |
| `entity_id` | `sensor.kitchen_device` | Entity name of a Google Home device sensor. |

### Refresh devices

Note: Resets the timer for automatic polling to refresh devices.

#### Example

```yaml
service: google_home.refresh_devices
```

## Getting Started

### Prerequisites

Use Home Assistant v2026.1.0 or above.

### Google Account security

This integration uses your google account username and app password.
See [2 Factor Authentication](#2-factor-authentication--app-passwords) section for tips
how to setup app password. If you have created a passkey for your Google Account you must obtain the master token for your account as described in the [corresponding section](#master-token).

However, we strongly recommend protection your main
google account by not exposing it to the Home Assistant for automation purposes.
We encourage you to create a separate Google account and add it to your Google Home.
Your second account would not have access to anything other than Google Home, so even if it
gets compromised, it's not as severe as losing your main google account.
See more discussion [here](https://github.com/leikoilja/ha-google-home/issues/124#issuecomment-921773489)

### Master token

Due to authentication issues with google credentials alone it may be required to get the master token separately and provide it during the setup process. This can be done using [this script](https://gist.github.com/rithvikvibhu/952f83ea656c6782fbd0f1645059055d) or [glocaltokens](https://github.com/leikoilja/glocaltokens#quickstart) package.

Since there are several issues getting the token reliable on different environments, you can use a community created [docker image](https://hub.docker.com/r/breph/ha-google-home_get-token) which was created solely for helping to get a master token reliably. If you choose to use this docker container, run the following command:

```
$ docker run --rm -it breph/ha-google-home_get-token
```

You fill find more detailed instructions on how to run the docker container [here](https://github.com/leikoilja/ha-google-home/issues/890#issuecomment-2515002294).

### HACS Installation

You can find it in the default HACS repo. Just search `Google Home`.

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

2. Create the symlink to `google_home` in the configuration directory.
   If you have non standard directory for configuration, use it instead.

```shell
ln -s ha-google-home/custom_components/google_home ~/.homeassistant/custom_components/google_home
```

#### Copy method

1. Download [ZIP](https://github.com/leikoilja/ha-google-home/archive/master.zip) with the code.
2. Unpack it.
3. Copy the `custom_components/google_home/` from the unpacked archive to `custom_components`
   in your Home Assistant configuration directory.

### Integration Setup

- Browse to your Home Assistant instance.
- In the sidebar click on [Configuration](https://my.home-assistant.io/redirect/config).
- From the configuration menu select: [Integrations](https://my.home-assistant.io/redirect/integrations).
- In the bottom right, click on the [Add Integration](https://my.home-assistant.io/redirect/config_flow_start?domain=ha-google-home) button.
- From the list, search and select “Google Home”.
- Follow the instruction on screen to complete the set up.
- After completing, the Google Home integration will be immediately available for use.

### Running in Home Assistant Docker container

Make sure that you have your Home Assistant Container network set to `host`, as perscribed in the official docker installation for Home Assistant.

### ARM Docker Container Dependencies Workaround

If you are installing this integration on an ARM based device (Like Raspberry Pi, Synology, etc.), you may need to do the following if you get this error:

```
ERROR: Cannot install glocaltokens==0.3.1
```

Please run the following command in the Home Assistant container to add the missing dependencies for `glocaltokens`:

```
apk add gcc g++
```

then you can install `glocaltokens` manually like this:

```
pip3 install glocaltokens
```

Unfortunately, this will need to be done each time the image is updated. Alternatively you can add the command to the container startup:

```
command: /bin/bash -c "apk add gcc g++; pip3 install --upgrade pip; pip3 install glocaltokens; /init"
```

## Lovelace Cards

**Open a PR to add your card here!**

- [Google Home timers card](https://github.com/DurgNomis-drol/google_home_timers_card) by [@DurgNomis-drol](https://github.com/DurgNomis-drol)

## Node-RED Flows

**Open a PR to add your flow here!**

- [Alarms & timers as actionable notifications](https://dev.to/mattieha/get-google-home-alarms-timers-as-notifications-i0m) by [@mattieha](https://github.com/mattieha)
- [Broadcast ringing alarms & timers to other devices](https://dev.to/mattieha/broadcast-google-home-alarms-timers-3c13) by [@mattieha](https://github.com/mattieha)

## Troubleshooting

### Collecting useful log data

Here are the steps to generate useful log data:

1. Temporary log level change.
   1. Visit [Home Assistant Developer Services Tool](https://my.home-assistant.io/redirect/developer_services/).
   2. Choose `Logger: Set level` from the **Service** menu. (the [Logger service](https://www.home-assistant.io/integrations/logger/) needs to be enabled for this)
   3. Go to YAML mode and paste the following (starting on line 2):
      ```yaml
      data:
        custom_components.google_home: debug
        glocaltokens: debug
      ```
   4. Click **Call Service**.
2. Read the log information.
   1. Visit [Home Assistant Logs](https://my.home-assistant.io/redirect/logs/).
   2. Click **Load Full Home Assistant Log**.
   3. Look for all `google_home` and `glocaltokens` entries.
3. Requesting help with the log information.
   1. Copy the log entries.
   2. Paste them into a discussion forum or bug report. Make sure to use quotation block.

### "Username/Password is incorrect"

If you get this error:

1. First verify you are using the correct Username and Password combination for that Google account.
2. Have you enabled 2 Factor Authentication on that Google account? _If so read the [2 Factor Authentication](#2-factor-authentication--app-passwords) section to continue._
3. We have seen some other custom components break the dependencies causing `google_home` to fail authentication process. For more information please see [this issue](https://github.com/leikoilja/ha-google-home/issues/95).
4. After ruling out #1, #2 and #3 collect relevant logs and open a new issue.

### 2 Factor Authentication / App Passwords

The error "The setting you are looking for is not available for your account" will occur if you do not have 2 Factor Authentication (2FA) enabled on your Google account.

Here are the steps to resolve this issue:

1. Open [Google Account settings](https://myaccount.google.com/).
2. On the top right corner click the profile photo and select the account which you would like to use.
3. Go to [Security](https://myaccount.google.com/security) page and make sure you have **2-Step Verification** turned on in **Signing in to Google** section.
4. Then visit [App passwords](https://myaccount.google.com/apppasswords).
   1. Click **Select app** and enter a descriptive name such as _Google Home Integration for Home Assistant_.
   2. Click the **Generate** button.
   3. Copy the password and return to the Google Home Configuration screen.
5. Return to [Integrations](https://my.home-assistant.io/redirect/integrations/).
   1. Click **Configure** on the Google Home integration.
   2. Enter your Google account username.
   3. Paste the password into the **Google account app password** field.
   4. Click **Submit**.

### Devices found, but not initialized

If the debug logs list your devices, but then show `Successfully initialized 0 Google Home devices` make sure you are logged into the correct Google account.
The account you are using with the integration must have access to your Home.
If unsure, please check what account you are using in the _Google Home_ app and if your devices are listed there.

### Devices found and initialized, but no alarms/timers sensor (#231)

If you can see your devices, and they all seem correct, but the alarms/timers sensors do not appear, or appear empty try restarting the Google Home device, Home Assistant, and reinstalling the integration.

### Device offline or not compatible message (#402)

If you get the following error for **_all_** of your devices:

```
2021-11-28 16:13:20 DEBUG (MainThread) [custom_components.google_home] Failed to fetch timers/alarms information from device xxx. We could not determine its IP address, the device is either offline or is not compatible Google Home device. Will try again later.
```

It may be that your device and Home Assistant installation are not on the same network.

The integration works by connecting to the Google's servers to authenticate and get the authorisation keys for controlling these devices, but after that, all the requests are made locally, so it's required that the server and devices are on the same network. You can use a VPN or setup routing between each network to overcome this issue.

### "version GLIBC_2.34 not found"

Your system has old version of GLIBC and therefore not compatible with pre-compiled version of grpcio.
But you can build it from sources for your system. For that in HA virtualenv run (use the version of `grpcio` from [glocaltokens](https://github.com/leikoilja/glocaltokens/blob/master/pyproject.toml)):

```
pip install -U grpcio==1.46.1 --no-binary=grpcio --force-reinstall
```

## Contribution

If you encounter issues or have any suggestions consider opening issues and contributing through PR.
If you are ready to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md).

## Localization

Currently the integration supports the following languages:

- Catalan
- Danish
- Dutch
- English
- French
- German (Germany)
- Italian (Italy)
- Norwegian (bokmål and nynorsk)
- Polish
- Portuguese (Brazil)
- Portuguese (Portugal)
- Russian
- Slovak
- Spanish (Spain)
- Ukrainian

If you want to translate the project to your own language, follow the [Localization guide](LOCALIZATION.md).

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

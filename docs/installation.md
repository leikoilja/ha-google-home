# Getting Started

## Before you start

You need:

- Home Assistant 2026.10.0 or later.
- Google speakers or displays, such as a Nest Mini, Nest Audio or Nest Hub. The integration doesn't add the other devices in your Google Home app, such as lights or thermostats. See [Other Google Home devices](index.md#other-google-home-devices).
- A Google account that is a member of your home in the Google Home app. Open the Google Home app with that account and check that your devices are listed.
- Home Assistant on the same local network as your devices. If you run Home Assistant in Docker, set the container's network mode to `host`, as the [official installation guide](https://www.home-assistant.io/installation/linux) does. Otherwise the integration can't find your devices.

!!! tip "Use a separate Google account"

    The integration needs credentials that give full access to the Google account you sign in with. Instead of your main account, create a new Google account and [invite it to your home](https://support.google.com/googlenest/answer/9155535) in the Google Home app. If its credentials leak, only that account is exposed. See [issue #124](https://github.com/leikoilja/ha-google-home/issues/124#issuecomment-921773489) for the discussion.

## Install the integration

=== "HACS (recommended)"

    1. Open HACS in Home Assistant.
    2. Search for **Google Home** and open it.
    3. Select **Download**.
    4. Restart Home Assistant.

    HACS tells you when an update is available.

=== "Manual"

    1. Download the source code ZIP of the [latest release](https://github.com/leikoilja/ha-google-home/releases/latest) and unpack it.
    2. Find your Home Assistant configuration folder, the one that contains `configuration.yaml`. If it has no `custom_components` folder, create one.
    3. Copy the `custom_components/google_home` folder from the release into that `custom_components` folder.
    4. Restart Home Assistant.

    To update, repeat these steps with the new release. Delete the old `google_home` folder first.

## Choose how to sign in

The setup form accepts either your **Google account username** with an **app password**, or a **master token**.

- **App password:** try this first, because it is simpler. Google accepts it for some accounts and rejects it for others. App passwords aren't available if your 2-Step Verification uses only security keys or your account is enrolled in Advanced Protection. For a work or school account, they depend on your organization's [security settings](https://knowledge.workspace.google.com/admin/security/how-2-step-verification-works-with-legacy-apps). If you sign in to Google with a passkey, use a master token. When Google rejects one, setup shows "Username or password is incorrect" even though both are right.
- **Master token:** works when an app password doesn't. See [Get a master token](#get-a-master-token).

### Create an app password

1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/twosv) for the Google account. Google requires it for app passwords.
2. Open [App passwords](https://myaccount.google.com/apppasswords) and sign in.
3. Enter a name, such as _Home Assistant_, and select **Create**.
4. Copy the 16-character password. Google shows it only once.

If the App passwords page still says "The setting you are looking for is not available for your account" after you turned on 2-Step Verification, your account can't use app passwords. [Get a master token](#get-a-master-token) instead.

## Add the integration

1. [Add the Google Home integration](https://my.home-assistant.io/redirect/config_flow_start?domain=google_home), or go to **Settings** > **Devices & services** > **Add integration** and search for **Google Home**.
2. Fill in the form:
    - To use an app password, enter **Google account username** and **Google account app password**, and leave **Google account master token** empty.
    - To use a master token, paste it into **Google account master token**. You can leave the other two fields empty.
3. Select **Submit**.

Home Assistant then adds a device for each Google Cast device in your home, with the [entities](entities.md) for it. Devices that have no alarms or timers, such as an NVIDIA Shield, get only a device sensor.

To change the account or credentials later, delete the integration and add it again.

## Change the update interval

The integration checks your devices for changes every 180 seconds.

To change the interval, go to **Settings** > **Devices & services** > **Google Home** and select **Configure**. If your devices time out, increase the interval until they stay stable. Shorter intervals update alarms and timers sooner but send more requests to your devices.

To update immediately, use the [Refresh devices](actions.md#refresh-devices) action.

## Get a master token

!!! warning "Keep your master token secret"

    A master token works like your password: anyone who has it can access your Google account. Don't share it or post it in an issue.

### With the Docker image

If you have Docker on an x86-64 computer, the [community Docker image](https://hub.docker.com/r/breph/ha-google-home_get-token) asks for your email and app password and prints the token:

```shell
docker run --rm -it breph/ha-google-home_get-token
```

The image doesn't run on ARM computers such as a Raspberry Pi. It signs in the same way the integration does, so if setup said "Username or password is incorrect", the image fails too. It then prints `{'Error': 'BadAuthentication'}` and `Could not get master token`. In that case, use the next method.

### With a browser sign-in

This method doesn't use your password, so it works when Google rejects your app password. You need a computer with Python 3 and a desktop browser.

1. In a private browser window, open [accounts.google.com/EmbeddedSetup](https://accounts.google.com/EmbeddedSetup) and sign in with the account you want to use.
2. Accept the prompt. The page may then keep loading forever; that is expected.
3. Open your browser's developer tools and find the cookies for `accounts.google.com`. In Chrome, this is **Application** > **Cookies**; in Firefox, **Storage** > **Cookies**.
4. Copy the value of the `oauth_token` cookie. It starts with `oauth2_4/`.
5. Install the [`gpsoauth`](https://github.com/simon-weber/gpsoauth) library in a new virtual environment, so it doesn't touch your system's Python, and exchange the cookie for a master token. Replace the email address and cookie value with your own:

    === "macOS and Linux"

        ```shell
        python3 -m venv gpsoauth-env
        gpsoauth-env/bin/python -m pip install gpsoauth
        gpsoauth-env/bin/python -c "import gpsoauth; print(gpsoauth.exchange_token('you@gmail.com', 'oauth2_4/...', '0123456789abcdef'))"
        ```

        On Debian or Ubuntu, if the first command says `ensurepip is not available`, install the `python3-venv` package and run it again.

    === "Windows"

        ```powershell
        py -m venv gpsoauth-env
        .\gpsoauth-env\Scripts\python -m pip install gpsoauth
        .\gpsoauth-env\Scripts\python -c "import gpsoauth; print(gpsoauth.exchange_token('you@gmail.com', 'oauth2_4/...', '0123456789abcdef'))"
        ```

6. Find `Token` in the output. Its value starts with `aas_et/`. That is your master token. You can now delete the `gpsoauth-env` folder.

If the output contains `'Error': 'BadAuthentication'` instead, the cookie has expired, was already used, or was copied incompletely. The cookie expires quickly and works only once, so repeat from step 1 in a new private window and run the command straight away.

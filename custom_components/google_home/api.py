"""The requests to each device that use its token, and the polling built on them."""

from contextlib import suppress
from datetime import timedelta
from http import HTTPStatus
import json
import logging
from time import monotonic
from typing import Literal

from aiohttp import (
    ClientConnectionError,
    ClientError,
    ClientPayloadError,
    ClientResponse,
    ClientTimeout,
)
from aiohttp.client_exceptions import ClientConnectorError, ContentTypeError

from homeassistant.util import dt as dt_util

from .account import GoogleAccountClient, TokenWait, first_update_after
from .const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARM_VOLUME,
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_BUILD_INFO,
    API_ENDPOINT_DO_NOT_DISTURB,
    API_ENDPOINT_REBOOT,
    API_ENDPOINT_UPDATE_INFO,
    FIRMWARE_CHECK_INTERVAL,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    JSON_ALARM_VOLUME,
    JSON_NOTIFICATIONS_ENABLED,
    PORT,
    SUPPORT_CHECK_DELAY,
    TIMEOUT,
)
from .device_info import (
    async_get_device_info,
    async_get_info_status,
    create_url,
    lacks_assistant,
)
from .exceptions import (
    AlarmsAndTimersNotDeleted,
    AlarmsAndTimersNotFetched,
    DeviceRequestFailed,
    RequestFailure,
)
from .models import GoogleHomeDevice, is_number
from .observations import observe_poll
from .types import JsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)

# The fields of a device's build info that are kept: its versions and release channel
BUILD_INFO_FIELDS = (
    "cast_build_revision",
    "system_build_number",
    "release_track",
    "preview_channel_state",
)


def log_failure(
    device: GoogleHomeDevice,
    polling: bool,
    failure: str,
    message: str,
    *args: object,
    exc_info: bool = False,
) -> None:
    """Log a failed request to the device as an error, or for debugging if its updates already did.

    An update logs each type of failure once, until an update of the device works,
    and the others for debugging, and its failure marks the running update as
    failed. An action logs every failure.
    """
    if polling:
        device.update_failed = True
        if failure in device.logged_failures:
            _LOGGER.debug(message, *args, exc_info=exc_info)
            return
        device.logged_failures.add(failure)
    _LOGGER.error(message, *args, exc_info=exc_info)


def answer_failure(
    device: GoogleHomeDevice, response: ClientResponse, *, polling: bool
) -> RequestFailure:
    """Log an answer other than 200 from the device, and return why it failed."""
    if response.status == HTTPStatus.UNAUTHORIZED:
        _LOGGER.debug("%s rejected its token", device.name)
        return "token_rejected"
    device.available = False
    if response.status == HTTPStatus.NOT_FOUND:
        _LOGGER.debug(
            (
                "Failed to perform request to %s, API returned %d. "
                "The device(hardware='%s') may be starting, or may "
                "have no alarms/timers."
            ),
            device.name,
            response.status,
            device.hardware,
        )
        return "not_ready"
    log_failure(
        device,
        polling,
        f"HTTP {response.status}",
        "Failed to access %s, API returned %d: %s",
        device.name,
        response.status,
        response,
    )
    return "request_failed"


class GlocaltokensApiClient(GoogleAccountClient):
    """API client."""

    async def update_device(
        self, device: GoogleHomeDevice, *, found_at_known_host: bool = False
    ) -> bool:
        """Ask a device on Google's list for its alarms, timers and settings, if it can be.

        With found_at_known_host, the device was just found at a known host, which
        answered with its info. Return whether the device was asked, which sets
        whether it's reachable. An update of a device without an address can't ask
        it: it counts toward the updates without an address, not toward those the
        device didn't answer.
        """
        # Gives the user a warning if the device is offline
        if not device.ip_address:
            if device.available:
                device.available = False
                _LOGGER.debug(
                    (
                        "Failed to fetch timers/alarms information "
                        "from device %s. We could not determine its IP address, "
                        "the device is either offline or is not compatible "
                        "Google Home device. Will try again later."
                    ),
                    device.name,
                )
            device.addressless_updates += 1
            return False
        if not device.auth_token and not device.alarms_unsupported:
            return False
        device.update_failed = False
        await self.collect_data_from_endpoints(
            device, found_at_known_host=found_at_known_host
        )
        # It answered, and none of its requests failed: alarms and settings, or its
        # info if it has no alarms
        if device.logged_failures and device.reachable and not device.update_failed:
            _LOGGER.info("Updating %s works again", device.name)
            device.logged_failures.clear()
        return True

    async def collect_data_from_endpoints(
        self, device: GoogleHomeDevice, *, found_at_known_host: bool = False
    ) -> GoogleHomeDevice:
        """Collect data from different endpoints.

        A device that doesn't answer isn't asked the rest until the next update, so it
        costs two timeouts, for its alarms and its info, not four. A device without
        alarms is asked only for its info, which shows whether it answers. Actions
        don't come here, so they're always sent.

        The device is reachable if its alarms answer 200, or else its info does. When
        the check for alarms asks for its info, or the device was just found at a known
        host, that answer counts, so it isn't asked again.
        """
        if device.alarms_unsupported:
            status = (
                HTTPStatus.OK
                if found_at_known_host
                else await async_get_info_status(self._session, device)
            )
            device.reachable = status == HTTPStatus.OK
            device.count_answer(status)
            return device
        device = await self.update_alarms_and_timers(device)
        status = device.statuses.get((API_ENDPOINT_ALARMS, True))
        answered = device.count_answer(status)
        device.reachable = status == HTTPStatus.OK
        try:
            asked_info = await self._async_find_alarms_unsupported(device)
        except ClientError, TimeoutError:
            _LOGGER.debug(
                "%s didn't answer when asked for its info. Will check again in %d "
                "minutes.",
                device.name,
                SUPPORT_CHECK_DELAY // 60,
                exc_info=True,
            )
            return device
        if device.alarms_unsupported:
            return device
        if not device.reachable and not asked_info:
            device.reachable = found_at_known_host or (
                await async_get_info_status(self._session, device) == HTTPStatus.OK
            )
        if not answered:
            return device
        device = await self.update_alarm_volume(device)
        if (API_ENDPOINT_ALARM_VOLUME, True) not in device.statuses:
            return device
        return await self.update_do_not_disturb(device)

    async def _async_find_alarms_unsupported(self, device: GoogleHomeDevice) -> bool:
        """Find whether the device has turned out to have no alarms, timers and settings.

        Set alarms_unsupported if so. Return whether the device was asked for its
        info, which also sets whether it's reachable.

        Its alarms must answer "not found" at an update, and again at the first
        update at least SUPPORT_CHECK_DELAY later, as a device that is starting
        answers "not found" for a while. Then its info, in that same update, must
        list its features without Google Assistant. Only a 404 counts: a device
        that doesn't answer may be busy or offline.

        Raise TimeoutError or ClientError if the device doesn't answer when asked
        for its info.
        """
        now = monotonic()
        due = device.support_check_at is not None and now >= device.support_check_at
        status = device.statuses.get((API_ENDPOINT_ALARMS, True))
        if status != HTTPStatus.NOT_FOUND:
            if status == HTTPStatus.OK or due:
                device.support_check_at = None
            return False
        if device.support_check_at is None:
            device.support_check_at = now + SUPPORT_CHECK_DELAY
            return False
        if not due:
            return False
        # Unless its info shows that it lacks Google Assistant, check again later,
        # also when it doesn't answer
        device.support_check_at = now + SUPPORT_CHECK_DELAY
        assert device.ip_address is not None
        info = await async_get_device_info(self._session, device.ip_address, device)
        if not lacks_assistant(info):
            _LOGGER.debug(
                "%s still answers 404 for alarms, but its info doesn't show that it "
                "lacks Google Assistant. Will check again in %d minutes.",
                device.name,
                SUPPORT_CHECK_DELAY // 60,
            )
            return True
        _LOGGER.debug(
            (
                "%s (hardware='%s') still answers 404 for alarms after at least %d "
                "minutes, and its info lists its features without Google Assistant. "
                "It won't be asked for alarms, timers and settings until the "
                "integration is reloaded."
            ),
            device.name,
            device.hardware,
            SUPPORT_CHECK_DELAY // 60,
        )
        device.alarms_unsupported = True
        device.support_check_at = None
        self.unsupported_device_ids.add(device.device_id)
        return True

    async def update_firmware(self, device: GoogleHomeDevice) -> None:
        """Ask a device for its firmware when due, after update_device has asked it.

        Only a device that update_device found reachable, so one that didn't answer
        at this update gets no more requests. A check is due at most every
        FIRMWARE_CHECK_INTERVAL, counted from the start of the last one, so a device
        that fails isn't asked again until then. Its build info has its versions,
        and its info without params whether an update is waiting; neither needs a
        token. A device that doesn't answer the first isn't asked the second. Only
        the version and release channel fields, the flag, the Wi-Fi network and
        signal strength, and estimated boot time are kept. A field that its info
        leaves out is unknown; an answer other than its info keeps what it said before.
        """
        now = monotonic()
        if not device.reachable or (
            device.firmware_checked_at is not None
            and now < device.firmware_checked_at + FIRMWARE_CHECK_INTERVAL
        ):
            return
        device.firmware_checked_at = now
        assert device.ip_address is not None
        try:
            info = await async_get_device_info(
                self._session, device.ip_address, endpoint=API_ENDPOINT_BUILD_INFO
            )
            if info is not None:
                build_info = info.get("build_info")
                device.build_info = (
                    {
                        field: build_info[field]
                        for field in BUILD_INFO_FIELDS
                        if field in build_info
                    }
                    if isinstance(build_info, dict)
                    else None
                )
            info = await async_get_device_info(
                self._session, device.ip_address, endpoint=API_ENDPOINT_UPDATE_INFO
            )
        except ClientError, TimeoutError:
            _LOGGER.debug(
                "%s didn't answer when asked for its firmware. Will check again in %d "
                "minutes.",
                device.name,
                FIRMWARE_CHECK_INTERVAL // 60,
                exc_info=True,
            )
            return
        if info is not None:
            uptime = info.get("uptime")
            device.booted_at = None
            if isinstance(uptime, int | float) and is_number(uptime) and uptime >= 0:
                # Either the duration or the resulting date can be too large.
                with suppress(OverflowError):
                    device.booted_at = dt_util.utcnow() - timedelta(seconds=uptime)
            has_update = info.get("has_update")
            # Only the JSON true or false
            device.has_update = has_update if isinstance(has_update, bool) else None
            ssid = info.get("ssid")
            device.wifi_ssid = ssid if isinstance(ssid, str) and ssid else None
            signal = info.get("signal_level")
            # A JSON number, but not true or false, which Python counts as numbers
            device.wifi_signal = (
                signal
                if isinstance(signal, int | float) and not isinstance(signal, bool)
                else None
            )
        _LOGGER.debug(
            "%s has firmware %s, update waiting: %s",
            device.name,
            device.sw_version,
            device.has_update,
        )

    async def update_alarms_and_timers(
        self, device: GoogleHomeDevice, *, polling: bool = True
    ) -> GoogleHomeDevice:
        """Fetch timers and alarms from google device.

        Unless polling, raise if they can't be fetched, so an action doesn't
        work from the alarms and timers of the last update. A reply that can't be
        read replaces neither, and an update doesn't count it as having got them.
        """
        try:
            response = await self.request(
                method="GET",
                endpoint=API_ENDPOINT_ALARMS,
                device=device,
                polling=polling,
            )
        except DeviceRequestFailed as error:
            raise AlarmsAndTimersNotFetched(device.name, error) from error
        # Only an action's: an update's request logs it
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            _LOGGER.error(
                "%s sent a reply that isn't valid JSON: %s", device.name, error
            )
            raise AlarmsAndTimersNotFetched(device.name) from error

        # An update's request that failed: request() logged it and marked the update
        # as failed, which it wasn't before, as this is the update's first request.
        # Any other None is a reply of JSON null or an empty body.
        if response is None and polling and device.update_failed:
            return device
        device.alarms_reply = response
        if isinstance(response, dict) and device.set_alarms_and_timers(response):
            if polling:
                device.polled_snapshots += 1
                device.poll_observation = observe_poll(device)
            _LOGGER.debug(
                "Successfully retrieved alarms and timers from %s. Response: %s",
                device.name,
                response,
            )
            return device
        log_failure(
            device,
            polling,
            "unknown alarms reply",
            (
                "Failed to parse fetched alarms and timers for device %s - "
                "API returned unknown json structure. "
                "Received = %s"
            ),
            device.name,
            response,
        )
        if not polling:
            raise AlarmsAndTimersNotFetched(device.name)
        return device

    async def delete_alarm_or_timer(
        self, device: GoogleHomeDevice, items_to_delete: list[str]
    ) -> None:
        """Delete one or more timers or alarms in a single request.

        Once the device confirms, also remove them from the device's data. Raise
        if it doesn't, as it may still have them.
        """

        if not items_to_delete:
            return

        data = {"ids": items_to_delete}

        item_type = items_to_delete[0].split("/", maxsplit=1)[0]

        _LOGGER.debug(
            "Deleting %s from Google Home device %s - Raw data: %s",
            item_type,
            device.name,
            data,
        )

        try:
            response = await self.request(
                method="POST",
                endpoint=API_ENDPOINT_ALARM_DELETE,
                device=device,
                data=data,
            )
        # A reply that isn't valid JSON, although its content type says it is
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            _LOGGER.error(
                "%s sent a reply that isn't valid JSON: %s", device.name, error
            )
            raise AlarmsAndTimersNotDeleted(device.name) from error
        except DeviceRequestFailed as error:
            raise AlarmsAndTimersNotDeleted(device.name, error) from error

        # Only this reply is known to confirm a delete
        if isinstance(response, dict) and response.get("success") is True:
            _LOGGER.debug("Successfully deleted %s for %s", item_type, device.name)
            device.remove_alarms_and_timers(items_to_delete)
            return
        if response is not None:
            _LOGGER.error(
                "%s didn't confirm the %s delete. Received = %s",
                device.name,
                item_type,
                response,
            )
        raise AlarmsAndTimersNotDeleted(device.name)

    async def reboot_google_device(self, device: GoogleHomeDevice) -> None:
        """Reboot a Google Home device if it supports this.

        Raise DeviceRequestFailed if it doesn't answer 200. The rest of its answer
        isn't read, as it may go down while sending it.
        """

        # "now" means reboot and "fdr" means factory reset (Not implemented).
        data = {"params": "now"}

        _LOGGER.debug(
            "Trying to reboot Google Home device %s",
            device.name,
        )

        await self.request(
            method="POST",
            endpoint=API_ENDPOINT_REBOOT,
            device=device,
            data=data,
            read_reply=False,
        )
        # It answers so even if the device does not support rebooting.
        _LOGGER.info(
            "Successfully asked %s to reboot.",
            device.name,
        )

    async def update_do_not_disturb(self, device: GoogleHomeDevice) -> GoogleHomeDevice:
        """Get the Do Not Disturb setting from a Google Home device."""
        _LOGGER.debug(
            "Getting Do Not Disturb setting from Google Home device %s",
            device.name,
        )
        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_DO_NOT_DISTURB,
            device=device,
            polling=True,
        )
        self._store_do_not_disturb(device, response)
        return device

    async def set_do_not_disturb(self, device: GoogleHomeDevice, enable: bool) -> None:
        """Set the Do Not Disturb setting on a Google Home device.

        Raise DeviceRequestFailed if setting it fails.
        """
        _LOGGER.debug(
            "Setting Do Not Disturb setting to %s on Google Home device %s",
            enable,
            device.name,
        )
        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_DO_NOT_DISTURB,
            device=device,
            # Setting is inverted on device
            data={JSON_NOTIFICATIONS_ENABLED: not enable},
        )
        self._store_do_not_disturb(device, response)

    @staticmethod
    def _store_do_not_disturb(
        device: GoogleHomeDevice, response: JsonDict | None
    ) -> None:
        """Store the Do Not Disturb setting that the device answered with, if any."""
        if response is None:
            return
        if JSON_NOTIFICATIONS_ENABLED in response:
            enabled = not bool(response[JSON_NOTIFICATIONS_ENABLED])
            _LOGGER.debug(
                "Received Do Not Disturb setting from Google Home device %s"
                " - Enabled: %s",
                device.name,
                enabled,
            )
            device.do_not_disturb = enabled
        else:
            _LOGGER.debug(
                (
                    "Unexpected response from Google Home device '%s' "
                    "when fetching DND status - %s"
                ),
                device.name,
                response,
            )

    async def update_alarm_volume(self, device: GoogleHomeDevice) -> GoogleHomeDevice:
        """Get the alarm volume setting from a Google Home device."""
        _LOGGER.debug(
            "Getting alarm volume from Google Home device %s",
            device.name,
        )
        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_ALARM_VOLUME,
            device=device,
            polling=True,
        )
        if response and JSON_ALARM_VOLUME in response:
            volume_raw = str(response[JSON_ALARM_VOLUME])
            try:
                volume = round(float(volume_raw) * 100)
            # Not a number, such as "loud": keep the volume it had
            except ValueError, OverflowError:
                log_failure(
                    device,
                    True,
                    "invalid alarm volume",
                    "%s sent an alarm volume that isn't a number: %s",
                    device.name,
                    volume_raw,
                )
                return device
            device.alarm_volume = volume
            _LOGGER.debug(
                "Received alarm volume from Google Home device %s - Volume: %d(raw=%s)",
                device.name,
                device.alarm_volume,
                volume_raw,
            )
        elif response:
            self._log_unexpected_volume_answer(device, response)
        return device

    async def set_alarm_volume(self, device: GoogleHomeDevice, volume: int) -> None:
        """Set the alarm volume setting on a Google Home device.

        Raise DeviceRequestFailed if setting it fails.
        """
        volume_float = volume / 100
        _LOGGER.debug(
            "Setting alarm volume to %d(float=%f) on Google Home device %s",
            volume,
            volume_float,
            device.name,
        )
        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_ALARM_VOLUME,
            device=device,
            data={JSON_ALARM_VOLUME: volume_float},
        )
        if response and JSON_ALARM_VOLUME in response:
            _LOGGER.debug(
                "Successfully set alarm volume to %d on Google Home device %s",
                volume,
                device.name,
            )
            device.alarm_volume = volume
        elif response:
            self._log_unexpected_volume_answer(device, response)

    @staticmethod
    def _log_unexpected_volume_answer(
        device: GoogleHomeDevice, response: JsonDict
    ) -> None:
        """Log an answer about the alarm volume that doesn't have it."""
        _LOGGER.debug(
            (
                "Unexpected response from Google Home device '%s' "
                "when fetching alarm volume setting - %s"
            ),
            device.name,
            response,
        )

    async def request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        device: GoogleHomeDevice,
        data: JsonDict | None = None,
        polling: bool = False,
        *,
        read_reply: bool = True,
    ) -> JsonDict | None:
        """Shared request method.

        Unless polling, raise DeviceRequestFailed when the device doesn't answer
        200 or its answer can't be read, and JSONDecodeError or UnicodeDecodeError
        when it answers 200 with a reply that isn't valid JSON. An update only logs
        it, and gets None. Without read_reply, the 200 is the whole answer: the rest
        isn't read, and {} is returned.
        """
        try:
            return await self._send(
                method, endpoint, device, data, polling, read_reply=read_reply
            )
        except DeviceRequestFailed:
            if polling:
                device.update_failed = True
                return None
            raise
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            if not polling:
                raise
            log_failure(
                device,
                polling,
                "invalid JSON",
                "%s sent a reply to %s that isn't valid JSON: %s",
                device.name,
                endpoint,
                error,
            )
            return None

    async def _send(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        device: GoogleHomeDevice,
        data: JsonDict | None,
        polling: bool,
        *,
        read_reply: bool,
        retry: bool = True,
    ) -> JsonDict | None:
        """Send a request and return the answer, or raise DeviceRequestFailed.

        If the device rejects its token, get a new one and send the request once
        more. Only a rejection is retried: a request that timed out may have run.
        """

        # A request sent again with a new token replaces the status
        device.statuses.pop((endpoint, polling), None)

        if device.ip_address is None:
            _LOGGER.warning("Device %s doesn't have an IP address!", device.name)
            raise DeviceRequestFailed(device.name, "offline")

        if (token := device.auth_token) is None:
            _LOGGER.warning("Device %s doesn't have an auth token!", device.name)
            raise DeviceRequestFailed(device.name, "request_failed")

        url = create_url(device.ip_address, PORT, endpoint)

        headers: dict[str, str] = {
            HEADER_CAST_LOCAL_AUTH: token,
            HEADER_CONTENT_TYPE: "application/json",
        }

        _LOGGER.debug(
            "Requesting endpoint %s for Google Home device %s - %s",
            endpoint,
            device.name,
            url,
        )

        resp = None
        failure: RequestFailure | None = None

        try:
            timeout = ClientTimeout(total=TIMEOUT)
            async with self._session.request(
                method, url, json=data, headers=headers, timeout=timeout
            ) as response:
                status = response.status
                if response.status == HTTPStatus.OK:
                    resp = await self._read_answer(
                        response, device, endpoint, polling, read_reply=read_reply
                    )
                else:
                    failure = answer_failure(device, response, polling=polling)
            # Only once the answer has been read, if it's read: a 200 whose body
            # times out or is cut off isn't an answer
            device.statuses[endpoint, polling] = status
        except ClientConnectorError as error:
            logger_func = _LOGGER.debug if polling else _LOGGER.warning
            logger_func(
                "Failed to connect to %s device. The device is probably offline.",
                device.name,
            )
            device.available = False
            raise DeviceRequestFailed(device.name, "offline") from error
        except ClientError as error:
            # Make sure that we log the exception from the client if one occurred.
            log_failure(
                device,
                polling,
                type(error).__name__,
                "Request from %s device error",
                device.name,
                exc_info=True,
            )
            device.available = False
            # A connection that closed or an answer that was cut off: the device
            # may have done it
            if isinstance(error, ClientConnectionError | ClientPayloadError):
                raise DeviceRequestFailed(device.name, "no_reply") from error
            raise DeviceRequestFailed(device.name, "request_failed") from error
        except TimeoutError as error:
            _LOGGER.debug(
                "%s device timed out while performing a request to it - Raw data: %s",
                device.name,
                data,
            )
            device.available = False
            raise DeviceRequestFailed(device.name, "no_reply") from error

        if failure == "token_rejected":
            if retry and await self._async_get_new_token(device, token):
                _LOGGER.debug(
                    "Sending the request to %s again with its new token", device.name
                )
                return await self._send(
                    method,
                    endpoint,
                    device,
                    data,
                    polling,
                    read_reply=read_reply,
                    retry=False,
                )
            self._mark_token_rejected(device, polling=polling)
        if failure is not None:
            raise DeviceRequestFailed(
                device.name, failure, polling_off=self.polling_off
            )
        return resp

    async def _read_answer(
        self,
        response: ClientResponse,
        device: GoogleHomeDevice,
        endpoint: str,
        polling: bool,
        *,
        read_reply: bool,
    ) -> JsonDict | None:
        """Return the reply of the device's 200, and make the device available once it's read.

        Without read_reply, what comes after the status, or doesn't, can't undo it, and
        {} is returned, as for a reply that isn't JSON. Raise JSONDecodeError or
        UnicodeDecodeError for one that says it is but isn't valid, which still counts
        as an answer.
        """
        # It accepts its token, so its next rejection fetches straight away
        self._token_waits.pop(device.device_id, None)
        try:
            reply = await response.json() if read_reply else {}
        except ContentTypeError:
            reply = {}
        except json.JSONDecodeError, UnicodeDecodeError:
            device.available = True
            device.statuses[endpoint, polling] = response.status
            raise
        device.available = True
        return reply

    def _mark_token_rejected(self, device: GoogleHomeDevice, *, polling: bool) -> None:
        """Mark a device that rejected its token, with no new one to try.

        While polling is on, a device that rejects the token from a fetch that worked
        waits before its rejection fetches Google's list again: the next of
        FETCH_RETRY_DELAYS from the start of that fetch, longer for each later fetch
        that starts once the wait is over and whose token it rejects, until it accepts
        a token. Once it has rejected the tokens from two fetches in a row, the first
        update it fails logs an error, and the others log for debugging: right after a
        device restarts, Google may still give its old token for a short while.

        After a fetch that failed, or while polling is off, the list is fetched again
        at the next update or, after a failed fetch, at the first update once the
        backoff has passed. Keep the devices meanwhile, so the fetch keeps their data,
        and the others still update if Google can't be reached.
        """
        device.available = False
        wait: TokenWait | None = None
        if self.polling_off or self._fetch_backoff.failing:
            self.google_devices_fetched = False
        else:
            wait = self._token_waits.setdefault(device.device_id, TokenWait())
            if wait.counts(self._last_fetch_started):
                wait.fetch_started(self._last_fetch_started)
        if polling and wait is not None:
            message = (
                "%s rejected the token that Google gave it. Google is asked for a new "
                "one at %s"
            )
            when = first_update_after(wait.wait_left(monotonic()))
            if wait.repeated:
                log_failure(
                    device,
                    polling,
                    "token_rejected",
                    f"{message}; further rejections are logged at debug level until "
                    "it accepts one",
                    device.name,
                    when,
                )
            else:
                _LOGGER.debug(message, device.name, when)
        elif polling:
            _LOGGER.debug(
                (
                    "Failed to fetch data from %s due to invalid token. "
                    "Will refresh the token and try again."
                ),
                device.name,
            )
        elif self.polling_off:
            _LOGGER.warning(
                "Failed to send the request to %s due to invalid token. "
                "Polling is off: run Refresh devices, then try again.",
                device.name,
            )
        else:
            _LOGGER.warning(
                "Failed to send the request to %s due to invalid token. "
                "Token will be refreshed, please try again later.",
                device.name,
            )

    async def _async_get_new_token(
        self, device: GoogleHomeDevice, rejected_token: str
    ) -> bool:
        """Return whether a device that rejected its token has a new one now.

        If no fetch since the request was sent has brought one, fetch Google's list,
        unless the device waits after rejecting the token from a fetch that worked.
        Only one fetch runs from one update to the next, so once it has, the device
        waits for the next update. While the list is unknown, it also waits for the
        backoff after a failed fetch.
        """
        wait = self._token_waits.get(device.device_id)
        if device.auth_token == rejected_token and not (
            wait is not None and wait.waiting(monotonic())
        ):
            try:
                await self._async_fetch_devices(self._fetches_before_update)
            # Google can't be reached at setup
            except ClientError, TimeoutError:
                _LOGGER.debug("Failed to fetch Google's device list", exc_info=True)
        return device.auth_token != rejected_token

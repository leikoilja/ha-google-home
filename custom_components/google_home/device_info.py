"""Build a device's URLs, and ask it about itself, which needs no token."""

from collections.abc import Awaitable
import logging

from ghome_local_api import (
    BuildInfo,
    DeviceInfo,
    GoogleHomeLocalClient,
    RequestError,
    StatusError,
    UpdateInfo,
    device_url,
)

from .models import GoogleHomeDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


def create_url(ip_address: str, port: int, api_endpoint: str) -> str:
    """Create url to endpoint."""
    return device_url(ip_address, api_endpoint, port)


async def _async_info[T](
    host: str, request: Awaitable[T | None]
) -> tuple[bool, T | None]:
    """Return whether the device answered 200 with its whole body, and its info.

    The info is None if the device answers with something else, such as an error
    page. Raise RequestError if it doesn't answer.
    """
    try:
        info = await request
    # A device that is starting can answer 404, and an error page isn't its info
    except StatusError as error:
        _LOGGER.debug("%s answered %d when asked for its info", host, error.status)
        return False, None
    if info is None:
        _LOGGER.debug("%s answered, but not with its info", host)
    return True, info


async def async_get_device_info(
    client: GoogleHomeLocalClient, host: str, device: GoogleHomeDevice | None = None
) -> DeviceInfo | None:
    """Return what the device at this host reports about itself.

    Return None if it answers with something else, such as an error page.
    Raise RequestError if it doesn't answer. With a device, set whether it's
    reachable: whether a 200 came, with its whole body.
    """
    reachable = False
    try:
        reachable, info = await _async_info(host, client.get_device_info(host))
    finally:
        if device is not None:
            device.reachable = reachable
    return info


async def async_get_build_info(
    client: GoogleHomeLocalClient, host: str
) -> BuildInfo | None:
    """Return the device's firmware versions, or None if it answers otherwise.

    Raise RequestError if it doesn't answer.
    """
    return (await _async_info(host, client.get_build_info(host)))[1]


async def async_get_update_info(
    client: GoogleHomeLocalClient, host: str
) -> UpdateInfo | None:
    """Return whether the device has an update waiting, and its uptime and Wi-Fi.

    Return None if it answers otherwise. Raise RequestError if it doesn't answer.
    """
    return (await _async_info(host, client.get_update_info(host)))[1]


async def async_get_info_status(
    client: GoogleHomeLocalClient, device: GoogleHomeDevice
) -> int | None:
    """Return the status of the device's answer when asked for its info, without its token.

    A 200 counts once its body has come, another status as soon as it comes, and
    isn't undone if the answer then breaks off. Return None if no answer comes, for
    example when the session rejects a redirect. Redirects aren't followed. The
    session itself may try once more after a lost connection.
    """
    assert device.ip_address is not None
    try:
        return await client.get_info_status(device.ip_address)
    except RequestError as error:
        _LOGGER.debug(
            "%s didn't answer when asked for its info",
            device.name,
            exc_info=error.__cause__,
        )
        return None

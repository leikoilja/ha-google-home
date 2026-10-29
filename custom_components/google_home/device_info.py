"""Build a device's URLs, and ask it about itself, which needs no token."""

from http import HTTPStatus
import ipaddress
import logging

from aiohttp import ClientError, ClientSession, ClientTimeout
from aiohttp.client_exceptions import ContentTypeError

from .const import API_ENDPOINT_EUREKA_INFO, PORT, TIMEOUT
from .models import GoogleHomeDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


def create_url(ip_address: str, port: int, api_endpoint: str) -> str:
    """Create url to endpoint.

    Note: port argument is unused because all request must be done to 8443.
    """
    if isinstance(ipaddress.ip_address(ip_address), ipaddress.IPv6Address):
        ip_address = f"[{ip_address}]"
    return f"https://{ip_address}:{port}/{api_endpoint}"


async def async_get_device_info(
    session: ClientSession, host: str, device: GoogleHomeDevice | None = None
) -> dict[str, object] | None:
    """Return what the device at this host reports about itself.

    Return None if it answers with something else, such as an error page.
    Raise TimeoutError or ClientError if it doesn't answer. With a device, set
    whether it's reachable: whether a 200 came, with its whole body.
    """
    url = create_url(host, PORT, API_ENDPOINT_EUREKA_INFO)
    reachable = False
    try:
        async with session.get(url, timeout=ClientTimeout(total=TIMEOUT)) as response:
            # A device that is starting can answer 404, and an error page
            # isn't its info
            if response.status != HTTPStatus.OK:
                _LOGGER.debug(
                    "%s answered %d when asked for its info", host, response.status
                )
                return None
            try:
                info = await response.json()
            # An answer that isn't JSON, though it has come whole
            except ContentTypeError, ValueError:
                _LOGGER.debug("%s answered, but not with its info", host, exc_info=True)
                info = None
            reachable = True
    finally:
        if device is not None:
            device.reachable = reachable
    return info if isinstance(info, dict) else None


async def async_get_info_status(
    session: ClientSession, device: GoogleHomeDevice
) -> int | None:
    """Return the status of the device's answer when asked for its info, without its token.

    A 200 counts once its body has come, another status as soon as it comes, and
    isn't undone if the answer then breaks off. Return None if no answer comes, for
    example when the session rejects a redirect. Redirects aren't followed. The
    session itself may try once more after a lost connection.
    """
    assert device.ip_address is not None
    url = create_url(device.ip_address, PORT, API_ENDPOINT_EUREKA_INFO)
    status: int | None = None
    try:
        async with session.get(
            url, timeout=ClientTimeout(total=TIMEOUT), allow_redirects=False
        ) as response:
            if response.status != HTTPStatus.OK:
                status = response.status
            else:
                await response.read()
                status = HTTPStatus.OK
    except ClientError, TimeoutError:
        if status is None:
            _LOGGER.debug(
                "%s didn't answer when asked for its info",
                device.name,
                exc_info=True,
            )
    return status


def lacks_assistant(info: dict[str, object] | None) -> bool:
    """Return whether a device's info lists its features without Google Assistant.

    Google and Nest speakers and displays report assistant_supported as true. A
    Chromecast Audio leaves it out of its list, so a missing key counts as no, as
    does false. No list, an empty one, or any other value says nothing either way.
    """
    device_info = info.get("device_info") if info else None
    capabilities = (
        device_info.get("capabilities") if isinstance(device_info, dict) else None
    )
    if not isinstance(capabilities, dict) or not capabilities:
        return False
    # Only the JSON false: 0, null or "false" isn't a clear answer
    return capabilities.get("assistant_supported", False) is False

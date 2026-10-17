"""Tests for finding devices at known hosts when mDNS can't."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

from aiohttp import ClientError
from glocaltokens.client import Device
from glocaltokens.scanner import NetworkDevice

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.config_flow import GoogleHomeOptionsFlowHandler
from custom_components.google_home.models import GoogleHomeDevice

# glocaltokens accepts only tokens of the real length
MASTER_TOKEN = "aas_et/" + "x" * 216
LOCAL_AUTH_TOKEN = "x" * 108


def fake_session(answers: dict[str, tuple[str, str] | Exception]) -> Mock:
    """Return a session where each host reports a name and Google's ID, or fails."""

    def get(url: str, **_kwargs: object) -> MagicMock:
        answer = answers[url.split("//")[1].split(":", maxsplit=1)[0]]
        response = MagicMock()
        if isinstance(answer, Exception):
            response.__aenter__.side_effect = answer
        else:
            name, cloud_device_id = answer
            response.__aenter__.return_value.json = AsyncMock(
                return_value={
                    "name": name,
                    "device_info": {"cloud_device_id": cloud_device_id},
                }
            )
        return response

    return Mock(get=get)


def use_known_hosts(
    devices: list[GoogleHomeDevice], answers: dict[str, tuple[str, str] | Exception]
) -> None:
    """Match the known hosts to the devices that Google returned."""
    client = GlocaltokensApiClient(
        Mock(),
        fake_session(answers),
        master_token=MASTER_TOKEN,
        known_hosts=list(answers),
    )
    client.google_devices = devices
    asyncio.run(client.async_use_known_hosts())


def device(
    name: str, cloud_device_id: str, ip_address: str | None = None
) -> GoogleHomeDevice:
    """Return a device as Google lists it."""
    return GoogleHomeDevice(
        name.lower(),
        name,
        "token",
        ip_address=ip_address,
        cloud_device_id=cloud_device_id,
    )


def test_known_hosts_fill_in_missing_addresses() -> None:
    """Give a device that mDNS didn't find the address of the host that reports it."""
    kitchen = device("Kitchen", "AAAA")
    office = device("Office", "BBBB", ip_address="10.0.0.2")
    bedroom = device("Bedroom", "CCCC")

    use_known_hosts(
        [kitchen, office, bedroom],
        {
            "10.0.1.5": ("Kitchen speaker", "aaaa"),
            "10.0.1.6": ("Office", "bbbb"),
            "10.0.1.7": ClientError("No route to host"),
        },
    )

    # Matched by ID, whatever the name and the case
    assert kitchen.ip_address == "10.0.1.5"
    # mDNS found it, so its address stays
    assert office.ip_address == "10.0.0.2"
    assert bedroom.ip_address is None


def test_known_hosts_find_speaker_pair() -> None:
    """Find a speaker pair at its leading speaker, even when the other comes first."""
    pair = device("Den speakers", "dddd")

    use_known_hosts(
        [pair],
        {
            # The other speaker reports its own ID, which Google doesn't list
            "10.0.1.9": ("Den speaker right", "eeee"),
            "10.0.1.8": ("Den speaker left", "dddd"),
        },
    )

    assert pair.ip_address == "10.0.1.8"


def test_known_hosts_use_first_host_of_a_device() -> None:
    """Use the first host when several report the same device, as mDNS does."""
    pair = device("Den speakers", "dddd")

    use_known_hosts(
        [pair],
        {
            "10.0.1.8": ("Den speaker left", "dddd"),
            "10.0.1.9": ("Den speaker right", "dddd"),
        },
    )

    assert pair.ip_address == "10.0.1.8"


def make_options_flow(options: dict[str, object]) -> GoogleHomeOptionsFlowHandler:
    """Return the options flow of an entry with these options."""
    flow = GoogleHomeOptionsFlowHandler()
    flow.hass = Mock()
    flow.hass.config_entries.async_get_known_entry.return_value = Mock(options=options)
    flow.handler = "entry-id"
    return flow


def test_options_save_known_hosts() -> None:
    """Save known hosts without blanks, surrounding spaces and repeats, in order."""
    flow = make_options_flow({})

    result = asyncio.run(
        flow.async_step_init(
            {
                "update_interval": 180,
                "known_hosts": [" 10.0.1.5 ", "", "fd00::5", "10.0.1.5"],
            }
        )
    )

    assert result["type"] == "create_entry"
    assert result["data"] == {
        "update_interval": 180,
        "known_hosts": ["10.0.1.5", "fd00::5"],
    }


def test_options_reject_hostnames() -> None:
    """Ask for IP addresses, as requests to devices are built from them."""
    flow = make_options_flow({"known_hosts": ["10.0.1.5"]})

    result = asyncio.run(
        flow.async_step_init({"update_interval": 180, "known_hosts": ["kitchen.local"]})
    )

    assert result["type"] == "form"
    assert result["errors"] == {"known_hosts": "known-host-not-ip"}


def test_known_hosts_fill_in_devices_from_glocaltokens() -> None:
    """Find a device that glocaltokens returns without an address at its known host."""
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    client = GlocaltokensApiClient(
        hass,
        fake_session({"10.0.1.5": ("Den speaker left", "dddd")}),
        master_token=MASTER_TOKEN,
        known_hosts=["10.0.1.5"],
    )
    pair = Device("pair", "Den speakers", LOCAL_AUTH_TOKEN, cloud_device_id="DDDD")
    client._client = Mock(  # noqa: SLF001  # pylint: disable=protected-access
        get_google_devices=Mock(return_value=[pair]),
        homegraph=Mock(),
    )

    [den] = asyncio.run(client.get_google_devices())

    assert den.name == "Den speakers"
    assert den.cloud_device_id == "dddd"
    assert den.ip_address == "10.0.1.5"


def test_known_hosts_not_asked_when_mdns_found_everything() -> None:
    """Don't wait on known hosts when mDNS found an address for every device."""
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    session = Mock()
    client = GlocaltokensApiClient(
        hass, session, master_token=MASTER_TOKEN, known_hosts=["10.0.1.5"]
    )
    found_by_mdns = Device(
        "kitchen",
        "Kitchen",
        LOCAL_AUTH_TOKEN,
        NetworkDevice("Kitchen", "10.0.0.3", 8009, "Nest Audio", "aaaa"),
        cloud_device_id="AAAA",
    )
    client._client = Mock(  # noqa: SLF001  # pylint: disable=protected-access
        get_google_devices=Mock(return_value=[found_by_mdns]),
        homegraph=Mock(),
    )

    asyncio.run(client.get_google_devices())

    session.get.assert_not_called()


def test_known_hosts_skip_addresses_mdns_found() -> None:
    """Don't ask a known host whose address mDNS already gave to a device."""
    office = device("Office", "BBBB", ip_address="fd00::2")
    kitchen = device("Kitchen", "AAAA")
    answers: dict[str, tuple[str, str] | Exception] = {
        # The same address as the office speaker's, written differently
        "fd00:0::2": AssertionError("asked a host that mDNS already found"),
        "10.0.1.5": ("Kitchen", "aaaa"),
    }

    use_known_hosts([office, kitchen], answers)

    assert kitchen.ip_address == "10.0.1.5"
    assert office.ip_address == "fd00::2"

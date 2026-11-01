"""The fix of the repair that says polling is turned off."""

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_POLLING_DISABLED, POLLING_DOCS_URL


class PollingDisabledFlow(RepairsFlow):
    """Turn polling back on, or keep it off and hide the repair."""

    async def async_step_init(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Say what polling being off means, and offer both choices."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["turn_on", "keep_off"],
            description_placeholders={"docs_url": POLLING_DOCS_URL},
        )

    async def async_step_turn_on(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Turn polling on and reload the entry, as the system options do.

        Home Assistant then removes the repair.
        """
        entries = self.hass.config_entries
        if self.data is not None and (
            entry := entries.async_get_entry(str(self.data["entry_id"]))
        ):
            entries.async_update_entry(entry, pref_disable_polling=False)
            entries.async_schedule_reload(entry.entry_id)
        return self.async_create_entry(data={})

    async def async_step_keep_off(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Hide the repair and leave polling off.

        Not a finished fix, which Home Assistant would remove the repair for, so setup
        would show it again. Home Assistant keeps it hidden over restarts until setup
        removes it, once polling is on, which may also have happened while the menu
        was open.
        """
        if ir.async_get(self.hass).async_get_issue(DOMAIN, ISSUE_POLLING_DISABLED):
            ir.async_ignore_issue(self.hass, DOMAIN, ISSUE_POLLING_DISABLED, True)
        return self.async_abort(reason="polling_kept_off")


async def async_create_fix_flow(
    _hass: HomeAssistant,
    _issue_id: str,
    _data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix of the integration's only fixable repair."""
    return PollingDisabledFlow()

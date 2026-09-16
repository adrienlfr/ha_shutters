"""Regression coverage for the shared telework end timer."""

import asyncio
from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.parametrize("end", [time(18), time(6, 30, 15)])
def test_telework_turns_off_and_is_saved_for_every_window(integration, end):
    manager = integration.global_settings.GlobalSettingsManager(MagicMock())
    manager.settings.update(telework_enabled=True, telework_end=end.isoformat())
    controllers = [
        SimpleNamespace(
            entry=SimpleNamespace(entry_id=str(index)),
            async_global_settings_updated=AsyncMock(),
        )
        for index in range(2)
    ]
    for controller in controllers:
        manager.register(controller)
    tracker = integration.global_settings.async_track_time_change
    tracker.assert_called_once_with(
        manager.hass,
        manager._async_telework_end,
        hour=end.hour,
        minute=end.minute,
        second=end.second,
    )

    callback = tracker.call_args.args[1]
    asyncio.run(callback(datetime(2026, 9, 16, end.hour, end.minute, end.second)))

    assert manager.settings["telework_enabled"] is False
    manager._store.async_save.assert_awaited_once_with(manager.settings)
    for controller in controllers:
        controller.async_global_settings_updated.assert_awaited_once()
    # The following day must not re-enable telework or rewrite unchanged state.
    asyncio.run(callback(datetime(2026, 9, 17, end.hour, end.minute, end.second)))
    assert manager.settings["telework_enabled"] is False
    assert manager._store.async_save.await_count == 1


def test_end_time_changes_and_unload_manage_single_listener(integration):
    manager = integration.global_settings.GlobalSettingsManager(MagicMock())
    controller = SimpleNamespace(
        entry=SimpleNamespace(entry_id="window"),
        async_global_settings_updated=AsyncMock(),
    )
    tracker = integration.global_settings.async_track_time_change
    first_cancel, second_cancel = MagicMock(), MagicMock()
    tracker.side_effect = [first_cancel, second_cancel, MagicMock()]
    manager.register(controller)

    asyncio.run(manager.async_update("telework_end", time(17, 30)))

    first_cancel.assert_called_once()
    assert tracker.call_args.kwargs == {"hour": 17, "minute": 30, "second": 0}
    manager.unregister("window")
    second_cancel.assert_called_once()
    manager.register(controller)
    assert tracker.call_count == 3

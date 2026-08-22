"""Tests for SolaxModbusGrowattController control_mode="vpp".

Verifies the VPP remote-power-control path (issue #118):
- No TOU segment writes — remote_control/power/time entities only
- VPP Status/AC-charging enabled once, not every period
- Intent -> power mapping mirrors SolaxController
- Fallback timer state survives controller re-instantiation via read-back
- health check gates on VPP entities, not TOU entities
"""

from datetime import datetime
from unittest.mock import patch

import pytest  # type: ignore

from core.bess.dp_schedule import DPSchedule
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.conftest import MockHomeAssistantController


def hourly_to_quarterly(
    hourly_intents: dict[int, str], default: str = "IDLE"
) -> list[str]:
    quarterly = [default] * 96
    for hour, intent in hourly_intents.items():
        for period in range(hour * 4, (hour + 1) * 4):
            quarterly[period] = intent
    return quarterly


def make_schedule(intents: list[str], actions: list[float] | None = None) -> DPSchedule:
    return DPSchedule(
        actions=actions if actions is not None else [0.0] * len(intents),
        state_of_energy=[25.0] * (len(intents) + 1),
        prices=[0.1] * len(intents),
        original_dp_results={"strategic_intent": intents},
    )


@pytest.fixture
def battery_settings():
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


@pytest.fixture
def controller(battery_settings):
    return SolaxModbusGrowattController(battery_settings, control_mode="vpp")


@pytest.fixture
def mock_ha():
    return MockHomeAssistantController()


def _apply_at_period(
    controller,
    mock_ha,
    period,
    grid_charge,
    discharge_rate,
    block_passive_charging=False,
    strategic_intent="",
):
    hour = period // 4
    minute = (period % 4) * 15
    with patch("core.bess.solax_modbus_growatt_controller.time.sleep"):
        with patch("core.bess.solax_modbus_growatt_controller.time_utils") as mock_time:
            mock_time.now.return_value = datetime(2026, 5, 20, hour, minute, 0)
            controller.apply_period(
                mock_ha,
                grid_charge,
                discharge_rate,
                block_passive_charging,
                strategic_intent,
            )


class TestControlModeValidation:
    def test_rejects_unknown_control_mode(self, battery_settings):
        with pytest.raises(ValueError):
            SolaxModbusGrowattController(battery_settings, control_mode="bogus")

    def test_defaults_to_tou(self, battery_settings):
        controller = SolaxModbusGrowattController(battery_settings)
        assert controller.control_mode == "tou"


class TestIntentToVpp:
    def test_grid_charge_maps_to_full_charge_power(self, controller):
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=True, discharge_rate=0
        )
        assert power_pct == 100
        assert enabled is True

    def test_solar_storage_disables_remote_control(self, controller):
        """SOLAR_STORAGE (block_passive_charging=False) -> self-use, battery
        may absorb solar surplus."""
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False,
            discharge_rate=0,
            block_passive_charging=False,
            strategic_intent="SOLAR_STORAGE",
        )
        assert power_pct == 0
        assert enabled is False

    def test_idle_enables_battery_first_hold(self, controller):
        """#466: IDLE must not fall back to native load_first self-use --
        load_first discharges the battery to cover house load, but the DP's
        own cost model (_idle_battery_flows) never credits battery discharge
        during IDLE. remote_control=Enabled, vpp_power=+1 (battery first)
        keeps self-consumption on grid/solar instead of draining the
        battery, per the Growatt VPP protocol V2.01 section 3.5."""
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False,
            discharge_rate=0,
            block_passive_charging=False,
            strategic_intent="IDLE",
        )
        assert power_pct == 1
        assert enabled is True

    def test_idle_at_reserve_floor_releases_remote_control(
        self, controller: SolaxModbusGrowattController
    ) -> None:
        """#592: at the reserve floor the battery-first hold has nothing left
        to protect, but keeping remote control enabled re-asserts a command
        every period so the inverter (and its BMS) never sleeps.

        Releasing to the inverter's own load_first self-use is flow-neutral
        here -- there is no headroom to discharge (the hardware's own
        discharge_stop_soc register is the floor) and passive solar
        absorption is preserved, which grid_first (power=0, enabled) would
        lose. See test_idle_at_floor_is_flow_neutral in
        test_vpp_simulator_branches.py for the outcome-level proof."""
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False,
            discharge_rate=0,
            block_passive_charging=False,
            strategic_intent="IDLE",
            at_reserve_floor=True,
        )
        assert power_pct == 0
        assert enabled is False

    def test_idle_above_reserve_floor_still_holds_battery_first(
        self, controller: SolaxModbusGrowattController
    ) -> None:
        """#592 must not weaken #466: above the floor there IS energy being
        held back for a later peak, so the battery-first hold stays."""
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False,
            discharge_rate=0,
            block_passive_charging=False,
            strategic_intent="IDLE",
            at_reserve_floor=False,
        )
        assert power_pct == 1
        assert enabled is True

    def test_solar_export_keeps_remote_control_enabled(self, controller):
        """SOLAR_EXPORT (block_passive_charging=True) -> grid-first hold,
        not self-use -- see #355. Remote control stays enabled with
        power=0 instead of being disabled."""
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False, discharge_rate=0, block_passive_charging=True
        )
        assert power_pct == 0
        assert enabled is True

    def test_discharge_rate_maps_to_negative_power(self, controller):
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False, discharge_rate=60
        )
        assert power_pct == -60
        assert enabled is True

    def test_battery_export_still_forces_fixed_rate(self, controller):
        """BATTERY_EXPORT must keep forcing a fixed grid_first rate --
        only LOAD_SUPPORT releases control (#413)."""
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False, discharge_rate=60, strategic_intent="BATTERY_EXPORT"
        )
        assert power_pct == -60
        assert enabled is True

    def test_load_support_releases_vpp_control(self, controller):
        """#413: LOAD_SUPPORT must release VPP control (fall back to the
        inverter's own load-following self-use) instead of forcing a fixed
        discharge rate via grid_first -- a fixed rate causes unnecessary
        grid imports/exports whenever the schedule's load prediction misses.
        """
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False, discharge_rate=60, strategic_intent="LOAD_SUPPORT"
        )
        assert power_pct == 0
        assert enabled is False

    def test_load_support_releases_vpp_control_at_zero_discharge_rate(self, controller):
        """PR #414 review: LOAD_SUPPORT's INTENT_TO_CONTROL charge_rate is 0
        (same as BATTERY_EXPORT/SOLAR_EXPORT), so block_passive_charging is
        True for it in production (compute_rates_for_period). Whenever the
        DP plan calls for no net discharge, or discharge-inhibit forces the
        rate to 0, discharge_rate is 0 too -- both common, not edge cases.
        The discharge_rate==0 branch must not take priority over the
        LOAD_SUPPORT release for real block_passive_charging=True callers.
        """
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False,
            discharge_rate=0,
            block_passive_charging=True,
            strategic_intent="LOAD_SUPPORT",
        )
        assert power_pct == 0
        assert enabled is False


class TestApplyPeriodVpp:
    def test_no_tou_segments_written(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)

        assert mock_ha.calls["tou_segments"] == []
        assert mock_ha.calls["grid_charge"] == []
        assert mock_ha.calls["discharge_rate"] == []

    def test_vpp_status_enabled_once(self, controller, mock_ha):
        """VPP Status/AC-charging are written once, not on every period."""
        intents = hourly_to_quarterly({2: "GRID_CHARGING", 4: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)
        _apply_at_period(controller, mock_ha, 9, grid_charge=True, discharge_rate=0)

        assert len(mock_ha.calls["growatt_vpp_status"]) == 1
        assert len(mock_ha.calls["growatt_vpp_allow_ac_charging"]) == 1

    def test_charge_period_writes_positive_power(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is True
        assert period["power_pct"] == 100
        assert period["fallback_minutes"] == 20

    def test_discharge_period_writes_negative_power(self, controller, mock_ha):
        intents = hourly_to_quarterly({10: "BATTERY_EXPORT"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        _apply_at_period(
            controller,
            mock_ha,
            40,
            grid_charge=False,
            discharge_rate=70,
            strategic_intent="BATTERY_EXPORT",
        )

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is True
        assert period["power_pct"] == -70

    def test_load_support_releases_remote_control_on_hardware(
        self, controller, mock_ha
    ):
        """#413: unlike BATTERY_EXPORT, LOAD_SUPPORT must disable
        vpp_remote_control on the hardware write, not force a fixed rate."""
        intents = hourly_to_quarterly({10: "LOAD_SUPPORT"})
        controller.apply_intents(make_schedule(intents), current_period=0)
        controller._last_written_vpp_remote_control = True  # force a change

        _apply_at_period(
            controller,
            mock_ha,
            40,
            grid_charge=False,
            discharge_rate=70,
            strategic_intent="LOAD_SUPPORT",
        )

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is False
        assert period["power_pct"] == 0

    def test_idle_enables_battery_first_hold_on_hardware(self, controller, mock_ha):
        """#466: IDLE must write remote_control=Enabled, power=+1 (battery
        first) instead of falling back to native load_first self-use."""
        intents = hourly_to_quarterly({0: "IDLE"})
        controller.apply_intents(make_schedule(intents), current_period=0)
        controller._last_written_vpp_remote_control = False  # force a change

        _apply_at_period(
            controller,
            mock_ha,
            0,
            grid_charge=False,
            discharge_rate=0,
            block_passive_charging=False,
            strategic_intent="IDLE",
        )

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is True
        assert period["power_pct"] == 1

    def test_solar_export_keeps_remote_control_enabled_on_hardware(
        self, controller, mock_ha
    ):
        """#355: SOLAR_EXPORT must not fall back to self-use, which lets
        solar surplus recharge the battery instead of exporting it."""
        intents = hourly_to_quarterly({0: "SOLAR_EXPORT"})
        controller.apply_intents(make_schedule(intents), current_period=0)
        controller._last_written_vpp_remote_control = False  # force a change

        _apply_at_period(
            controller,
            mock_ha,
            0,
            grid_charge=False,
            discharge_rate=0,
            block_passive_charging=True,
        )

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is True
        assert period["power_pct"] == 0

    def test_unchanged_active_command_refreshes_timer(self, controller, mock_ha):
        """#404: a stable run of identical active periods must still write,
        or the inverter's fallback timer lapses and it reverts to load_first."""
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)
        writes_after_first = len(mock_ha.calls["growatt_vpp_periods"])

        # Same active command again — must still write to refresh the timer
        _apply_at_period(controller, mock_ha, 9, grid_charge=True, discharge_rate=0)
        assert len(mock_ha.calls["growatt_vpp_periods"]) == writes_after_first + 1

    def test_unchanged_disabled_command_skips_write(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "SOLAR_STORAGE"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=False, discharge_rate=0)
        writes_after_first = len(mock_ha.calls["growatt_vpp_periods"])

        # Same disabled (load_first) command again — nothing active, no
        # timer to protect, so the write is still skipped.
        _apply_at_period(controller, mock_ha, 9, grid_charge=False, discharge_rate=0)
        assert len(mock_ha.calls["growatt_vpp_periods"]) == writes_after_first

    def test_power_change_within_active_control_triggers_write(
        self, controller, mock_ha
    ):
        intents = hourly_to_quarterly({0: "BATTERY_EXPORT"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 0, grid_charge=False, discharge_rate=50)
        _apply_at_period(controller, mock_ha, 1, grid_charge=False, discharge_rate=80)

        assert len(mock_ha.calls["growatt_vpp_periods"]) == 2
        assert mock_ha.calls["growatt_vpp_periods"][-1]["power_pct"] == -80


class TestWriteScheduleToHardwareVpp:
    """VPP has no persistent/bulk schedule to push — sync_to_hardware is a
    no-op for power (like SolaxController's), same as its class docstring
    already claims. The real per-period power command always comes from
    apply_period via BatterySystemManager._apply_period_schedule, which runs
    immediately after sync_to_hardware in the same update_battery_schedule
    cycle (#421)."""

    def test_returns_zero_writes_zero_disables(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        writes, disables = controller.sync_to_hardware(mock_ha, effective_period=8)

        assert writes == 0
        assert disables == 0

    def test_no_vpp_power_command_written(self, controller, mock_ha):
        """#421: sync_to_hardware previously computed power from a
        hardcoded battery_action_kw=0.0 stub, sending a spurious power=0%
        command that briefly preceded the correct value written moments
        later by apply_period. It must not write any VPP power at all."""
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        controller.sync_to_hardware(mock_ha, effective_period=8)

        assert mock_ha.calls["growatt_vpp_periods"] == []

    def test_no_vpp_power_command_written_for_real_discharge_action(
        self, controller, mock_ha
    ):
        """Reproduces the exact #421 scenario: a BATTERY_EXPORT period with a
        real nonzero planned discharge (period 77, -2.48 kWh / -9.90 kW in
        the reported debug log) must not produce a spurious power=0% write
        from sync_to_hardware — the stub battery_action_kw=0.0 previously
        made this look like "no action", forcing discharge_rate=0."""
        intents = hourly_to_quarterly({19: "BATTERY_EXPORT"})
        actions = [0.0] * 96
        actions[77] = -2.48
        controller.apply_intents(make_schedule(intents, actions), current_period=77)

        controller.sync_to_hardware(mock_ha, effective_period=77)

        assert mock_ha.calls["growatt_vpp_periods"] == []

    def test_vpp_status_enabled_via_sync_to_hardware(self, controller, mock_ha):
        """The one-time VPP Status/AC-charging enable sequence is still
        sync_to_hardware's job, per the class docstring."""
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        controller.sync_to_hardware(mock_ha, effective_period=8)

        assert len(mock_ha.calls["growatt_vpp_status"]) == 1
        assert len(mock_ha.calls["growatt_vpp_allow_ac_charging"]) == 1


class TestReadAndInitializeVpp:
    def test_seeds_state_from_hardware(self, controller, mock_ha):
        mock_ha._growatt_vpp_status_state = "Enabled"
        mock_ha._growatt_vpp_allow_ac_charging_state = "Enabled"
        mock_ha._growatt_vpp_remote_control_state = "Enabled"

        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert controller._vpp_status_confirmed is True
        assert controller._vpp_ac_charging_confirmed is True
        assert controller._last_written_vpp_remote_control is True

    def test_seeds_disabled_state(self, controller, mock_ha):
        mock_ha._growatt_vpp_status_state = "Disabled"
        mock_ha._growatt_vpp_allow_ac_charging_state = "Disabled"
        mock_ha._growatt_vpp_remote_control_state = "Disabled"

        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert controller._vpp_status_confirmed is False
        assert controller._vpp_ac_charging_confirmed is False
        assert controller._last_written_vpp_remote_control is False

    def test_no_hardware_writes_on_read(self, controller, mock_ha):
        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert mock_ha.calls["growatt_vpp_status"] == []
        assert mock_ha.calls["growatt_vpp_periods"] == []

    def test_restart_with_status_already_enabled_writes_no_flash_registers(
        self, controller, mock_ha
    ):
        """#399 (ridax67), the symptom as reported: *"at startup allow ac grid
        charging and vpp_status are always set. In most cases these writes are
        not needed as they don't reset between runs, so if you test if they
        need to be set first, you will avoid a lot of flash writes for frequent
        restarters."*

        `test_seeds_state_from_hardware` above asserts the read-back sets
        `_vpp_status_confirmed`. That is the mechanism, not the symptom — it
        stays green if the flag is seeded correctly and then ignored. This
        asserts the outcome ridax measured: a **fresh controller** (what a
        restart produces) that reads back an already-enabled inverter performs
        **zero** writes to either flash register while going on to command a
        normal period.

        #329's `TestNoRedundantWritesAcrossCycles` covers the adjacent case —
        the same instance applying twice — which never exercises the read-back
        path at all, because that instance already has the flag set from its
        own first write.
        """
        mock_ha._growatt_vpp_status_state = "Enabled"
        mock_ha._growatt_vpp_allow_ac_charging_state = "Enabled"
        mock_ha._growatt_vpp_remote_control_state = "Enabled"

        # A restart: a brand-new controller, as BESS constructs each cycle.
        restarted = type(controller)(controller.battery_settings, control_mode="vpp")
        restarted.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        restarted.apply_intents(
            make_schedule(hourly_to_quarterly({2: "GRID_CHARGING"})), current_period=0
        )
        _apply_at_period(restarted, mock_ha, 8, grid_charge=True, discharge_rate=0)

        assert mock_ha.calls["growatt_vpp_status"] == [], (
            "restart re-wrote VPP Status although the inverter already "
            "reported Enabled — this is #399's flash wear"
        )
        assert mock_ha.calls["growatt_vpp_allow_ac_charging"] == [], (
            "restart re-wrote allow-AC-charging although VPP was already "
            "enabled — this is #399's flash wear"
        )
        assert mock_ha.calls["growatt_vpp_periods"], (
            "the period command itself must still be written, or this test "
            "passes by the controller doing nothing at all"
        )

    def test_restart_repairs_ac_charging_when_only_status_is_enabled(
        self, controller, mock_ha
    ):
        """The other half of #399's skip: it must not skip a write the
        inverter still needs.

        `_ensure_vpp_status_enabled` writes *both* flash registers, and they
        can drift apart -- a user toggle, a firmware reset, or a write that
        failed after the first of the two. An earlier revision gated both
        writes on one flag seeded from VPP Status alone, so an inverter
        reporting Status Enabled + AC charging Disabled was treated as fully
        configured on every restart, the AC-charging write never happened
        again, and GRID_CHARGING periods silently drew nothing from the grid.

        The repair is per register: the drifted one is rewritten and the
        healthy one is left alone, or the repair path itself reintroduces
        #399's wear on every restart of a half-drifted install.

        The flash-wear guard above and this one are the same mechanism read
        from both sides: skip when nothing is needed, repair when something
        is.
        """
        mock_ha._growatt_vpp_status_state = "Enabled"
        mock_ha._growatt_vpp_allow_ac_charging_state = "Disabled"
        mock_ha._growatt_vpp_remote_control_state = "Enabled"

        restarted = type(controller)(controller.battery_settings, control_mode="vpp")
        restarted.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        restarted.apply_intents(
            make_schedule(hourly_to_quarterly({2: "GRID_CHARGING"})), current_period=0
        )
        _apply_at_period(restarted, mock_ha, 8, grid_charge=True, discharge_rate=0)

        assert mock_ha.calls["growatt_vpp_allow_ac_charging"] == [True], (
            "an inverter that cannot AC-charge was left that way: "
            "GRID_CHARGING would draw nothing from the grid"
        )
        assert mock_ha.calls["growatt_vpp_status"] == [], (
            "the healthy VPP Status register was rewritten while repairing "
            "AC charging — #399's flash wear, moved into the repair path"
        )

    def test_restart_repairs_only_the_register_it_could_not_read(
        self, controller, mock_ha
    ):
        """An unreadable register is *unknown*, not "Disabled".

        `_get_raw_state` returns None for a transient API error or a
        momentarily `unavailable` entity just as it does for one that is not
        configured. Unknown still has to be repaired -- assuming Enabled would
        leave VPP unable to execute its plan with no further chance to fix it
        -- but the repair must stay scoped to the register that could not be
        read, or one flaky read at startup rewrites both flash registers.
        """
        mock_ha._growatt_vpp_status_state = "Enabled"
        mock_ha._growatt_vpp_allow_ac_charging_state = None
        mock_ha._growatt_vpp_remote_control_state = "Enabled"

        restarted = type(controller)(controller.battery_settings, control_mode="vpp")
        restarted.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        restarted.apply_intents(
            make_schedule(hourly_to_quarterly({2: "GRID_CHARGING"})), current_period=0
        )
        _apply_at_period(restarted, mock_ha, 8, grid_charge=True, discharge_rate=0)

        assert mock_ha.calls["growatt_vpp_allow_ac_charging"] == [True]
        assert mock_ha.calls["growatt_vpp_status"] == [], (
            "a failed read of one register rewrote the other, which was known "
            "to be Enabled — #399's flash wear on a flaky read"
        )


class TestNoRedundantWritesAcrossCycles:
    """#329: applying the same intents twice in a row on the SAME controller
    instance (no recreation at all, unlike #368's simulated-recreation test)
    must not re-write VPP status/allow-AC-charging the second time."""

    def test_apply_intents_twice_writes_vpp_status_once(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        schedule = make_schedule(intents)

        controller.apply_intents(schedule, current_period=0)
        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)
        assert len(mock_ha.calls["growatt_vpp_status"]) == 1

        # Re-apply the identical schedule -- same instance, no recreation
        controller.apply_intents(schedule, current_period=0)
        _apply_at_period(controller, mock_ha, 9, grid_charge=True, discharge_rate=0)

        assert len(mock_ha.calls["growatt_vpp_status"]) == 1
        assert len(mock_ha.calls["growatt_vpp_allow_ac_charging"]) == 1


class TestCheckHealthVpp:
    def test_checks_vpp_entities_not_tou_entities(self, controller, mock_ha):
        mock_ha.sensors = {
            **mock_ha.sensors,
            "growatt_vpp_status": "select.growatt_vpp_status",
            "growatt_vpp_remote_control": "select.growatt_vpp_remote_control",
            "growatt_vpp_allow_ac_charging": "select.growatt_vpp_allow_ac_charging",
            "growatt_vpp_time": "number.growatt_vpp_time",
            "growatt_vpp_power": "number.growatt_vpp_power",
        }

        [health] = controller.check_health(mock_ha)

        checked_keys = {c["key"] for c in health["checks"]}
        assert "growatt_vpp_status" in checked_keys
        assert "growatt_vpp_power" in checked_keys
        assert "tou_time_1_enabled" not in checked_keys

    def test_missing_vpp_entity_is_error(self, controller, mock_ha):
        [health] = controller.check_health(mock_ha)
        assert health["status"] == "ERROR"

    def test_ems_rate_and_stop_soc_not_required(self, controller, mock_ha):
        """VPP setups commonly have these EMS entities disabled in HA
        (they're unused in VPP mode) — health check must not require them."""
        mock_ha.sensors = {
            **mock_ha.sensors,
            "growatt_vpp_status": "select.growatt_vpp_status",
            "growatt_vpp_remote_control": "select.growatt_vpp_remote_control",
            "growatt_vpp_allow_ac_charging": "select.growatt_vpp_allow_ac_charging",
            "growatt_vpp_time": "number.growatt_vpp_time",
            "growatt_vpp_power": "number.growatt_vpp_power",
        }

        [health] = controller.check_health(mock_ha)

        checked_methods = {c["method_name"] for c in health["checks"]}
        assert "get_charge_stop_soc" not in checked_methods
        assert "get_discharge_stop_soc" not in checked_methods
        assert "get_charging_power_rate" not in checked_methods
        assert "get_discharging_power_rate" not in checked_methods
        assert health["status"] == "OK"


class TestVppInitDoesNotTouchTou:
    def test_initialize_hardware_writes_no_tou_segments(self, controller, mock_ha):
        """VPP mode must never read or write TOU entities (#309, #302)."""
        mock_ha.read_tou_segments_from_entities = lambda: [
            {
                "segment_id": 1,
                "batt_mode": "battery_first",
                "start_time": "00:00",
                "end_time": "23:59",
                "enabled": True,
            }
        ]

        controller.initialize_hardware(mock_ha)

        assert mock_ha.calls["tou_segments"] == []


class TestGetAllTouSegmentsVppMode:
    def test_get_all_tou_segments_vpp_mode_solar_export_has_no_batt_mode(
        self, controller
    ):
        controller.strategic_intents = ["SOLAR_EXPORT"] * 96
        controller.current_schedule = None
        segments = controller.get_all_tou_segments()
        assert len(segments) >= 1
        segment = segments[0]
        assert "batt_mode" not in segment
        assert segment["vpp_power_pct"] == 0
        assert segment["vpp_remote_control"] is True

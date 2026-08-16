"""CONTROL_MODEL must correctly classify every controller's real hardware model."""

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.huawei_controller import HuaweiController
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.solis_modbus_controller import SolisModbusController
from core.bess.tests.helpers import make_battery_settings


def _make(cls, **kwargs):
    battery_settings = make_battery_settings()
    return cls(battery_settings=battery_settings, **kwargs)


def test_growatt_min_is_tou_register():
    controller = _make(GrowattMinController)
    assert controller.CONTROL_MODEL == "tou_register"


def test_solax_modbus_growatt_tou_mode_is_tou_register():
    controller = _make(SolaxModbusGrowattController, control_mode="tou")
    assert controller.CONTROL_MODEL == "tou_register"


def test_solax_modbus_growatt_vpp_mode_is_vpp_power():
    controller = _make(SolaxModbusGrowattController, control_mode="vpp")
    assert controller.CONTROL_MODEL == "vpp_power"


def test_solax_controller_is_vpp_power():
    controller = _make(SolaxController)
    assert controller.CONTROL_MODEL == "vpp_power"


def test_growatt_sph_is_period_list():
    controller = _make(GrowattSphController)
    assert controller.CONTROL_MODEL == "period_list"


def test_solis_modbus_is_period_list():
    controller = _make(SolisModbusController)
    assert controller.CONTROL_MODEL == "period_list"


def test_huawei_is_period_list():
    controller = _make(HuaweiController)
    assert controller.CONTROL_MODEL == "period_list"


# ── The two capability flags, and what binds them (Phase 4b) ────────────────


def _exact_cover_controllers():
    """Every shipped controller configuration, as (label, instance)."""
    return [
        ("growatt_min", _make(GrowattMinController)),
        (
            "solax_modbus_growatt/tou",
            _make(SolaxModbusGrowattController, control_mode="tou"),
        ),
        (
            "solax_modbus_growatt/vpp",
            _make(SolaxModbusGrowattController, control_mode="vpp"),
        ),
        ("solax_native", _make(SolaxController)),
        ("growatt_sph", _make(GrowattSphController)),
        ("solis_modbus", _make(SolisModbusController)),
        ("huawei", _make(HuaweiController)),
    ]


def test_exact_cover_is_only_declared_where_the_written_rate_can_deliver_it():
    """Two different flags decide two halves of the same promise, and nothing
    in the type system stops them diverging.

    `load_support_delivers_exact_cover` decides whether the DP may plan a
    partial load cover (`action_selector._residual_cover_p`).
    `discharge_rate_is_load_following` decides whether the written rate is
    rounded UP as a ceiling or to nearest as a target
    (`execution_model.command_index`). If a platform ever declares
    cover=True with a *target* rate, the DP plans a delivery the write path
    rounds to something else -- R != P, the #282 shape this phase exists to
    end.

    Exactly one configuration is in that combination today, and it is safe
    for a reason that lives in a third file: solax-modbus Growatt in VPP mode
    writes *no* LOAD_SUPPORT rate at all (#413 hands the period to the
    inverter's own self-use), so there is no rounding to get wrong. This test
    pins that reasoning where it can fail, so a new platform cannot inherit
    the combination without someone proving the same thing.
    """
    # Anti-vacuity: this test is a loop of `continue`s, so it would pass
    # just as happily if the interesting case stopped existing. Count it.
    checked = 0
    for label, controller in _exact_cover_controllers():
        if not controller.load_support_delivers_exact_cover:
            continue
        if controller.discharge_rate_is_load_following:
            continue  # ceiling: rounded up, delivers the cover exactly
        checked += 1
        assert label == "solax_modbus_growatt/vpp", (
            f"{label} declares load_support_delivers_exact_cover=True while "
            f"its discharge rate is a forced power. The DP will plan a "
            f"partial load cover this platform cannot deliver unless it "
            f"discards the LOAD_SUPPORT rate entirely -- prove that here."
        )
        # The reason it is safe: the rate is thrown away, not rounded.
        vpp_power, remote_control = controller._intent_to_vpp(
            strategic_intent="LOAD_SUPPORT",
            discharge_rate=57,  # any value; it must not reach the inverter
            grid_charge=False,
            block_passive_charging=False,
        )
        assert (vpp_power, remote_control) == (0, False), (
            "VPP LOAD_SUPPORT must release the period to native load-following "
            "(#413). If it starts writing a rate, the exact-cover candidate "
            "has to be withdrawn from this platform."
        )

    assert checked == 1, (
        f"expected exactly one cover-with-target-rate configuration to check, "
        f"found {checked}. If it is 0 the divergence this test guards has "
        f"been designed out -- delete the test rather than leaving it green "
        f"and empty."
    )

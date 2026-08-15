# Platform / provider maturity

Tracks which inverter platforms and price providers are real-world validated
versus experimental. The `experimental` marker (README/USER_GUIDE tag + this
file) is the stability flag for this codebase — see `feature-lifecycle` skill.

## Experimental / not yet real-world validated

- **Growatt VPP control mode** (`inverter.control_mode="vpp"`, on top of the
  `solax_modbus_growatt_min` (GEN4) and `solax_modbus_growatt_sph` (GEN3)
  platforms) — shipped per issue
  [#118](https://github.com/johanzander/bess-manager/issues/118). Confirmed
  writing real VPP commands to hardware by multiple testers (`nholmgaard`,
  `ridax67`, `jdungen`), and several real bugs found in the field have been
  fixed: LOAD_SUPPORT forcing a fixed rate instead of releasing control
  ([#413](https://github.com/johanzander/bess-manager/issues/413)), a
  spurious `power=0%` write on every schedule reload
  ([#421](https://github.com/johanzander/bess-manager/issues/421)/[#423](https://github.com/johanzander/bess-manager/pull/423)),
  IDLE periods draining the battery overnight
  ([#466](https://github.com/johanzander/bess-manager/issues/466)), and VPP
  Remote Control continuing to override the inverter after switching away
  from VPP mode
  ([#479](https://github.com/johanzander/bess-manager/issues/479)). A
  real-world regression scenario built from `ridax67`'s live config is
  locked in as `ci-wizard-growatt-vpp-ridax-118` (backend discovery test +
  Playwright wizard E2E). Still marked experimental: the most recent fix
  (#479) has only shipped in the beta channel (`v10.1.0b4`) so far, not yet
  in a stable/prod release, and no tester has given a clean "this now works
  end-to-end" confirmation since it landed. Move to the validated list below
  once both happen (`feature-lifecycle` Stage 5/6).
- `solax_modbus_growatt_sph` (GEN3) — monitoring-only, schedule control not implemented.
- `solax_modbus_native` (SolaX VPP).

## Real-world validated

(Populate as platforms/providers graduate through `feature-lifecycle` Stage 6.
Candidates not yet formally tracked here: Growatt cloud MIN/SPH, GEN4 Growatt
TOU via solax_modbus — all in production use prior to this file's creation.)

- `solis_modbus` (Solis hybrid via Pho3niX90/solis_modbus, added for issue
  [#130](https://github.com/johanzander/bess-manager/issues/130)) — confirmed
  working against real Solis installations by two beta testers
  (`tatusbar` on an S6-EH3P10K-NV-YD-L, `andys1802` on an S6-EH3P15K):
  entities auto-detected, schedule control running successfully. A debug
  log from the field surfaced one real bug (grid export power never
  auto-configured,
  [#475](https://github.com/johanzander/bess-manager/issues/475)), fixed and
  locked into the `ci-wizard-solis` regression scenario (backend discovery
  test + Playwright wizard E2E).
- **ENTSO-e / Belpex price provider** (`entsoe_source.py`, added for issue
  [#126](https://github.com/johanzander/bess-manager/issues/126)) — confirmed
  working against a real Belgian Belpex/Luminus Dynamic contract by
  `Frank-Leysen` over an extended live-test period spanning many beta
  builds. Several real bugs surfaced and were fixed along the way: wizard
  defaulting to SEK instead of EUR, `ems_discharging_rate` writes
  overriding Load First mode, and the terminal-value arbitrage cap using
  an unrelated slot's price as its ceiling
  ([#422](https://github.com/johanzander/bess-manager/issues/422)/[#425](https://github.com/johanzander/bess-manager/pull/425)).
  Frank's real (anonymized) config is locked into the regression suite as
  `ci-wizard-entsoe-frank-126` (backend discovery test + Playwright wizard
  E2E). Unrelated live-test findings from the same thread were split out
  into their own issues (#337, #269, #352, #330, #345, #362, #363, #428,
  #429) rather than tracked here.

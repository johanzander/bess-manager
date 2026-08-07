# Platform / provider maturity

Tracks which inverter platforms and price providers are real-world validated
versus experimental. The `experimental` marker (README/USER_GUIDE tag + this
file) is the stability flag for this codebase — see `feature-lifecycle` skill.

## Experimental / not yet real-world validated

- **Growatt VPP control mode** (`inverter.control_mode="vpp"`, on top of the
  `solax_modbus_growatt_min` (GEN4) and `solax_modbus_growatt_sph` (GEN3)
  platforms) — shipped per issue
  [#118](https://github.com/johanzander/bess-manager/issues/118). Not yet
  confirmed against real hardware; GEN4's existing `"tou"` control mode is
  unaffected and remains the default there. Move to the validated list below
  once a beta tester confirms (`feature-lifecycle` Stage 5), naming their
  scenario.
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

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
- `solis_modbus` (Solis hybrid via Pho3niX90/solis_modbus, added for issue
  #130) — implementation is source-verified against the real integration
  (release v4.1.6) but has not been confirmed against a real Solis
  installation. Do not describe it as validated in user-facing docs or
  release notes until a beta tester confirms via a debug log.

## Real-world validated

(Populate as platforms/providers graduate through `feature-lifecycle` Stage 6.
Candidates not yet formally tracked here: Growatt cloud MIN/SPH, GEN4 Growatt
TOU via solax_modbus — all in production use prior to this file's creation.)

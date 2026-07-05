# Inverter platform maturity levels

Only Growatt cloud (`growatt_server_min`, `growatt_server_sph`) and Growatt
GEN4 via solax_modbus (`solax_modbus_growatt_min`) are real-world tested.

Experimental / not yet real-world validated:

- `solax_modbus_growatt_sph` (GEN3) — monitoring-only, schedule control not implemented.
- `solax_modbus_native` (SolaX VPP).
- `solis_modbus` (Solis hybrid via Pho3niX90/solis_modbus, added for issue
  #130) — implementation is source-verified against the real integration
  (release v4.1.6) but has not been confirmed against a real Solis
  installation. Do not describe it as validated in user-facing docs or
  release notes until a beta tester confirms via a debug log.

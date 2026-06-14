# Demo Mode

Read-only operation mode that lets users see how BESS Manager would optimize their battery without actually controlling the inverter. Users can evaluate the system's value before committing to live control.

## Approach

Thin UI layer over the existing `test_mode` mechanism in `ha_api_controller.py`. The `test_mode` flag already blocks all inverter writes (HTTP POST to switch/turn_on, switch/turn_off, number/set_value) and service calls (except safe read operations like `growatt_server.read_*` and `nordpool.get_prices_for_date`). Demo mode persists this as a user-facing setting and adds UI for toggling, visibility, and onboarding.

## Wizard Integration

The current Step 5 ("Done") is reworked into a control mode selection step. The config summary stays at the top. Below it, two radio-style cards:

- **Demo Mode** — "Watch how the system would optimize your battery. No commands sent to inverter."
- **Live Control** — "Start optimizing immediately. Sends charge/discharge commands to your inverter."

Neither option is pre-selected. The "Complete Setup" button is disabled until the user makes a choice. A note reads "You can change this anytime in Settings."

The `handleComplete()` call to `/api/setup/complete` includes the selected mode. The backend sets `demo_mode` in `SettingsStore` and calls `ha_api_controller.set_test_mode()` accordingly.

## Persistent Banner

A `DemoModeBanner` component renders in the app layout (`App.tsx`) above page content, appearing on all pages (Dashboard, Savings, Inverter, Insights, Settings) when demo mode is active.

Content: eye icon + "Demo Mode — Optimization is running but not controlling your inverter" on the left. A "Go Live" button on the right that triggers the pre-flight health check dialog.

Styling: blue-toned background (`#1e3a5f`), thin bar, visually distinct from error/warning banners. Disappears immediately when demo mode is turned off.

## Settings Page

A new **System** tab is added to the Settings page after the existing AI Analyst tab. It contains a toggle switch for Demo Mode with description text: "Read-only — optimizer runs but does not control the inverter."

When demo mode is active, an inline status message appears below the toggle: "Currently in demo mode. Savings shown are theoretical estimates."

## Mode Switching

### Demo → Live (enabling live control)

Triggered by: the Settings toggle, the "Go Live" banner button, or the wizard choosing Live Control.

A pre-flight dialog runs the health check automatically and displays structured pass/fail results:
- Inverter reachable
- Battery sensors responding
- Price data available
- Solar sensors configured

If all checks pass, the "Enable Live Control" button is enabled. The status message confirms: "The system will start controlling your inverter on the next optimization cycle." If any check fails, the button is disabled and the failure is explained.

### Live → Demo (disabling live control)

A confirmation dialog: "Switch to demo mode? The inverter will be set to a safe idle state."

On confirmation, the system sets the inverter to a safe idle state (grid_charge=False, discharge_rate=0 — solar-only mode) via the existing `inverter_controller.apply_period()` with an IDLE intent, then activates `test_mode`.

### Availability

The toggle is always available in Settings, not just during initial setup. Useful for testing configuration changes, during hardware swaps, or returning to observation after running live.

## Savings in Demo Mode

Savings use the existing `PredictionSnapshot` path — theoretical values computed from the optimization plan, not from actual sensor deltas. The optimizer still runs every 15 minutes, reads real sensor data (SOC, prices, solar), and computes optimal schedules. The schedule is logged and stored but not sent to the inverter.

The savings API response includes `"data_source": "theoretical"` so the frontend can label savings accordingly. On the Dashboard, the savings card shows a small "theoretical" label beneath the number. On the Savings page, a subtitle reads "All savings are theoretical estimates based on optimization plans."

The system shows what it *would* have saved, not what actually happened. This is intentional — the purpose of demo mode is to demonstrate value, and theoretical numbers represent the system's capability.

## Backend Changes

### Settings persistence

New `demo_mode: bool` field in `SettingsStore`, persisted in config.yaml. Defaults to `false` for existing installations (no disruption to current users).

On startup, `ha_api_controller.set_test_mode()` is called based on the persisted `demo_mode` setting.

### API endpoints

- `GET /api/settings/demo-mode` — returns `{ "enabled": bool }`
- `POST /api/settings/demo-mode` — body `{ "enabled": bool }`. When disabling demo mode (going live), runs health check first and returns results. When enabling demo mode, sets inverter to safe idle state before activating.

### Health check integration

The existing `health_check.py` already reports `"system_mode": "demo"` when `test_mode` is active. The pre-flight check reuses the same health check logic but returns structured pass/fail results for the frontend dialog.

### Optimization engine

No changes. The scheduler continues to run every 15 minutes. It reads real SOC each cycle and re-plans accordingly, so schedules stay realistic. The write-blocking happens at the `ha_api_controller` layer, below the optimizer.

## Edge Cases

**SOC drift** — since the inverter doesn't follow the plan, actual SOC diverges from optimizer assumptions. The optimizer re-reads real SOC each cycle, so plans adjust to reality. Savings remain theoretical (plan-based).

**Add-on restart** — `demo_mode` is persisted in settings. The system restarts in the same mode.

**Existing users upgrading** — `demo_mode` defaults to `false`. No behavior change. The wizard modification only affects new setups.

**System-wide** — demo mode is per-system, not per-user. Correct since there is one physical inverter.

**Long-running demo** — theoretical savings accumulate over days/weeks with consistent labeling. Users build confidence in the system's value over time.

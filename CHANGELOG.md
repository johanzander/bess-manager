# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Solis inverter platform** (`solis_modbus`) — Solis hybrid inverters can now be configured via the community [Pho3niX90/solis_modbus](https://github.com/Pho3niX90/solis_modbus) integration (local Modbus, Grid Time of Use v2 schedule — 6 charge + 6 discharge periods). `solax_modbus` (already supported for other brands) was the initial target since no new transport would be needed, but real-world testing on the reporter's hardware confirmed Solis is not reachable through it — this integration is the confirmed-working path instead. Based on SA7BNT's research and initial implementation in bess-manager-beta PR #51, re-verified against the actual integration source and re-implemented to share scheduling logic with Growatt SPH through proper inheritance instead of cross-class private-method calls. **Experimental** — not yet validated end-to-end against a real Solis installation beyond the reporter's Modbus entity check. (#130)

- **Daily savings history with week/month/year aggregates** — A new `DailyViewStore` persists a per-day savings snapshot at day rollover. `GET /api/savings/aggregate` and a new Savings page section expose week/month/year rollups built from that history, plus disk-usage and clear-history controls. ([#260](https://github.com/johanzander/bess-manager/pull/260))

### Changed

- **Net Grid Cost replaces the wear-bundled headline; battery wear moved to its own Insights table; Savings page redesigned with Day/Month/Year drill-down** — The dashboard, Savings, and Insights pages now show **Net Grid Cost** (import − export, matching the physical meter) as the headline cost figure instead of a bundled figure that silently included modeled battery wear. **Net Savings** (wear-free, `Grid-Only Cost − Net Grid Cost`) is a new additive figure alongside it; the underlying savings/percentage-saved formula is unchanged. Battery wear no longer appears in any cost/savings headline — it now lives in a new **Battery Actions** table, moved from the Savings page to Insights, as a per-period breakdown of optimizer decisions. The Savings page's old rolling Week/Month/Year toggle is replaced by a **Day/Month/Year resolution selector with a date picker**, plus a Tibber-style History drill-down (year → month → day → hour), and the Scenario Comparison tab moved to Insights. ([#249](https://github.com/johanzander/bess-manager/issues/249), [#268](https://github.com/johanzander/bess-manager/pull/268))

- **DP optimizer now uses pure backward induction instead of ad hoc profitability floors** — Removed the `cost_basis` discharge-profitability floor, the anti-cycling special case, and the whole-day `min_action_profit_threshold` rejection gate. `IDLE` is always a feasible action, so the value function's own `max` already makes the hold-vs-discharge call correctly per Bellman's principle of optimality; a separate veto on top was redundant at best. Replaced with a trivial idle-vs-DP-cost numerical safety net that only guards against SoE-grid discretization residual. Changes nearly every scenario's expected schedule — equal-or-better economics on all 26 pinned fixtures. `min_action_profit_threshold` remains in settings/schema but is now unused (backward-compatible for existing installs). Originally shipped to beta as [#59](https://github.com/johanzander/bess-manager-beta/pull/59); forward-ported to main via [#253](https://github.com/johanzander/bess-manager/pull/253) ([#242](https://github.com/johanzander/bess-manager/pull/242) was an earlier, unmerged attempt at the same port).

### Fixed

- **Debug export's `input_data.initial_soe` showed the day-start (midnight) SOE instead of the SOE the DP actually started from, after the first optimization run of the day** — `battery_system_manager.py`'s schedule-creation step always preferred `_initial_soc_pct` (set once at midnight) over the current run's real starting state, silently overwriting `initial_soe` on every re-optimization for the rest of the day and misleading debug-bundle root-cause analysis. `initial_soe` is now always populated from the current run's actual starting SOE (`period_data[0].energy.battery_soe_start`); a new, separately-named `day_start_soe` key carries the midnight value for future consumers that need it. ([#292](https://github.com/johanzander/bess-manager/issues/292))
- **Savings/Insights table's current-hour battery SOC could jump straight to the configured Min SOC floor instead of the live sensor reading** — `_state_transition`'s final safety clamp unconditionally raised `next_soe` to `min_soe_kwh` even when the period started below the floor with zero real charging (e.g. a live sensor reading under Min SOC in demo mode, or with any external controller BESS isn't writing to). The clamp now only raises to the floor when the period started at/above it; below-floor periods keep the real, unfabricated SOE until genuine charging recovers it. A related stale bounds check in `_best_action_at_continuous_state` — which would have silently rejected every candidate action (including plain IDLE) once this fix made a below-floor `next_soe` possible, fabricating a zero-cost period — is fixed the same way. Applied to both `_state_transition` and its vectorized DP-search twin `_state_transition_grid` for parity. ([#233](https://github.com/johanzander/bess-manager/issues/233))
- **Savings page's "Hours in Today" table showed `undefined:00` in the Period column on every row for hourly-resolution systems** — `formatHourLabel` read a `hour` field from `DashboardHourlyData` that the backend never sends (only `period`); the bug was masked in the default quarter-hourly resolution, which already read `period` correctly. Also fixed the same stale-field read in `SystemStatusCard`'s hourly-mode lookup, which silently failed to find the current period's data, and removed the unused `hour` field from the frontend type. ([#126](https://github.com/johanzander/bess-manager/issues/126))
- **Date picker (Savings Report and Insights → Battery Action) always rendered light, ignoring dark mode** — `DateSelector` had no `dark:` Tailwind classes, and the embedded `react-datepicker` calendar has no dark styling out of the box. Added dark-mode classes to the selector and dark-mode CSS overrides for the calendar popup.
- **DP terminal holding pattern retained more charge than necessary above the reserve floor going into a price peak** — Shrunk `SOE_STEP_KWH` from 0.1 to 0.05 kWh (`POWER_STEP_KW` unchanged at 0.2) to reduce continuous-path-reconstruction interpolation error against the DP's own exact backward-induction value function. Reduces (does not eliminate) the defect: on the reported reproduction scenario, the DP now holds 3.90 kWh above the floor at the peak instead of 5.32 kWh (~27% reduction) before handing the remainder to the next peak; full elimination needs a follow-up continuous-action reformulation. Also extracted `core/bess/dp_constants.py` as a single source of truth for the DP's grid resolution, fixing a latent bug where `decision_intelligence.py` hardcoded a noise-floor threshold that assumed `POWER_STEP_KW` would never change. ([#275](https://github.com/johanzander/bess-manager/issues/275), [#279](https://github.com/johanzander/bess-manager/pull/279))
- **DP's continuous-state action search missed the true piecewise-linear optimum between fixed power grid points** — `_best_action_at_continuous_state` searched a fixed 0.2 kW power grid to pick each period's discharge/charge action, which could miss the true optimum since the reward+continuation-value objective is exactly piecewise-linear. Discharge search is now exact enumeration of the real hardware action space (integer percent of `max_discharge_power_kw`), which also fixes a related misclassification where the smallest 1% step could fall at or below `decision_intelligence.py`'s `POWER_CLASSIFICATION_THRESHOLD_KW` for batteries ≤10kW. Charging no longer searches a grid at all, since the STORE branch is binary. Confirmed plan-vs-realized cost equality (R == P) exactly on all 26 pinned fixtures; 20 fixtures' pinned costs shifted (11 improved, 9 regressed, all ≤0.38 SEK) as the DP's forward reconstruction now sometimes takes a different, still-optimal action against the same interpolated value function. Does not resolve [#275](https://github.com/johanzander/bess-manager/issues/275) — the residual gap is in the backward-pass value function itself, tracked in [#276](https://github.com/johanzander/bess-manager/issues/276). ([#282](https://github.com/johanzander/bess-manager/issues/282), [#284](https://github.com/johanzander/bess-manager/pull/284))
- **Setup wizard discovered the off-grid EMS/SOC-limit sensor instead of the on-grid one for SolaX-modbus Growatt, growatt_server cloud, and native SolaX installs** — `SOLAX_GROWATT_MIN_SUFFIX_MAP`, `GROWATT_MIN_SUFFIX_MAP`, and `SOLAX_NATIVE_SUFFIX_MAP` only mapped the off-grid discharge-stop-SOC/minimum-capacity suffix, which has no effect since BESS always operates grid-tied. Now only the on-grid suffix is matched (the off-grid entity is left unmapped, not silently bound); also fixes a pre-existing typo in the native-SolaX suffix (`grid_tied` → `gridtied`) that meant its on-grid entity never matched at all. ([#270](https://github.com/johanzander/bess-manager/issues/270), [#277](https://github.com/johanzander/bess-manager/pull/277))
- **Inverter tab "Charge Power Rate" showed a stale 40% config default instead of the live sensor value** — `/api/inverter/status` called `controller.get_discharging_power_rate()` for the discharge-rate field but never the equivalent `get_charging_power_rate()`, so the response had no live charge-rate field at all; the frontend fell back to the static `batterySettings.chargingPowerRate` config default (40%) instead. Wired the live read into the response and switched the UI to consume it. ([#271](https://github.com/johanzander/bess-manager/issues/271))
- **DP terminal-value fallback could exceed the real achievable export price on wide buy/sell-spread markets** — The rolling-horizon terminal-value estimate priced leftover battery charge using only the median buy price, so on markets with a wide spread (e.g. Belgian ENTSO-e/Belpex) it could exceed the best price actually achievable by exporting now, causing the optimizer to hold charge to chase a fictitious future bonus. Capped at `min(buy-based estimate, best in-horizon sell price)`, self-calibrating without a market-specific threshold. ([#251](https://github.com/johanzander/bess-manager/pull/251))
- **Battery SOC chart tooltip only showed buy price, with no explanation for export-driven decisions on divergent buy/sell contracts** — Adds a "Show sell price" toggle on the Energy Flow chart's price line, and always shows the sell price in the tooltip when the data exists. ([#238](https://github.com/johanzander/bess-manager/pull/238))
- **Small export overshoot beyond `home_consumption` was miscredited as export revenue** — Load-first hardware self-throttles and never actually delivers that excess, so it's no longer counted as savings. Fixes issue [#240](https://github.com/johanzander/bess-manager/issues/240) via [#253](https://github.com/johanzander/bess-manager/pull/253).
- **`BATTERY_EXPORT` classification threshold was 10x coarser than related flow checks** — `classify_strategic_intent`/`infer_intent_from_flows` used a `0.1` kWh threshold instead of `0.01`, misclassifying small export-only discharges as `LOAD_SUPPORT` (a mode that physically cannot export), causing planned-vs-realized cost gaps up to 18.7 SEK on quarter-hourly fixtures. Reconciled to `0.01` everywhere, including the reward function's matching export-credit threshold. ([#253](https://github.com/johanzander/bess-manager/pull/253))
- **`GRID_CHARGING` charge rate display was stuck at a static 100% in logs and the schedule API** — `get_detailed_period_groups()` (used by the debug log's schedule table and by the API/frontend) read a static `charge_rate=100` for GRID_CHARGING periods instead of the action-derived rate `get_period_settings()` already computed since [#191](https://github.com/johanzander/bess-manager/pull/191), so small top-up charges (e.g. ~1% of max power) were misreported as full-rate 100% in the ASCII debug table. Both call sites now share one `_compute_charge_rate()` helper.
- **Redundant "Intent transition" log spam on every hourly re-optimization** — `create_schedule()` in both the Growatt MIN and Solax Modbus Growatt controllers re-logged every already-elapsed intent transition for the whole day on each hourly re-plan, dominating debug bundles (~88% of INFO-level log lines). Transition logging now starts from the current period instead of period 0. Also removed a per-run log dump of the static `INTENT_TO_MODE` class constant.

### Added

- **ENTSO-e / Belpex price provider** — New `entsoe` energy provider reads day-ahead spot prices from the [ENTSO-e Transparency Platform](https://github.com/JaccoR/hass-entso-e) HA integration via the average-price sensor's `prices_today` / `prices_tomorrow` attributes. Supports both hourly (PT60M) and quarterly (PT15M) data, auto-detected by the setup wizard. Prices are treated as VAT-exclusive spot prices. Experimental — not yet real-world validated. ([#208](https://github.com/johanzander/bess-manager/pull/208))

### Fixed

- **Transient, self-recovering HA API timeouts were logged as ERROR, surfacing false alarms in the UI/debug bundle** — `run_request()`'s exception handler logged unconditionally at `ERROR` on every failed HTTP attempt, before its caller (`_api_request`, which already retries with backoff) could determine whether the attempt would actually be retried. Every retryable timeout (attempts 1-3 of 4) produced a duplicate, premature `ERROR` line even when the retry succeeded seconds later — as seen in a user's debug bundle where a `button/press` timeout logged `ERROR` at 18:54:48 and 18:55:20 despite the schedule applying successfully at 18:55:51. Demoted the `run_request()` log call to `DEBUG`; `_api_request()` remains the single source of truth, logging `WARNING` for retryable attempts and `ERROR` only once retries are exhausted.
- **Anti-cycling discharge gate no longer over-values stored energy during solar surplus** — When solar already covers all home load for a period, `_compute_reward`'s discharge profitability check no longer credits the discharge with `avoid_purchase_value` (there is no grid purchase to displace when solar covers the load). This closed a leak that let marginal, unprofitable ~0.1 kWh `BATTERY_EXPORT` discharges slip past the `-inf` anti-cycling floor in solar-surplus periods with a full battery. ([#209](https://github.com/johanzander/bess-manager/pull/209))
- **`GRID_CHARGING` throttled to ~1% of the planned rate** — The DP's ascending-order tie-break always kept the smallest positive tested power level (0.2 kW) as the reported action for the STORE branch, so `decision.battery_action` reported that instead of the throughput actually achieved. That leaked value drove the inverter's charge-rate formula, silently throttling grid charging to ~1% of the intended rate since [#191](https://github.com/johanzander/bess-manager/pull/191). Fixed by computing `battery_action_kwh` from the achieved throughput for the STORE branch. ([#207](https://github.com/johanzander/bess-manager/pull/207))
- **`LOAD_SUPPORT` discharge rate not reaching the inverter on Solax Modbus** — The Solax Modbus / local-Modbus Growatt controller withheld the hardware discharge-rate write for every intent mapped to `load_first` mode (`IDLE`, `SOLAR_STORAGE`, `SOLAR_EXPORT`, `LOAD_SUPPORT`), but only `LOAD_SUPPORT` computes a real non-zero rate — the others correctly resolve to 0. The write is now withheld only when the rate is genuinely zero, not for every `load_first`-mapped intent. ([#211](https://github.com/johanzander/bess-manager/pull/211))
- **Stale health-check banner and InfluxDB placeholder-config log spam** — The dashboard health banner only refreshed at startup, after a settings save, or after the setup wizard, so a sensor blip at exactly one of those moments left it stuck showing an error indefinitely. Added a 5-minute background recheck and a manual "Recheck now" button. Also fixed periodic sensor collection attempting real HTTP connections to the default placeholder InfluxDB URL for users who never configured it, by reusing the same `is_influxdb_configured()` check the startup path already used. ([#217](https://github.com/johanzander/bess-manager/pull/217))
- **SOC limits rewritten to inverter flash on every restart even when unchanged** — Growatt MIN and SolaX Modbus controllers wrote charge/discharge stop SOC unconditionally on every program start, wearing the inverter's flash memory unnecessarily since the config rarely changes between restarts. Both now read the current value first and only write on a mismatch, matching `GrowattSphController.sync_soc_limits()`'s existing pattern. ([#258](https://github.com/johanzander/bess-manager/pull/258))
- **Savings page export badge used a different threshold than the backend's own intent classification** — The Savings page gated its battery-to-grid export badge on a hardcoded 0.05 kWh threshold, diverging from the backend's 0.01 kWh `BATTERY_EXPORT` classification, so a period could clear the backend threshold (and drive Growatt TOU mode) without the frontend agreeing. The badge now derives from the backend's own strategicIntent/observedIntent, and the duplicated precedence logic across three components is consolidated into one shared `getIntent()` helper. Also fixed the debug bundle's Time column showing each period's storage timestamp (end-of-period) instead of its start time. ([#259](https://github.com/johanzander/bess-manager/pull/259))
- **SolaX Modbus withheld the EMS discharge-rate=0 write in `load_first` mode** — Removed an unverified gate (from #166) that skipped resetting the discharge-rate register to 0 for SOLAR_STORAGE/IDLE, leaving a stale nonzero value on the inverter. Writes unconditionally now, matching the cloud-based Growatt MIN controller — flagged for hardware verification on a real GEN4 inverter before deciding whether to keep this or restore the gate. ([#261](https://github.com/johanzander/bess-manager/pull/261))

### Internal

- **Vectorized the DP backward-induction hot loop with numpy (~115x faster)** — `_run_dynamic_programming`'s per-period state x action search (~240 SOE levels x ~150 power levels) was a doubly-nested pure-Python loop; new `_state_transition_grid`/`_compute_reward_grid` helpers replicate `_state_transition`/`_compute_reward` operation-for-operation on broadcast `(S,1) x (1,A)` arrays instead, producing bit-identical results per cell. A 96-period optimization dropped from ~12.5s to ~0.1s. Unblocks the discretization-tuning fix candidate for [#275](https://github.com/johanzander/bess-manager/issues/275). No user-facing effect. ([#236](https://github.com/johanzander/bess-manager/issues/236), [#278](https://github.com/johanzander/bess-manager/pull/278))
- **Release pipeline and issue-triage workflow fixes** — Beta's `release-addon.yml` now derives the image repo from `github.repository` instead of a hardcoded prod name, fixing denied GHCR pushes on beta releases ([#256](https://github.com/johanzander/bess-manager/pull/256)); the issue-triage bot now runs for non-collaborator reporters so external bug reports get auto-labeled ([#257](https://github.com/johanzander/bess-manager/pull/257)). No user-facing effect.

## [9.8.1] - 2026-06-28

### Changed

- **Debug export now leads with a "Key Findings" section** — the debug bundle opens with an auto-generated digest that surfaces cross-run schedule disagreements (a slot scheduled differently across re-optimization runs) and a deduplicated rollup of today's log anomalies (network/connectivity, data gaps, restarts, runtime errors), grouped by category and source. Raw logs and the full schedule JSON are moved to the bottom, and the health check is captioned as a point-in-time snapshot so its "OK" is not mistaken for "nothing went wrong today." The in-app AI chat uses the same digest instead of the raw log dump. This makes root-causing optimizer decisions and runtime failures much faster. (#198)

## [9.8.0] - 2026-06-27

### Added

- **Redesigned inverter schedule table** — The schedule table in the Inverter Status Dashboard is rebuilt as a single unified table with consistent column widths across today and tomorrow. Intent is now split into separate **Solar** (amber) and **Grid/Discharge** (green/orange) power columns so it's immediately clear which source is charging or discharging. A **Target SOC** column replaces the old SOC field and shows the end-of-period state of charge as a percentage. Pre-optimization (past) rows are greyed out to indicate they are no longer accurate. Inverter Configuration columns (Mode, Charge%, Discharge%, Grid Charge) are hidden for SolaX VPP (`solax_modbus_native`), which does not use TOU-based control. (#194)

## [9.7.1] - 2026-06-27

### Added

- **Energy Flow expandable rows in Savings Overview** — Each row in the Savings Overview table now expands to show a detail panel with per-interval solar, battery, and grid flows. Grid Import and Grid Export cells also display compact sub-flow badges (gridToHome, gridToBattery, solarToGrid, batteryToGrid) to the right of the main value. (#188)
- **Action-derived charge rate for GRID_CHARGING periods** — The inverter now receives a proportional charge rate command instead of always 100%. For small top-up periods (e.g. filling the last 0.17 kWh at 99.4% SOC) the rate is scaled from the DP algorithm's planned action, matching what was actually optimised. All other intents (SOLAR_STORAGE, IDLE, SOLAR_EXPORT) continue to charge at 100% to accept solar at full rate. (#191)

## [9.7.0] - 2026-06-27

### Fixed

- **Battery locked in `grid_first` during solar-surplus idle periods** — When the optimizer planned no battery action (`power=0`) during periods with active solar export, the classifier returned `BATTERY_EXPORT` (formerly `EXPORT_ARBITRAGE`), which maps to `grid_first`. This blocked the battery from supporting house load during long daytime windows even when solar was insufficient. A new `SOLAR_EXPORT` intent is introduced for power≈0 + solar-to-grid periods; it maps to `load_first` so the battery can serve load while solar exports to the grid. (#187)
- **Grid charging blocked during solar surplus even at cheaper prices** — The optimizer had a surplus gate that prevented any grid-to-battery charging whenever solar production exceeded home consumption. This caused the optimizer to skip cheap daytime hours in favour of more expensive hours when solar was active. The gate is removed: solar fills the battery first and grid tops up remaining capacity when prices make it worthwhile. On high-solar days this can increase arbitrage savings significantly (up to +12.5 SEK on scenario baselines). (#189)
- **Schedule Overview discharge rate always showed 100%** — `get_detailed_period_groups()` read `discharge_rate` from the static `INTENT_TO_CONTROL` table (hardcoded 100 for `EXPORT_ARBITRAGE`/`LOAD_SUPPORT`). It now computes the rate from the actual per-period battery action in the schedule, so partial-discharge slots correctly reflect the planned power rather than always showing 100%. (#186)
- **Battery Settings card showed bare "0 %" when EV charger was inhibiting discharge** — When the EV charger suppresses discharge to 0%, the Discharge Power Rate row now dims and shows an amber "Inhibited" badge instead of a bare percentage. (#186)

### Changed

- **`EXPORT_ARBITRAGE` intent renamed to `BATTERY_EXPORT`** — All references updated across backend, frontend, tests, and documentation. The semantic meaning is unchanged: battery actively discharging to the grid during peak-price windows. (#187)

## [9.6.3] - 2026-06-25

### Fixed

- **Dashboard hourly view returned 500** — `_aggregate_quarterly_to_hourly` was never updated when `observedIntent` was added to `APIDashboardHourlyData` in 9.6.2, so every call to `GET /api/dashboard?resolution=hourly` crashed with a missing required argument.
- **Inverter platform badge always showed "SolaX Modbus"** — `InverterStatusDashboard.tsx` compared `platform` against legacy short strings (`growatt_min`, `growatt_sph`, `solax`) that never matched the actual API values (`growatt_server_min`, `growatt_server_sph`, etc.), so every user fell through to the else branch and saw "SolaX Modbus". String matching is updated to the current API values. (#60)
- **Growatt SPH TOU intervals rendered "Segment #undefined"** — `GrowattSphController.build_schedule` built `tou_intervals` without `segment_id` or `is_default` fields. The frontend template assumed both were always present, causing `isDefault` to render as falsy and the segment label to show as undefined. Both fields are now included. (#60)
- **AI Analyst returned 404 errors on deprecated model IDs** — The AI Analyst feature used `claude-sonnet-4-20250514` and `claude-opus-4-20250514`, the Claude 4.0 launch IDs from May 2025. Anthropic deprecated these IDs (retirement date June 15 2026), causing 404 errors for all users. Updated to `claude-sonnet-4-6` and `claude-opus-4-8`. (#180)
- **EnergyFlowCards and SystemStatusCard stayed frozen between refreshes** — Both components called `useDashboardData()` without a refresh interval, so they fetched only on mount. The main dashboard page polls every 60 s but the cards remained stale. Both now pass a 60 s interval, staying in sync with the dashboard cadence. (#179)
- **Energy Prediction health check validates active consumption strategy** — The health check was hardcoded to validate `get_estimated_consumption` (the `sensor` strategy sensor) regardless of which strategy was configured, producing false-positive warnings for users running `fixed`, `influxdb_7d_avg`, or `ha_statistics`. The check now only validates `get_estimated_consumption` when `sensor` is the active strategy; solar forecast validation is unchanged. (#160)
- **Nord Pool HACS continental areas mapped to Norway** — The entity-id regex in `_parse_nordpool_area_from_entity_id` only matched original Nord Pool members (SE/NO/DK/FI/EE/LT/LV). HACS users with continental area codes (NL, BE, DE, DE-LU, FR, AT, PL) got `None` from the parser; the `raw.upper()` fallback produced a long string starting with "NO", so `_hints_from_nordpool_area` read the "NO" prefix and returned Norwegian krone instead of the correct currency. The regex is extended to cover all continental areas. (#171)
- **Nord Pool Currency field always read-only in UI** — Both Nord Pool provider variants rendered the Currency input with `readOnly: true` unconditionally, preventing users from correcting a wrong auto-detected currency. The field is now editable when area or currency detection has not produced a value. (#171)
- **Next-day schedule timestamps stamped with today's date** — The `prepare_next_day` path set `optimization_period=0` and then called `period_index_to_timestamp(0..95)`, which anchors index 0 to today. Period timestamps in the next-day schedule were therefore labeled `YYYY-MM-DD (today) HH:MM` instead of `YYYY-MM-DD (tomorrow) HH:MM`. `_add_timestamps_to_period_data` now accepts a `next_day` flag that offsets the period index by today's period count before timestamp conversion, so all periods resolve to tomorrow's date. (#155)

### Refactored

- **Unified `prepare_next_day` and extended-horizon data paths** — `_gather_optimization_data` previously had two independent branches that each fetched tomorrow's solar forecast and the consumption forecast separately. Any bug had to be fixed twice. The two branches now share a single fetch stage (`_fetch_tomorrow_solar_forecast` helper + cache-first consumption fetch) before diverging only for array-building. The 23:55 next-day publish and the rolling hourly run behave identically to before; only the duplication is removed. (#157)

## [9.6.2] - 2026-06-24

### Fixed

- **SolaxModbus (GEN4): Load First defeated by EMS discharge register** — `apply_period()` was writing `discharge_rate=0` to the EMS register for all modes including `load_first`, overriding the inverter's own Load First logic and causing grid imports during periods that should rely on the battery. The EMS discharge register is now only written for `battery_first` and `grid_first` modes. (#166)
- **SolaxModbus: optional preflight checks blocked "Enable Live Control"** — The `PreflightCheckDialog` treated `NOT_CONFIGURED` optional components (e.g. Solcast) as errors, preventing users from enabling live control when non-required integrations were absent. Optional checks are now correctly non-blocking. (#169)
- **SolaxModbus: demo→live transition left inverter in bad state** — Switching from demo mode to live control skipped hardware initialization: TOU slots 2–9 from any prior 9-segment configuration were never cleaned up and SOC limits were never written, so the single-segment SolaxModbus controller could not start cleanly. Hardware initialization (disable legacy TOU slots, sync SOC limits) is now always performed on demo→live transition. (#169)
- **Nordpool continental areas locked to SEK currency** — The discovery hint map only covered original Nord Pool members (SE/NO/DK/FI/EE/LT/LV/GB). For post-expansion areas (NL, BE, DE-LU, FR, AT, PL) no currency hint was returned, the SEK bootstrap default from `config.yaml` stayed in place, and the Settings UI locked the Currency field to SEK. Continental day-ahead areas are now mapped with their correct currency and VAT rate. (#163)
- **SOLAR_STORAGE shown overnight when battery starts below minimum SOE** — When initial SOE was below `min_soe_kwh`, `_state_transition` clamped the next SOE up to the floor during IDLE periods. `_idle_battery_flows` was interpreting that clamp delta as passive solar charging, causing every overnight IDLE period to display as SOLAR_STORAGE even at 2 am with no solar production. Fixed by returning zero flows when `soe < min_soe_kwh`. (#161)

## [9.6.1] - 2026-06-21

### Fixed

- **LOAD_SUPPORT discharged at full rate instead of the planned pace** — The DP optimizer models partial discharge for LOAD_SUPPORT (e.g. discharge 0.4 kW and let the grid cover the rest, reserving the battery for a later expensive peak), but the inverter control layer always wrote `discharge_rate=100%`, so the battery dumped at full power and drained early. LOAD_SUPPORT now scales the inverter discharge rate from the planned battery action, mirroring EXPORT_ARBITRAGE. (Issue #147)
- **Consumption strategy change silently dropped in setup wizard** — `POST /api/setup/complete` only entered the home settings block when `currency` or `consumption` were non-null; changing `consumptionStrategy`, `maxFuseCurrent`, `voltage`, or other home-only fields without also touching those two fields caused the change to be silently lost. Same flaw applied to the battery block (guarded by `totalCapacity` only) and electricity-price block. All three blocks now use an `any(f is not None …)` guard covering every field in the section.
- **Consumption strategy change takes effect immediately** — Updating `consumption_strategy` via `update_settings()` now clears the stale prediction cache so the next optimization cycle fetches predictions under the new strategy, rather than waiting until the nightly `prepare_next_day` refresh at 23:55.
- **Next-day schedule used today's solar forecast** — The `prepare_next_day` optimization built tomorrow's battery schedule from *today's* Solcast forecast instead of tomorrow's, so the plan written to the inverter could be optimized against substantially wrong solar production (e.g. 28.5 kWh today vs 64.8 kWh forecast for the next day). It now uses `get_solar_forecast_tomorrow()`, mirroring the extended-horizon path, with the same zeros fallback when tomorrow's forecast is unavailable.
- **Next-day schedule ignored the real battery SOC** — The `prepare_next_day` run (cron at 23:55, when current SOC is known and ≈ tomorrow's starting SOC) discarded the actual SOC and assumed minimum SOC. On any night the battery wasn't actually empty, tomorrow's plan started from a wrong state and under-used stored energy. It now seeds the next-day plan from the real current SOC, matching the regular optimization path.

## [9.6.0] - 2026-06-20

### Fixed

- **Solar-export savings over-crediting** — On sunny days the optimizer booked revenue for exporting surplus solar that the inverter actually stores in the battery (a `load_first` "store" period stores *all* surplus), inflating reported savings by roughly 8–16%. Surplus handling is now modelled as a binary per-period choice — store all surplus (no phantom export) or export all surplus — and export is credited per disposition, so reported savings match what the hardware can actually deliver. Verified end-to-end by a new closed-loop plan-faithfulness simulator that confirms planned and realized economics agree to the öre. This also removes the morning charge/export "dithering" some users observed.
- **Production-safety hardening** — Guard against a `ZeroDivisionError` when battery `total_capacity` is 0; replace `assert`-based validation of production data with explicit `SystemConfigurationError` (so the checks survive Python's `-O` optimization flag); and harden inverter TOU time-range parsing against malformed values.
### Changed

- **Battery surplus handling is now a binary store/export decision per period** — Schedules may differ from previous versions: instead of partial solar-to-battery splits, each period either stores all surplus solar or exports all of it. This is forecast-robust by construction — bonus solar beyond the forecast is always captured or exported, never wasted.

### Improved

- **Installation guide — consumption forecast (Step 3)** — Reworked into a comparison of all four consumption strategies with a clear recommendation to use `ha_statistics` (most accurate, no manual sensor setup), including the Home Assistant Energy-dashboard requirement and the ~7-day warm-up behaviour.

## [9.5.0] - 2026-06-15

### Added

- **Demo Mode** — New users can observe how BESS Manager would optimize their battery without actually controlling the inverter. The setup wizard now offers a "Demo Mode" vs "Live Control" choice as the final step. While in demo mode, the optimizer runs normally but all inverter writes are blocked; savings are labeled as theoretical estimates. A persistent banner shows the current mode with a "Go Live" button that triggers a pre-flight health check before enabling live control. Demo mode is also available as a toggle in the new **System** tab on the Settings page.
- **Settings page consolidation** — The Settings page now has five tabs: Integrations, Electricity Pricing, Battery, Home, and System. The old Health tab has been replaced by System, which combines demo mode toggle, AI analyst settings, and diagnostics (health checks + debug export).

### Fixed

- **Dockerfile and package script now auto-include new backend modules** — Previously each Python file had to be listed by name in both `Dockerfile` and `package-addon.sh`; new files (like `ai_chat.py`) were silently excluded from builds, causing `ModuleNotFoundError` at runtime. Both now use a `*.py` glob.
- **Removed legacy `config.dev.yaml`** — `bess_manager/config.yaml` is the single source of truth for version and add-on metadata.

### Improved

- **Installation instructions** — Expanded Step 1 in README and Installation Guide with explicit navigation steps for first-time Home Assistant users.

## [9.4.3] - 2026-06-15

### Fixed

- **Single changelog source of truth** — `bess_manager/CHANGELOG.md` is now a symlink to the repository-root `CHANGELOG.md` instead of a hand-maintained copy. The duplicate had drifted (it stopped at 9.4.0), so the Home Assistant add-on Changelog tab was showing outdated release notes; it now always reflects the canonical changelog.

## [9.4.2] - 2026-06-15

### Fixed

- **Removed duplicate "Runtime Errors" alert for unavailable InfluxDB history** — When InfluxDB historical data is missing, the dedicated "Incomplete Historical Data" dashboard banner already informs the user. v9.4.1 additionally recorded the same condition in the runtime-failure tracker, so it also appeared in the "Runtime Errors" panel — alarming, since that panel is meant for unexpected, actionable failures and the condition is benign (optimization continues normally). The redundant runtime-error alert is no longer raised; the friendly banner remains the single source of truth.

## [9.4.1] - 2026-06-14

### Fixed

- **Optimization no longer freezes when InfluxDB history is unavailable** — Historical reconstruction from InfluxDB is an optional enhancement (it backfills the actuals/savings view) and is never required to run the optimization, which uses live battery SOC plus the configured forecast. Previously a broken InfluxDB connection (e.g. after a Home Assistant update) raised a fatal error that aborted every re-optimization, silently freezing the battery on the midnight forecast for the whole day. The missing-history condition is now surfaced as a runtime failure banner and the hourly optimization continues. Note: the `influxdb_7d_avg` consumption strategy still genuinely requires InfluxDB.

## [9.4.0] - 2026-06-12

### Fixed

- **SPH platform capability gating** — UI and backend now disable features unsupported by SPH inverters (grid charge toggle, discharge power rate, fuse protection). Prevents "No entity ID configured for Grid Charge Enabled" errors. (#60)
- **SPH sensor definitions and device discovery** — Fixed sensor key mappings and discovery logic for SPH inverters. UI no longer incorrectly shows "solax" for SPH configurations. (#60)
- **Dead lifetime sensors removed** — Removed non-existent lifetime sensor keys from all platform UI definitions.

## [9.3.0] - 2026-06-12

### Changed

- **Add-on now distributed as pre-built Docker images** — HA Supervisor pulls images from GHCR instead of building from source. Faster installs, no build failures on low-powered hardware.
- **Add-on metadata moved to `bess_manager/` subdirectory** — Fixes compatibility with HA Supervisor 2026.06.x which changed how add-on repositories are scanned.

## [9.2.1] - 2026-06-10

### Fixed

- **SPH per-period apply failed every 15 minutes** — `GrowattSphController` inherited base class `_write_period_to_hardware` which tried to set `grid_charge` and `discharging_power_rate` entities that don't exist for SPH. Added no-op override since SPH deploys the full schedule atomically via service calls. (#60)
- **Octopus discovery picked gas entities for electricity import** — Discovery used keyword matching on `entity_id` instead of `unique_id` regex matching (like all other platforms). Gas rate entities matched the import pattern. Rewritten to use regex on `unique_id` requiring `octopus_energy_electricity_` prefix, which inherently excludes gas. (#60)
- **Debug export missing Octopus Energy entities** — Added `octopus_energy` to entity registry export domains so Octopus entities appear in debug logs.

## [9.2.0] - 2026-06-09

### Fixed

- **SPH inverter discovery failed** — ENTITY_SUFFIX_MAP only had MIN (tlx_*) keys, missing SPH (mix_*) keys. Split into per-platform suffix maps; discovery now picks the platform with more matches. (#111)
- **Wizard /api/setup/confirm endpoint was fragile** — Removed partial-state persistence endpoint; wizard now saves all settings atomically via /api/setup/complete. Octopus discovery rewritten to use entity registry platform field instead of string-matching entity_ids. (#112)
- **Non-Swedish locale defaults not persisted** — Bootstrap hardcoded SEK/1.25 VAT/Swedish grid costs for all users. Discovery now persists currency, VAT, and pricing defaults immediately for detected locale. (#113)

## [9.1.0] - 2026-06-08

### Added

- **AI Analyst chat panel** — Embedded AI analyst in the web UI. Ask questions about battery performance, optimization decisions, savings, and configuration from a floating chat panel on any page. Responses stream in real-time via SSE. The AI has full source code access (reads files, searches code) and uses live system data (sensors, schedules, prediction snapshots, logs) as context. Requires a Claude API key configured in Settings > AI Analyst. Prompt caching reduces follow-up message costs by ~90%.
- **Period-level retry with user-facing banners** — When HA supervisor is temporarily unresponsive, per-period hardware writes retry after 3 and 8 minutes instead of waiting 15 minutes for the next cycle. Dashboard shows clear banners like "Period 68 (17:00): Could not apply optimization to inverter, retrying in 3 min".
- **Startup progress spinner** — Dashboard shows live initialization progress instead of 502 Bad Gateway.

### Fixed

- **AI chat showed wrong savings numbers** — The AI analyst saw battery-only savings instead of the total savings shown on the dashboard. Fixed to match UI definition. Also clarified savings definitions (total vs battery-only) in domain knowledge.
- **Schedule bar showed "Charging from Grid" during solar charging** — Intent classifier now compares dominant energy source (`grid_to_battery > solar_to_battery`) instead of using a near-zero threshold that triggered on any tiny grid supplement.
- **Cryptic error messages on inverter write failures** — Hardware write operations now include descriptive operation labels instead of generic "Call number.set_value" messages.
- **502 Bad Gateway on startup** — Moved initialization to a background thread so the web server binds immediately.
- **InfluxDB warnings on startup when not configured** — Unconfigured InfluxDB state now detected early and handled gracefully.

## [9.0.0] - 2026-06-04

### Added

- **SolaX inverter support** — native SolaX inverters now supported via the homeassistant-solax-modbus HACS integration, using VPP active-power commands for battery control. Setup wizard auto-detects SolaX entities and shows platform-specific sensor configuration.
- **Growatt Local Modbus support** — Growatt MIN (GEN4) and SPH/MIX (GEN3) inverters can now be controlled locally via the solax_modbus HACS integration instead of the Growatt cloud API, providing faster response times and no cloud dependency.
- **Single-segment TOU for Growatt Modbus** — replaces the 9-slot TOU approach with a single TOU segment updated per-period, reducing required HA entities from 45 to 5. Legacy TOU slots 2-9 are auto-migrated on startup.
- **Failure tracking improvements** — recurring failures are coalesced with occurrence counts, inverter command failures are surfaced in the dashboard banner, and per-sensor failure categories auto-dismiss on recovery.
- **Scenario-driven wizard tests** — setup wizard and discovery tests load from JSON scenario files covering all supported integration combinations.

### Changed

- **Energy flow derivation unified** — `EnergyFlowCalculator` derives `load_consumption`, `system_production`, and `self_consumption` from 5 core sensors on all platforms, eliminating zero values on platforms without dedicated registers.
- **Multi-platform architecture** — inverter scheduling refactored into an `InverterController` base class with five platform-specific controllers: `growatt_server_min`, `growatt_server_sph`, `solax_modbus_growatt_min` (GEN4), `solax_modbus_growatt_sph` (GEN3), and `solax_modbus_native`. Runtime platform switching without restart.
- **Entity-registry-based discovery** — sensor auto-detection now exclusively uses the HA entity registry via WebSocket API (unique_id + platform fields, both immutable), replacing fragile states-based discovery that broke when users renamed entities.
- **Per-platform sensor storage** — sensor configuration is stored per-platform, so switching platforms in the wizard preserves previously entered sensor values.

### Fixed

- **Intent classification** — `classify_strategic_intent()` now checks `grid_to_battery > 0` directly instead of comparing grid import vs home consumption, fixing misclassification when solar partially covers home load.
- **Nordpool area detection** — uses device registry identifiers instead of brittle entity unique_id parsing; discovery-detected area is no longer overwritten by stale settings.
- **Hardware write retry** — failed schedule writes are retried on the next quarterly cycle instead of silently running with stale inverter settings.

## [8.7.0] - 2026-05-22

### Fixed

- **Octopus Energy setup wizard** — entity IDs for import/export rates (today/tomorrow) are now persisted when completing the setup wizard. Previously these were collected in the form but never saved, forcing Octopus users (Flux, Agile, etc.) to re-enter them on the Settings page. ([#60](https://github.com/johanzander/bess-manager/issues/60))
- **Analysis agent** — restructured the `@claude-bot analyze` pipeline to focus on the user's current problem instead of stale issue reports. The bot now triages the latest debug bundle before reading code, and performs a sanity check against recent comments before posting.

### Added

- Setup wizard E2E test coverage for `POST /api/setup/complete` endpoint (3 new tests).
- Agent documentation sync from beta: verification guidelines, release workflow, scope discipline, worktree conventions, 7-scenario wizard E2E matrix docs, project-level agent memory files.
- Ruff auto-lint hook for edited Python files (`.claude/settings.json`).

## [8.6.0] - 2026-05-14

### Added

- **HA Statistics consumption forecast strategy** — new `ha_statistics` option that builds a time-of-day consumption profile from the past 7 days of Home Assistant Recorder long-term statistics. Captures daily patterns (morning/evening peaks, overnight baseline) using a trimmed mean that filters out outlier spikes like EV charging. No extra integrations needed — works with the built-in HA Recorder.
- **Consumption Forecast Comparison** view on the Insights page — collapsible chart comparing all available forecast strategies (sensor, fixed, InfluxDB, HA Statistics) against actual consumption, with MAE accuracy metrics to show which strategy performs best.
- HA Recorder WebSocket API methods (`get_statistics_during_period`, `list_statistic_ids`, `find_statistic_id`) for querying long-term energy statistics.

## [8.5.1] - 2026-05-12

### Fixed

- Schedule deviation charts Y-axis now always includes zero, fixing missing zero reference on battery charge/discharge chart and duplicate tick labels on small-range charts like grid export.

## [8.5.0] - 2026-05-09

### Added

- "Report a Problem" button in the header that downloads the debug bundle and opens a pre-filled GitHub issue, with inline shortcuts on runtime failure alerts and the global alert banner. ([#94](https://github.com/johanzander/bess-manager/pull/94))
- Raw HA WebSocket discovery dump (nordpool and growatt config entries, scrubbed for secrets and identifiers) in the debug export. ([#94](https://github.com/johanzander/bess-manager/pull/94))

### Fixed

- Nordpool area discovery now extracts the area from entity registry unique_ids (e.g. `SE4-current_price`) instead of config entry data, which HA's WebSocket API does not return. Removes broken attribute-guessing fallbacks for HACS nordpool sensors. ([#91](https://github.com/johanzander/bess-manager/issues/91))

## [8.4.3] - 2026-05-07

### Fixed

- Nordpool area discovery now reads `data.areas` (list) matching the official HA integration format; previous `options.area`/`data.area` lookup never matched real config entries. ([#91](https://github.com/johanzander/bess-manager/issues/91))

## [8.4.2] - 2026-05-03

### Fixed

- Nordpool price area now correctly detected for the official HA core integration (`nordpool_official`); bootstrap default `SE4` placeholder no longer blocks discovery from setting the real area. ([#78](https://github.com/johanzander/bess-manager/issues/78), [#85](https://github.com/johanzander/bess-manager/pull/85))
- Stale TOU segments on the inverter are now detectable after optimization cycles where schedules matched; TOU interval state is carried forward when the schedule manager is replaced, preventing stale segments from becoming invisible to BESS. ([#88](https://github.com/johanzander/bess-manager/pull/88))
- `SOLAR_STORAGE` intent now correctly derives `batt_mode` from the `INTENT_TO_MODE` mapping (`load_first`) instead of the hardcoded `battery_first`. ([#88](https://github.com/johanzander/bess-manager/pull/88))

## [8.4.1] - 2026-04-29

### Fixed

- Stale TOU segments left on inverter causing uncontrolled grid export after 24h+ uptime. Past TOU intervals were not cleaned up from hardware when the schedule transitioned to no future intervals. (thanks [@ehrw](https://github.com/ehrw))

## [8.4.0] - 2026-04-29

### Added

- Redesigned Forecast Accuracy page with uniform card grid showing solar accuracy, consumption accuracy, savings comparison, and battery/grid deviations
- Forecast comparison charts (predicted vs actual) for solar, consumption, battery, grid import, and grid export
- Hourly deviation bar chart showing how each energy flow deviated from plan
- Full-day savings breakdown (snapshot vs current) in comparison API
- Grid import/export tracking in prediction analyzer
- Prediction snapshots now persist to disk and survive add-on restarts

## [8.3.1] - 2026-04-23

### Fixed

- SOLAR_STORAGE intent now uses `load_first` mode instead of `battery_first` on Growatt MIN and SPH inverters. The previous `battery_first` mode routed solar to the battery first, causing unnecessary grid imports to serve the home even when excess solar was available for both.

### Added

- Mock run time override: `./mock-run.sh <scenario> HH:MM` replays a scenario from a specific time of day.

## [8.3.0] - 2026-04-19

### Fixed

- DP optimizer no longer cycles charge/discharge during solar hours. The profitability check now accounts for the opportunity cost of stored energy: when sell > buy, discharge-for-export is blocked (round-trip losses make it unprofitable); when excess solar is available, the sell price is used as the cost basis floor (solar could have been exported instead). ([#73](https://github.com/johanzander/bess-manager/issues/73))
- IDLE periods now correctly model passive solar charging with charge rate clamping, and are classified as SOLAR_STORAGE when the battery absorbs excess solar.

## [8.2.3] - 2026-04-18

### Fixed

- Setup wizard failed to auto-detect `battery_discharge_soc_limit_on_grid` entity on Growatt models that expose separate on-grid/off-grid SOC limit entities.

## [8.2.2] - 2026-04-18

### Fixed

- MIN inverter returned 500 errors when the TOU schedule exceeded 9 slots on price-volatile days. Hardware writes now use only the active (capped) intervals with content-aware slot assignment to avoid evicting still-needed segments. (thanks [@pookey](https://github.com/pookey))

## [8.2.1] - 2026-04-17

### Fixed

- SOLAR_STORAGE and GRID_CHARGING periods now correctly write charge rate 100% to the inverter register when power monitoring is disabled. Previously, a stale 0% rate left by a preceding LOAD_SUPPORT or EXPORT_ARBITRAGE period caused the inverter to export excess solar instead of storing it.
- Nordpool service contract tests now pass when run in isolation, not just as part of the full suite. Backend test path setup no longer implicitly depends on core tests running first.
- InfluxDB health check now shows actionable error messages (e.g. "Wrong username or password" for HTTP 401) instead of raw status codes.
- Removed hardcoded fallback values and `hasattr` guards in API endpoints that masked configuration errors with fabricated data. The system now fails explicitly when misconfigured.
- Detailed schedule endpoint no longer sends `batterySocEnd` and `soc` fields that were hardcoded placeholders (50%) and never actually displayed — dashboard data always owns those values.

### Changed

- Removed redundant local imports throughout the codebase. All imports are now at module level.
- Added `_get_intent_description()` to `SphScheduleManager` for consistent interface with `GrowattScheduleManager`.

## [8.2.0] - 2026-04-17

### Changed

- Nord Pool HACS custom sensor integration now uses a single sensor entity (which exposes both `raw_today` and `raw_tomorrow` attributes) instead of two separate sensor fields. Existing settings are migrated automatically on first boot.
- Setup wizard pre-fills current Swedish default values for additional costs (0.77 SEK/kWh) and export compensation (0.20 SEK/kWh) for E.ON in SE4.
- User Guide substantially expanded: full documentation for all three price providers, all three consumption forecast strategies, and the EV charging discharge inhibit feature.
- Installation guide updated with corrected InfluxDB v2 connectivity test command.

### Fixed

- Nord Pool official integration now passes the configured area code to the `nordpool.get_prices_for_date` service call and looks up the response by that key. Previously the first list in the response was used regardless of area, which could return wrong-area prices on multi-area installations.
- Octopus Energy prices are no longer incorrectly inflated by the markup/VAT/additional-costs formula. The backend now detects that Octopus rates are already all-in and uses them as-is for buy prices.
- Switching price provider to Octopus Energy in the Settings UI now auto-resets markup rate, VAT multiplier, and additional costs to neutral values, preventing stale Nord Pool values from being saved.
- Partial settings PATCH requests now use deep merge: updating a single nested field (e.g. `config_entry_id`) no longer silently erases sibling fields in the same section.

## [8.1.1] - 2026-04-13

### Added

- Dashboard shows a dedicated "initializing" state immediately after wizard completion while the historical backfill and first schedule build run in the background (instead of a blank or error screen).
- Wizard re-run no longer clears previously configured values — existing sensor entity IDs, Nordpool config entry ID, and Growatt device ID all survive a re-scan.

### Changed

- Settings API consolidated into a single `GET /api/settings` and `PATCH /api/settings` endpoint, replacing the previous per-section endpoints. Existing installs are migrated automatically on first boot. Frontend updated throughout.
- Disabled power monitoring now reports `OK` in system health instead of `WARNING`.

### Fixed

- Growatt entity ID discovery now handles both the current SOC sensor name ("State of charge (SoC)") and the legacy name ("Statement of Charge SOC"), covering more installation variants.
- InfluxDB query skipped cleanly when no sensors are configured, avoiding a crash during first-boot before the wizard completes.

## [8.0.7] - 2026-04-12

### Fixed

- Dashboard banner not cleared after saving any settings change. Health check is now re-run after every settings mutation (battery, electricity, home, energy provider, inverter, sensors) so the banner always reflects the current state.

## [8.0.6] - 2026-04-12

### Fixed

- Dashboard banner showed stale "Electricity Price Data: Critical sensor configuration issue" after wizard completion because `_critical_sensor_failures` was only populated at startup and never cleared. Health check now re-runs at the end of wizard completion.
- Saving Home settings from the Settings page returned 422 because `currency` (stored in the Pricing form) was not included in the request payload.

## [8.0.5] - 2026-04-12

### Fixed

- `settings_store.py` missing from the root `Dockerfile` used by GitHub/HA Supervisor builds (the `backend/Dockerfile` used for local packaging was already fixed in 8.0.1).

## [8.0.4] - 2026-04-12

### Fixed

- Nordpool `config_entry_id` discovered by the setup wizard was saved to disk but not applied to the running price source, causing the health check to report "No config entry ID configured" until restart.
- Power monitoring remained disabled after the setup wizard enabled it: `HomePowerMonitor` was only created at startup, so enabling it via the wizard had no effect until restart.
- Setup wizard completion could corrupt numeric settings with `None` values for fields not included in the payload; live updates now only overwrite fields that were explicitly provided.
- `settings_store.py` added to `package-addon.sh` build context (missing from local installation packaging).

## [8.0.1] - 2026-04-12

### Fixed

- `settings_store.py` was missing from the Docker image `COPY` step, causing startup to fail with `ModuleNotFoundError`.

## [8.0.0] - 2026-04-12

### Changed

- **Settings storage moved out of `config.yaml`** — all operational settings (battery, home, electricity price, energy provider, Growatt, sensors) are now stored in `/data/bess_settings.json`, owned and managed by the add-on. On first boot, existing settings are automatically migrated from `options.json` — no manual action required. `config.yaml` now only holds InfluxDB credentials.

### Added

- Full-featured Settings page: all configuration (battery parameters, home settings, pricing, sensor entity IDs) is now editable directly in the UI — no more manual `config.yaml` editing for day-to-day configuration.
- First-time setup wizard with automatic detection of Home Assistant integrations (Growatt, Nordpool, Solcast, phase current sensors) — maps sensor entity IDs automatically so most users need zero manual configuration.

### Removed

- EV charging energy meter support removed (the feature was never wired up to the optimizer and had no effect on battery scheduling).

## [7.17.2] - 2026-04-11

### Added

- Compact debug export now serves three distinct use cases from a single endpoint: exact scenario replay, AI behaviour analysis via bess-analyst + MCP server, and prediction drift analysis throughout the day.
- Log filtering in compact mode: key events (errors, hardware commands, decisions, intent transitions) from the full day plus the last 50 lines, replacing the previous 2000-line tail that only covered ~2 hours.
- Entity snapshot rendered as a flat table in compact mode (state + unit per entity) with the full JSON in a collapsible for mock HA replay.
- Historical periods rendered as a compact markdown table (intent, observed intent, SOE, solar, import, savings) with full JSON collapsible for replay.
- Schedule section now includes economic summary and a period-decisions table in compact mode.
- Snapshot section now shows a full-day evolution table (all hourly optimization runs with total savings, actual count, predicted count) for drift analysis, instead of only the latest snapshot.
- `BESS_VERSION` environment variable set at Docker image build time; `_get_version()` reads it first before falling back to `config.yaml` (local dev).
- HA metadata fields (`last_changed`, `last_updated`, `last_reported`, `context`) stripped from entity snapshots — not used in any of the three debug use cases.
- `BESS_URL` added to `.env.example` for MCP server direct port access.

### Fixed

- Log formatter no longer suppresses log content when log lines contain the word "error" — now correctly checks for "error reading" to detect actual read failures.
- Debug log parser correctly identifies schedule JSON blocks in compact format by requiring the `optimization_period` key, ignoring the economic summary and input metadata blocks that precede the full schedule collapsible.
- `from_debug_log.py` scenario generator handles compact logs without `input_data` gracefully.
- Empty entity ID configured in sensor map now raises an explicit `ValueError` immediately instead of producing a confusing downstream failure.

## [7.16.1] - 2026-04-05

### Fixed

- Fixed solar-only charging not applying the configured charging power rate. The power monitor was returning early when grid charging was disabled, leaving the inverter at whatever rate was previously set. It now correctly applies 100% charging power for solar scenarios (no fuse risk).

## [7.16.0] - 2026-04-05

### Added

- Discharge inhibit: optional binary sensor (`discharge_inhibit`) that suppresses BESS discharge when active (e.g. EV charger on, Tibber grid award). Discharge resumes automatically within ~1 minute once the sensor clears. Leave the field empty to disable.

## [7.15.0] - 2026-04-03

### Added

- Dashboard alert banner now has two tiers: red (critical) for required sensor failures and amber (warning) for optional sensors that are configured but not responding.
- TOU segment write failures are now recorded in the runtime failure tracker and shown in the dashboard instead of being silently swallowed.
- Health checks treat `not_configured` sensors as SKIPPED rather than ERROR, preventing false warnings for optional sensors the user has not set up.

### Fixed

- Fixed timezone bug where `datetime.now()` returned UTC in the HA add-on container, causing off-by-one hour errors in period and date calculations for users in non-UTC timezones during the window around local midnight.
- Fixed spurious +0.1 kWh battery charge appearing in all predicted evening hours due to floating-point accumulation in `np.arange()` producing near-zero IDLE power that bypassed direction checks in `_compute_reward()`.
- Fixed Octopus Energy price source rejecting rates on DST spring-forward days (23-hour days now correctly require 46 periods instead of 48). (thanks [@pookey](https://github.com/pookey))

## [7.14.0] - 2026-04-02

### Added

- Debug export captures a full entity snapshot (raw HA state for every sensor BESS reads), enabling verbatim scenario replay in `mock-run.sh` without reconstructing values from processed data.
- Mock HA server handles `nordpool.get_prices_for_date` service calls and exposes `/api/config` for timezone, enabling correct `nordpool_official` replay.
- Mock HA replay seeds historical data directly from the scenario file, removing the InfluxDB dependency. Falls through to InfluxDB when the seed file is absent or all entries are invalid.

### Fixed

- Fixed `regex=` → `pattern=` in FastAPI `Query()` (Pydantic v2 compatibility).
- Container timezone is now propagated from the host in `dev-run.sh` and `mock-run.sh`.

## [7.13.0] - 2026-03-25

### Added

- Experimental SPH inverter support (`inverter_type: "SPH"` in config). MIN remains the default; SPH is opt-in. (thanks [@GraemeDBlue](https://github.com/GraemeDBlue))
- `power_monitoring_enabled` config option to disable phase current monitoring when current sensors are unavailable.

## [7.12.0] - 2026-03-25

### Added

- Mock HA development environment (`./mock-run.sh`) — runs the full BESS stack against a local FastAPI mock server. Scenarios are generated from debug logs; no real HA or inverter needed.
- Debug export now includes raw electricity prices, full addon options (entity IDs, inverter config), and active inverter TOU segments for exact scenario replay.

### Fixed

- Fixed `initial_soe` in debug log export being recorded as a percentage instead of kWh when the midnight SOC snapshot was used.

## [7.11.5] - 2026-03-25

### Fixed

- Fixed DP optimizer charging at a more expensive price window when a cheaper overnight window was available. The backward pass was not propagating future export value at max-SOE states, making early and late charging opportunities appear equally attractive.

## [7.11.4] - 2026-03-24

### Changed

- Refactored DP optimizer hot path to eliminate per-action dataclass allocation, reducing memory pressure during optimization.

### Fixed

- Fixed weather test helper generating invalid `hour=24` datetime strings when forecast spans midnight.

## [7.11.3] - 2026-03-24

### Fixed

- InfluxDB health check no longer reports OK when the bucket is misconfigured — it now tests connectivity with a sensor-agnostic query and reports a clear warning with the current bucket name and correct format.
- Fixed a variable name collision in the health check that caused a spurious "Critical System Issues Detected" error on startup.

### Changed

- `tax_reduction` default set to `0.0` — Swedish skattereduktion was removed as of Jan 1 2026.

### Documentation

- Added complete InfluxDB setup guide (Steps 2a–2f): two-user setup, `configuration.yaml` snippet, bucket naming (`homeassistant/autogen`), and connection verification.
- Added Nordpool electricity price section explaining VAT-exclusive pricing, the buy price formula, per-country VAT table, and Swedish cost breakdown (överföringsavgift, energiskatt, moms).
- Added InfluxDB troubleshooting section with InfluxDB UI navigation steps and a `curl` command to verify BESS read access.

## [7.11.2] - 2026-03-21

### Fixed

- Force Docker cache bust on every version bump so HA always builds frontend from latest source.

## [7.11.0] - 2026-03-21

### Changed

- Dashboard status cards redesigned: removed duplicate status badges, added inline colored pills for Grid/Battery direction and Strategic Intent.
- Battery card now shows Strategic Intent as the main KPI and Battery Mode as a sub-KPI.
- Status card labels renamed for clarity: "Power Flow"→"Home Power", "Solar Production"→"Solar Generation", "Home Load"→"Home Usage", "Grid Flow"→"Grid", "Energy & Power"→"Battery".
- Energy Flow chart switched from step bars to smooth monotone lines with midpoint positioning for clearer period visualisation.
- Battery Mode Schedule and Energy Flow chart horizontal axes now align exactly.
- Schedule intent labels updated to plain-language names: "Charging from Grid", "Storing Solar", "Powering Home", "Selling to Grid", "Standby".

## [7.10.0] - 2026-03-16

### Changed

- Dashboard chart layout: Schedule moved to top, followed by Energy Flow and Battery SOC charts. (thanks [@pookey](https://github.com/pookey))
- Consistent external section headings across all dashboard charts (Schedule, Energy Flow, Battery SOC and Energy Flow). (thanks [@pookey](https://github.com/pookey))
- Removed electricity price line from Battery SOC chart to reduce right-axis clutter. (thanks [@pookey](https://github.com/pookey))
- Removed "Battery" label and internal title from Battery Mode Timeline for cleaner layout. (thanks [@pookey](https://github.com/pookey))
- Removed "Actual hours" / "Predicted hours" legend labels from both charts (shading is self-explanatory). (thanks [@pookey](https://github.com/pookey))

## [7.9.5] - 2026-03-14

### Added

- Configurable consumption forecast strategy via `home.consumption_strategy`: `sensor` (default, HA 48h average), `fixed` (flat rate from config), or `influxdb_7d_avg` (7-day rolling average from InfluxDB power sensor data at 15-minute resolution). (thanks [@pookey](https://github.com/pookey))

## [7.9.4] - 2026-03-14

### Changed

- HA API retries now use exponential backoff (2s, 4s, 8s) instead of a fixed 4-second delay. (thanks [@pookey](https://github.com/pookey))
- TOU segment write failures now include a descriptive operation string and the HTTP response body for actionable diagnostics. (thanks [@pookey](https://github.com/pookey))

### Fixed

- Unavailable or unknown HA sensors now return `None` instead of 0.0, preventing zero values from corrupting optimization. (thanks [@pookey](https://github.com/pookey))
- Inverter page no longer blanks when a single API endpoint fails on startup. (thanks [@pookey](https://github.com/pookey))

## [7.9.3] - 2026-03-13

### Added

- Expired TOU intervals shown with reduced opacity, strikethrough times, and an "Expired" badge in the inverter schedule view. (thanks [@pookey](https://github.com/pookey))
- "Pending Write" amber badge on the inverter page for TOU segments queued but not yet written to hardware. (thanks [@pookey](https://github.com/pookey))

### Changed

- TOU schedule now uses a rolling window: only future periods generate segments, freeing hardware slots during mid-day re-optimizations. (thanks [@pookey](https://github.com/pookey))
- TOU segment IDs are stable across re-optimizations, preventing hardware slot divergence and overlap warnings. (thanks [@pookey](https://github.com/pookey))
- When >9 TOU segments are generated, all are kept in memory and the next 9 non-expired are written to hardware; pending segments cascade into freed slots on the next cycle. (thanks [@pookey](https://github.com/pookey))

### Fixed

- Schedule creation crash when optimization produces more than 9 TOU segments. (thanks [@pookey](https://github.com/pookey))
- KeyError when building stable segment IDs from intervals that had not yet been written to hardware. (thanks [@pookey](https://github.com/pookey))

## [7.8.1] - 2026-03-12

### Fixed

- Battery Mode Schedule tooltip showing incorrect times for sub-hour slot boundaries (e.g. 22:30 displayed as 22:00). (thanks [@pookey](https://github.com/pookey))
- Current-time marker on Battery Mode Schedule positioned at start of hour regardless of minutes elapsed. (thanks [@pookey](https://github.com/pookey))

## [7.8.0] - 2026-03-10

### Added

- Configurable single/three-phase electricity support via `home.phase_count` (1 or 3, default 3); fixes fuse protection for single-phase systems (common in the UK). (thanks [@pookey](https://github.com/pookey))

### Fixed

- `max_fuse_current`, `voltage`, and `safety_margin_factor` from config.yaml were not being applied — power monitor always ran on hardcoded defaults. (thanks [@pookey](https://github.com/pookey))

## [7.7.1] - 2026-03-10

### Fixed

- Add-on no longer discoverable from GitHub due to invalid `list?` schema type in `config.yaml`. Removed `derating_curve` from schema validation (HA Supervisor does not support nested list types).

## [7.7.0] - 2026-03-09

### Added

- Temperature-based charge power derating for outdoor batteries, using HA weather forecast to apply per-period charge limits via a configurable LFP derating curve. Opt-in via `battery.temperature_derating.enabled` in config.yaml. (thanks [@pookey](https://github.com/pookey))

## [7.6.2] - 2026-03-07

### Changed

- Profitability gate threshold now scales with remaining horizon (`max(15%, remaining/total)`) so mid-day optimizer runs are not held to a full-day savings bar.

## [7.6.1] - 2026-03-07

### Fixed

- Chart dark mode detection now tracks the `dark` CSS class on `<html>` via MutationObserver instead of OS `prefers-color-scheme`, correctly following Tailwind's `class` strategy.
- Axis tick label colors, grid lines, and price line now render correctly in dark mode.

### Changed

- Vite dev proxy target can be overridden via `VITE_API_TARGET` environment variable.

## [7.6.0] - 2026-03-07

### Added

- Battery Mode Schedule timeline on the Dashboard page, showing a color-coded horizontal bar of strategic intents (Grid Charging, Solar Storage, Load Support, Export Arbitrage, Idle) with hover tooltips, current-hour marker, and tomorrow's plan faded when available. (thanks [@pookey](https://github.com/pookey))

## [7.5.0] - 2026-03-07

### Added

- Timezone is now read automatically from Home Assistant's `/api/config` at startup instead of being hardcoded to `Europe/Stockholm`. Falls back to `Europe/Stockholm` with a warning if HA is unreachable. (thanks [@pookey](https://github.com/pookey))

## [7.4.5] - 2026-03-07

### Fixed

- Startup data collection for the last completed period used live sensors instead of InfluxDB, causing inflated values (e.g. ~2x) and leaving the next period nearly empty on the chart. (thanks [@pookey](https://github.com/pookey))
- Chart price line now shows visual gaps instead of dropping to zero when price data is unavailable.
- BatteryLevelChart SOC line no longer shows a flat 0% line for predicted hours with no data.

## [7.4.4] - 2026-03-07

### Fixed

- Chart grid lines now use `prefers-color-scheme` media query for dark mode detection, matching Tailwind's `media` strategy. Previously, charts used a DOM class check that detected Home Assistant's dark mode theme even when BESS UI was rendering in light mode, causing dark grid lines on a white background.

## [7.4.3] - 2026-03-07

### Fixed

- Visual improvements and alignment across EnergyFlowChart and BatteryLevelChart: predicted hours grey overlay added to BatteryLevelChart to match EnergyFlowChart, both charts now show a subtle grey background for tomorrow's data with a solid divider line at midnight.
- BatteryLevelChart tooltip now handles N/A values correctly and suppresses hover on the zero-anchor phantom point.
- Fixed `-0` display in battery action tooltip (now shows `0`).

## [7.4.2] - 2026-03-07

### Fixed

- EnergyFlowChart and BatteryLevelChart data now aligned to period start, eliminating one-period misalignment caused by a fake zero-point offset. (thanks [@pookey](https://github.com/pookey))
- Electricity price line now renders as a step function instead of smooth interpolation.
- Predicted hours shading now uses Recharts ReferenceArea instead of a raw SVG rect that rendered at incorrect coordinates.
- Tomorrow period numbers normalised correctly when API returns them as 96-191 continuation.
- X-axis tick labels use modulo 24 for clean hour display across the day boundary.

## [7.4.1] - 2026-03-07

### Fixed

- Terminal value calculation now uses the median of remaining buy prices instead of the average, preventing peak prices from inflating the estimate and causing the optimizer to hold charge instead of discharging during high-price periods. (thanks [@pookey](https://github.com/pookey))

## [7.4.0] - 2026-03-06

### Changed

- Currency is now configurable throughout the optimization pipeline and UI; removed hardcoded SEK/Swedish locale references. (thanks [@pookey](https://github.com/pookey))

## [7.3.0] - 2026-03-04

### Added

- Extended optimization horizon to 2 days when tomorrow's prices are available, enabling true cross-day arbitrage decisions. Only today's schedule is deployed to the inverter. (thanks [@pookey](https://github.com/pookey))
- Terminal value fallback when tomorrow's prices aren't yet published, preventing the optimizer from treating stored battery energy as worthless at end of day.
- Tomorrow's solar forecast support via Solcast `solar_forecast_tomorrow` sensor.
- Dashboard, Inverter, and Savings pages show tomorrow's planned schedule when available.
- DST-safe period-to-timestamp conversion throughout.

### Fixed

- Economic summary and profitability gate now scoped to today-only periods, preventing inflated savings figures when the horizon extends into tomorrow.

## [7.2.0] - 2026-03-02

### Changed

- DP optimizer assigns terminal value to stored battery energy at end of horizon, preventing premature end-of-day export.

## [7.1.1] - 2026-03-02

### Fixed

- Battery SOC no longer shows impossible values (e.g. 168%) when battery capacity differs from the 30 kWh default. `SensorCollector`, `EnergyFlowCalculator`, and `HistoricalDataStore` were initialised with the default capacity and only received the configured value via manual propagation in `update_settings()`. They now hold a shared `BatterySettings` reference so the configured capacity is always used for SOC-to-SOE conversion.

## [7.1.0] - 2026-03-01

Thanks to [@pookey](https://github.com/pookey) for contributing this fix (PR #20).

### Fixed

- InfluxDB CSV parsing now uses header-aware column detection instead of hardcoded indices, supporting both InfluxDB 1.x and 2.x where columns appear at different positions depending on version and tag configuration. Queries also match on both `_measurement` and `entity_id` tag to handle both data models.
- Historical data no longer lost after restart. A sensor name prefix mismatch in the batch query parser caused initial-value lookups to create duplicate entries that overwrote correct per-period values during normalization, producing flat SOC and zero energy deltas across the entire day.

## [7.0.0] - 2026-03-01

Thanks to [@pookey](https://github.com/pookey) for contributing Octopus Energy support (PR #19).

### Added

- Octopus Energy Agile tariff support as a new price source alongside Nordpool. Fetches import and export rates from Home Assistant event entities at 30-minute resolution with VAT-inclusive GBP/kWh prices.
- Separate import and export rate entities for Octopus Energy, allowing direct sell price data instead of calculated fallback.
- `get_sell_prices_for_date()` on `PriceSource` for sources that provide direct export/sell rates.
- `PriceManager.clear_cache()` to propagate settings changes at runtime without restart.
- Documentation for Octopus Energy setup in README, Installation Guide, and User Guide.
- UPGRADE.md with step-by-step migration instructions for the breaking config change.

### Changed

- **Breaking:** Unified energy provider configuration into a single `energy_provider:` section. The previous `nordpool:` top-level section and `nordpool_kwh_today`/`nordpool_kwh_tomorrow` sensor entries have been replaced. See [UPGRADE.md](UPGRADE.md) for migration instructions.
- Price logging now uses currency-neutral column headers instead of hardcoded "SEK".
- `HomeAssistantSource` now takes entity IDs directly via constructor instead of looking them up from the sensor map.
- Pricing parameters (markup, VAT, additional costs) now propagate immediately when updated via settings without requiring a restart.

### Removed

- `use_official_integration` boolean from config (replaced by `energy_provider.provider` field).
- `nordpool_kwh_today`/`nordpool_kwh_tomorrow` from `sensors:` section (moved to `energy_provider.nordpool`).
- Dead code: `LegacyNordpoolSource` class and unused Nordpool price methods from `ha_api_controller.py`.

### Fixed

- Grid charging now always charges at full power (100%) instead of being throttled to the DP algorithm's planned kW. The DP power level is an energy model artifact, not a hardware rate limit — the power monitor already handles fuse protection correctly. Previously, `hourly_settings` stored a proportional rate (e.g. 25% when the DP planned 1.5 kW out of 6 kW max), causing the inverter to charge far slower than it should during cheap price periods.
- Removed dead `charge_rate` local variable from `_apply_period_schedule` which was computed but never applied to hardware, eliminating the misleading split-brain between two code paths.

## [6.0.7] - 2026-03-01

### Fixed

- Grid charging now always charges at full power (100%) instead of being throttled to the DP algorithm's planned kW. The DP power level is an energy model artifact, not a hardware rate limit — the power monitor already handles fuse protection correctly. Previously, `hourly_settings` stored a proportional rate (e.g. 25% when the DP planned 1.5 kW out of 6 kW max), causing the inverter to charge far slower than it should during cheap price periods.
- Removed dead `charge_rate` local variable from `_apply_period_schedule` which was computed but never applied to hardware, eliminating the misleading split-brain between two code paths.

## [6.0.6] - 2026-02-26

### Fixed

- Historical data no longer shows as missing all day when InfluxDB is configured with InfluxDB 1.x (accessed via v2 compatibility API). The Flux query previously included a `domain == "sensor"` tag filter that is absent in 1.x setups, causing the batch query to silently return zero rows. The `_measurement` filter already uniquely identifies sensors, making the domain filter redundant.
- Batch sensor data that loads successfully but returns no periods is no longer cached, allowing the system to retry on the next 15-minute period rather than remaining stuck with an empty cache for the entire day.

## [6.0.5] - 2026-02-18

### Fixed

- System no longer crashes at startup if the inverter is temporarily unreachable when syncing SOC limits. A warning is logged and startup continues normally; the inverter retains its previous limits.

## [6.0.4] - 2026-02-08

### Added

- Compact mode for debug data export - reduces export size by including only latest schedule/snapshot and last 2000 log lines
- `compact` query parameter on `/api/export-debug-data` endpoint (defaults to `true`)

### Changed

- MCP server `fetch_live_debug` now uses `compact` parameter instead of `save_locally`
- Increased MCP server fetch timeout from 60s to 90s for large exports
- Raised `min_action_profit_threshold` default from 5.0 to 8.0 SEK

### Fixed

- Corrected `lifetime_load_consumption` sensor name in config.yaml (was pointing to daily sensor instead of lifetime)

## [6.0.0] - 2026-02-01

### Changed

- TOU scheduling now uses 15-minute resolution instead of hourly aggregation
- Eliminates "charging gaps" where minority intents were lost due to hourly majority voting
- Each 15-minute strategic intent period now directly maps to TOU segments
- Schedule comparison uses minute-level precision for accurate differential updates

### Added

- `_group_periods_by_mode()` groups consecutive 15-min periods by battery mode
- `_groups_to_tou_intervals()` converts period groups to Growatt TOU intervals
- `_enforce_segment_limit()` handles 9-segment hardware limit using duration-based priority
- DST handling for fall-back scenarios (100 periods) with proper time capping

### Fixed

- Single strategic period (e.g., 15-min GRID_CHARGING) now creates TOU segment instead of being outvoted
- Overlap detection uses minute-level precision instead of hour-level

## [5.7.0] - 2026-01-31

### Added

- MCP server for BESS debug log analysis - enables Claude Code to fetch and analyze debug logs directly
- Token-based authentication for debug export API endpoint (for external/programmatic access)
- `.bess-logs/` directory for cached debug logs (gitignored)

### Changed

- SSL certificate verification enabled by default for MCP server connections (security improvement)
- Optional `BESS_SKIP_SSL_VERIFY=true` environment variable for local self-signed certificates

## [5.6.0] - 2026-01-27

General release consolidating recent fixes.

## [5.5.0] - 2026-01-27

### Fixed

- Cost basis calculation now correctly accounts for pre-existing battery energy

## [5.4.0] - 2026-01-26

### Added

- InfluxDB bucket now configurable by end user in config.yaml

## [5.3.1] - 2026-01-23

### Fixed

- Improved sensor value handling in EnergyFlowCalculator

## [5.3.0] - 2026-01-22

### Changed

- Updated safety margin to 100%
- Removed "60 öringen" threshold
- Removed step-wise power adjustments

## [5.2.0] - 2026-01-22

General release consolidating v5.1.x fixes.

## [5.1.7] - 2026-01-18

### Fixed

- Missing period handling when HA sensors unavailable
- DailyViewBuilder now creates placeholder periods instead of skipping them when sensor data is unavailable (e.g., HA restart)
- Snapshot comparison API no longer crashes with IndexError

### Added

- `_create_missing_period()` to create placeholders with `data_source="missing"`
- Recovery of planned intent from persisted storage when available
- `missing_count` field in DailyView for transparency

## [5.1.6] - 2026-01-18

### Changed

- Refactored strategic intent to use economics-based decisions
- Strategic intent now derived from economic analysis rather than inferred from energy flows
- Prevents feedback loop where observed exports were incorrectly classified as EXPORT_ARBITRAGE

## [5.1.5] - 2026-01-17

### Fixed

- Fixed floating-point precision issue in DP algorithm where near-zero power levels (e.g., 2.2e-16) were incorrectly classified as charging/discharging instead of IDLE
- Fixed edge case in optimization where no valid action at boundary states (e.g., max SOE with unprofitable discharge) would leave period data undefined, now creates proper IDLE state
- Fixed `grid_to_battery` energy flow calculation to be correctly constrained by actual battery charging amount, preventing impossible energy flows

## [2.5.7] - 2025-11-10

### Fixed

- Fixed critical bug where invalid estimatedConsumption field in battery settings prevented all settings from being applied
- Fixed settings failures silently continuing with defaults instead of failing explicitly
- Currency and other user configuration now properly applied on startup

### Changed

- Settings application now fails fast with clear error message when configuration is invalid
- Removed estimatedConsumption from internal battery settings (now computed on-demand for API responses only)

## [2.5.5] - 2025-11-07

### Fixed

- Fixed initial_cost_basis returning 0.0 when battery at reserved capacity, causing irrational grid charging at high prices
- Fixed settings not updating from config.yaml due to camelCase/snake_case mismatch in update() methods
- Fixed dict-ordering bug where max_discharge_power_kw would be overwritten by max_charge_power_kw depending on key order
- Added explicit AttributeError for invalid setting keys instead of silent failures

### Changed

- Settings classes now convert camelCase API keys to snake_case attributes automatically
- Removed silent hasattr() checks in favor of explicit error handling
- Added Git Commit Policy to CLAUDE.md documentation

## [2.5.4] - 2025-11-07

### Fixed

- Fixed test mode to properly block all hardware write operations using "deny by default" pattern
- Fixed duplicate config.yaml files - now single source of truth in repository root
- Removed unused ac_power sensor configuration

### Changed

- Test mode now controlled via HA_TEST_MODE environment variable instead of hardcoded
- Updated docker-compose.yml to mount root config.yaml for development
- Updated deploy.sh and package-addon.sh to use root config.yaml

## [2.5.3] - 2025-11-06

### Fixed

- Fixed HACS/GitHub repository installation by restructuring to single add-on layout
- Moved add-on configuration files (config.yaml, Dockerfile, build.json, DOCS.md) to repository root
- Removed unnecessary bess_manager/ subdirectory (proper for single add-on repositories)
- Dockerfile now correctly references backend/, core/, and frontend/ from repository root
- Build context is now repository root, allowing direct access to all source directories

## [2.5.2] - 2024-11-06

### Added

- Home Assistant add-on repository support for direct GitHub installation
- Multi-architecture build configuration (aarch64, amd64, armhf, armv7, i386)
- repository.json for Home Assistant repository validation

### Fixed

- Removed duplicate config.yaml and run.sh files (now using symlinks)
- Removed duplicate CHANGELOG.md from bess_manager directory
- Fixed deploy.sh to work with symlinked configuration files

### Changed

- Restructured repository to comply with Home Assistant add-on store requirements

## [2.5.0] - 2024-10

- Quarterly resolution support for Nordpool integration
- Improved price data handling and metadata architecture

## [2.4.0] - 2024-10

- Added warning banner for missing historical data
- Added optimization start from below minimum SOC with warning
- Fixed savings and grid import columns in savings view

## [2.3.0] and Earlier

For earlier version history, see the [commit history](https://github.com/johanzander/bess-manager/commits/main/).

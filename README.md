# ChargeIQ — Smart Battery Optimization for Home Assistant

**Install it, forget it, and slash your energy bills.** ChargeIQ continuously optimizes your battery against live electricity prices, solar forecasts, and your household patterns.

![Dashboard Overview](./assets/dashboard.png)

---

## 🧪 jvdd Fork

> This is **Jan's personal fork** of [johanzander/bess-manager](https://github.com/johanzander/bess-manager), tuned for an **AC-coupled** setup in the Netherlands:
>
> - **Battery inverter:** Growatt MID 15KTL3-XH (3-phase, ~30 kWh battery)
> - **PV:** separate SolarEdge inverter — no DC solar on the Growatt, so battery only charges via the AC side
> - **Market:** Nord Pool NL (EUR/kWh) via Tibber, salderingsregeling
>
> Each fork release is tagged `9.6.x-jvdd.N` and published to `ghcr.io/jdungen/bess-manager-{arch}`.

### What this fork adds on top of upstream

| Feature | Why | Upstream status |
|---|---|---|
| **`external_solar_mode`** battery setting | On AC-coupled installs the Growatt has no DC solar input — without this, `SOLAR_STORAGE` periods do nothing. The flag flips `grid_charge=True` *and* TOU mode → `battery_first` so the inverter actively pulls from the AC side during the planned solar window. | [PR #167](https://github.com/johanzander/bess-manager/pull/167) — open |
| **`vpp_mode`** — direct power command via Growatt VPP registers | Bypasses TOU complexity entirely: writes signed % to `number.<*>_vpp_power` and toggles `select.<*>_vpp_status` per period. More reliable than juggling TOU slots, and Johan's preferred direction. | [issue #118](https://github.com/johanzander/bess-manager/issues/118) — proof-of-concept |
| SolaxModbus TOU begin/end via `time.*` entity mirror | On Growatt MID the `select.*_inverter_time_N_begin/end` entities are permanently `unavailable` and writes get silently dropped — TOU slot 1 was getting stuck on a stale time window. The parallel `time.*_time_N_begin/end` entities accept writes correctly; BESS now mirrors writes there. | [issue #181](https://github.com/johanzander/bess-manager/issues/181) — diagnostic |
| AI Analyst model IDs updated to current Claude generation | The hard-coded `claude-{sonnet,opus}-4-20250514` IDs from the 4.0 launch return 404 ahead of their 2026-06-15 retirement. Plus startup migration that rewrites legacy IDs in `bess_settings.json`. | [PR #180](https://github.com/johanzander/bess-manager/pull/180) — **merged in 9.6.3** ✅ |
| Nord Pool continental area hints (NL/BE/DE/FR/AT/PL) | The discovery hint map only covered the original Nord Pool members (SE/NO/DK/FI/EE/LT/LV/GB), so NL/BE/DE/FR/AT installs were locked to SEK and read-only. | [PR #164](https://github.com/johanzander/bess-manager/pull/164) — **merged in 9.6.3** ✅ |

### Settings → Battery — fork-only toggles

Two extra toggles in the Settings page, both default OFF (DC-coupled users see no change):

- **PV coupling → External solar mode** — enable on AC-coupled installs (separate PV inverter, no DC solar on battery inverter).
- **Inverter control mechanism → VPP control mode** — switch from TOU scheduling to direct power command via VPP. Requires the Growatt VPP entities to be configured (auto-discovered by Settings → Integrations → Auto-Configure).

### Hardware-verified behaviour

The full VPP control path has been live-verified on the Growatt MID 15KTL3-XH:
- Write sequence is **Disabled → power/time/ac_charging → Enabled** — the Disabled→Enabled edge is the only thing that retriggers the inverter (writing `Enabled` while already `Enabled` is silently ignored).
- `vpp_power` is **percentage** of inverter nominal AC power (range −100..100, step 5), `vpp_time` is **minutes** (range 0..1440, step 5). Writing watts/seconds returns HTTP 500.
- BESS' `_apply_period_vpp` maps strategic intent → percentage: GRID_CHARGING/SOLAR_STORAGE → +100, LOAD_SUPPORT/EXPORT_ARBITRAGE → −discharge_rate, IDLE → 0.

### Fork installation

Add the fork repository to Home Assistant:

```
https://github.com/jdungen/bess-manager
```

In the add-on store, install **BESS Manager** (it'll show the `9.6.x-jvdd.N` version). The image is pulled from `ghcr.io/jdungen/bess-manager-{arch}` — make sure that package is public on GHCR.

### Staying in sync with upstream

This fork rebases periodically on upstream `main` and force-pushes. Tags are stable. To check what's in the current fork build vs upstream, see [CHANGELOG.md](CHANGELOG.md) — the `jvdd` releases at the top spell out exactly which patches the fork carries on top of which upstream version.

---

### Setup in Minutes, Not Hours

No YAML files. No manual entering of entity IDs. The setup wizard auto-discovers your inverter, price source, and solar forecast from Home Assistant — just confirm and go.

![Setup Wizard](./assets/wizard.png)

### See Exactly Where Your Money Goes

ChargeIQ tracks every kWh and every cent. Compare three scenarios side by side — what you'd pay with **grid only**, with **solar only**, and with **solar + optimized battery** — so you can see exactly how much value the battery adds.

![Scenario Comparison](./assets/scenario-analysis.png)

### Predictions You Can Trust

See how accurate the forecasts are — solar, consumption, and savings — with predicted-vs-actual comparisons so you know it's working, not guessing.

![Insights](./assets/insights.png)

### Ask Your Battery Why

Something look off? The built-in AI Analyst explains every decision in plain language. Ask "why did the battery charge at 3am?" or "why are today's savings lower than yesterday?" and get a real answer backed by actual system data.

<img src="./assets/bess-analyst.png" width="400" alt="AI Analyst">

---

## Features

| | |
|---|---|
| **Optimization** | Dynamic programming finds the mathematically optimal schedule — not a simulation, not a heuristic |
| **Resolution** | 15-minute granularity (Nordpool) or 30-minute (Octopus) |
| **Solar aware** | Integrates solar forecast to maximize self-consumption |
| **Battery protection** | Models cycle degradation cost — won't chase marginal gains that wear out your battery |
| **Fuse protection** | Monitors grid current and limits charging to prevent overloading your main fuse |
| **EV aware** | Automatically pauses battery discharge when your EV is charging |
| **Re-optimization** | Continuously updates as prices, solar, and consumption data change |
| **AI Analyst** | Chat with your battery system — ask questions, get explanations |

## Supported Hardware & Markets

### Inverters
- **Growatt MIC/MIN/MOD/MID** — via Growatt Server (cloud) or Modbus (local)
- **Growatt SPH** — via Growatt Server(cloud) or Modbus (local)
- **SolaX** — via Solax modbus integration

### Electricity Markets
- **Nordpool** — Nordic spot market (SE, NO, FI, DK, EE, LT, LV)
- **Octopus Energy Agile** — UK market with separate import/export rates

### Optional Integrations
- **Solcast** or other solar forecast for production predictions
- **InfluxDB** for historical data persistence
- **Tibber** for power monitoring

> **Want support for your inverter?** We're actively looking for testers with GivEnergy, Solis, Huawei, and other systems. [Open an issue](https://github.com/johanzander/bess-manager/issues) or join the discussion!

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**, click the menu (⋮) → **Repositories**, and add: `https://github.com/johanzander/bess-manager`
2. Find **BESS Battery Manager** in the store, click **Install**, then **Start**
3. Open the web UI and follow the setup wizard

Full instructions: **[Installation Guide](docs/INSTALLATION.md)**

## Documentation

- [Installation Guide](docs/INSTALLATION.md) — Getting started
- [User Guide](docs/USER_GUIDE.md) — Understanding the interface
- [Development Guide](docs/DEVELOPMENT.md) — Contributing

## Community

- **Issues & feature requests**: [GitHub Issues](https://github.com/johanzander/bess-manager/issues)
- **Discussion**: [Home Assistant Community Forum](https://community.home-assistant.io/)

## License

MIT License — see [LICENSE](LICENSE) for details.

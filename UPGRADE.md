# Upgrade Guide

## Upgrading to 6.2.0

Version 6.2.0 introduces Octopus Energy support and unifies the energy provider
configuration. **Existing users must update their `config.yaml`** as described below.

### Config changes required

#### 1. Replace `nordpool:` section with `energy_provider:`

**Before (6.0.x):**

```yaml
nordpool:
  use_official_integration: true
  config_entry_id: "01K3Y99FD3MDZYVFX2XSWR4888"
```

**After (6.2.0) - for `nordpool_official` users:**

```yaml
energy_provider:
  provider: "nordpool_official"
  nordpool:
    today_entity: ""              # Not needed for nordpool_official
    tomorrow_entity: ""
  nordpool_official:
    config_entry_id: "01K3Y99FD3MDZYVFX2XSWR4888"
  octopus:
    import_today_entity: ""
    import_tomorrow_entity: ""
    export_today_entity: ""
    export_tomorrow_entity: ""
```

**After (6.2.0) - for legacy `nordpool` sensor users:**

```yaml
energy_provider:
  provider: "nordpool"
  nordpool:
    today_entity: "sensor.nordpool_kwh_se4_sek_2_10_025"
    tomorrow_entity: "sensor.nordpool_kwh_se4_sek_2_10_025"
  nordpool_official:
    config_entry_id: ""
  octopus:
    import_today_entity: ""
    import_tomorrow_entity: ""
    export_today_entity: ""
    export_tomorrow_entity: ""
```

#### 2. Remove Nordpool price sensors from `sensors:`

The `nordpool_kwh_today` and `nordpool_kwh_tomorrow` entries have moved into
`energy_provider.nordpool`. Remove them from your `sensors:` section:

```yaml
sensors:
  # REMOVE these two lines:
  # nordpool_kwh_today: "sensor.nordpool_kwh_se4_sek_2_10_025"
  # nordpool_kwh_tomorrow: "sensor.nordpool_kwh_se4_sek_2_10_025"
```

#### 3. (Optional) New Octopus Energy setup

If you are a UK user with Octopus Energy, see the
[Octopus Energy Setup](INSTALLATION.md#octopus-energy-setup) section in the
Installation Guide.

### Summary of config key changes

| Old key | New key |
|---------|---------|
| `nordpool.use_official_integration` | `energy_provider.provider` (`"nordpool"`, `"nordpool_official"`, or `"octopus"`) |
| `nordpool.config_entry_id` | `energy_provider.nordpool_official.config_entry_id` |
| `sensors.nordpool_kwh_today` | `energy_provider.nordpool.today_entity` |
| `sensors.nordpool_kwh_tomorrow` | `energy_provider.nordpool.tomorrow_entity` |

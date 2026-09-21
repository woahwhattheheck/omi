Automated weekly pulse detected one or more **nonzero** guardrail baselines that have not decreased for 30 days.

GitHub Issues are disabled on this repository, so this file is the durable tracking record.

Run: https://github.com/woahwhattheheck/omi/actions/runs/35647729331

## Pulse

```
union_return_isinstance      0     (baseline 0)
lifecycle_unlabeled_scripts  8     (baseline 8)
mapless_packages             0     (baseline 5)
version_prefixed_files       38    (baseline 38)
deferred_work_markers        811   (baseline 811)
brand_ui_purple              619   (baseline 619)
```

## Staleness

```
STALE: nonzero baselines with no decrease for 30 days: version_prefixed_files
```

Burn down the listed baselines (shrink the committed grandfather / pay the debt). This record is updated in place by `.github/workflows/guardrail-baseline-pulse.yml`.

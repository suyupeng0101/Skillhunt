# Scoring Formula

MVP recommendation score:

```text
recommendation_score = usability_score * 0.5 + adoption_score * 0.3 + maintenance_score * 0.2
```

Usability score:

- +40 for recognized install methods.
- +30 for quickstart, usage, install, example, or run instructions.
- +30 when no severe usability flags are present.
- Penalties apply for `demo_only`, `unclear_installation`, `no_quickstart`, `inactive_repo`, `kind_uncertain`, and heuristic fallback.

Adoption score:

- Uses log-scaled stars, forks, and watchers.
- Applies a small open-issue ratio penalty.
- Does not use npm, PyPI, Docker, or dependency download counts in MVP.

Maintenance score:

- Updated in 90 days: 100.
- Updated in 180 days: 70.
- Updated in 365 days: 40.
- Older or inactive: 10.

Brief generation:

- Include projects with `recommendation_score >= 50`.
- Exclude `demo_only` from top picks.
- Generate `why_pick` locally from score components and install method presence.

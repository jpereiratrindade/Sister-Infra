# Repository configuration examples

**EXAMPLE — NOT INSTALLATION AUTHORITY**

Files under this directory are contracts, examples, fixtures, test data, or
explicit seed inputs. Operational commands never select them merely because
they exist in the source tree.

Canonical external roots:

```text
LAB/workstation  ~/.config/sister/workstation/
production       /etc/sister/
```

Use `sister-infra authority seed-lab` for an explicit, reviewed LAB migration.
Production is never seeded from repository examples.

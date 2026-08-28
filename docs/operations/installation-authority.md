# Installation authority boundary

## Invariant

```text
CODE != INSTALLATION CONFIGURATION
```

The source repository supplies engine code, contracts, schemas, fixtures and
examples. It never silently supplies values for a real installation.

## Authority model

```text
engine/source               generic software
contracts/declarations      system structure and semantics
installation authority     selected composition, deployment, local policy
protected authorities      TLS private keys, PKI, DNS, secrets, approvals
```

An installation selects or pins a composition. This does not transfer the
semantic ownership of the composition contract to the installation.

## Resolution

All direct consumers use `sister-authority` with this precedence:

```text
explicit CLI path
        ↓
explicit target environment override
        ↓
target installation config root
        ↓
FAIL-CLOSED
```

Canonical roots:

```text
LAB/workstation  ~/.config/sister/workstation
production       /etc/sister
```

Overrides include `SISTER_WORKSTATION_CONFIG_ROOT` and
`SISTER_PRODUCTION_CONFIG_ROOT`. Production sandboxes may derive
`<SISTER_PRODUCTION_ROOT>/etc/sister`.

Resolved context reports target, root, path, source, status and SHA-256 digest
for composition selection, deployment and optional installation policy.

## Layout

```text
<config-root>/
├── composition.json
├── deployment.json
├── policy.json             optional installation-local policy
└── tls/                    protected external authority
```

System governance policy does not become installation `policy.json`.

## Command semantics

- `bootstrap` creates derivable layout only. It never creates or overwrites
  composition, deployment, policy or TLS.
- `check` is read-only and fails when required authority is absent.
- `doctor` diagnoses source and installation separately without repair.
- `plan` is read-only and includes authority provenance and digests.
- `status` exposes the authority context governing observed state.
- apply/promote paths consume declarations or resolved evidence derived from
  validated authority.

Gateway bind, port, public hosts and runtime bindings come from deployment.
Explicit target environment values remain operator-controlled overrides.

## Explicit LAB migration

Review repository examples first, then run:

```bash
sister-infra authority seed-lab \
  --composition-source config/compositions/workstation.json \
  --deployment-source config/deployments/workstation-lab.json
```

The operation refuses divergent existing destinations, is idempotent for
byte-identical files and emits JSON evidence. It does not activate runtime.

Production has no repository seed path.

## Changing domain or IP

1. Edit external `deployment.json` under administrative authority.
2. Run authority resolve/status and record digests.
3. Run plan and review changed bindings/publication.
4. Apply through existing approval gates.

No engine source edit is involved. DNS and TLS changes remain actions of their
respective protected institutional authorities.

## Failure and recovery

Missing files fail closed. Repository examples are never fallback. Restore a
reviewed external authority backup, verify its digest, then plan again.

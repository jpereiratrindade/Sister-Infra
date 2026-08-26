# sister.infra.candidate/1

Contrato autoritativo de **candidata imutável** para o `sister-infra`.

## Responsabilidade

A candidata é o pacote imutável e verificável que resulta da qualificação de uma composição:

- reúne a evidência de qualificação (`evidence/composition/qualification.json`);
- lista os participantes qualificados com seus commits exatos e caminhos relativos;
- lista os artefatos binários verificados por hash SHA-256;
- define o status do deployment como `PENDING_BINDINGS`.

A candidata é **neutra em relação a ambiente**: ela não contém bindings físicos, portas, hosts, certificados TLS ou service managers.

## Schema

- Schema canônico: `sister.infra.candidate/1`
- Schema legado aceito: `sister.infra.workstation.candidate/1`

## Transição para Release

A candidata é consumida por `sister-deployment resolve` juntamente com uma declaração de deployment (`sister.infra.deployment/1.0.0`):

```text
sister.infra.candidate/1  +  sister.infra.deployment/1.0.0
                              ↓
                sister.infra.deployment.resolved/1 (READY)
```

Uma mesma candidata qualificada pode ser resolvida tanto para um deployment de laboratório/desktop (`workstation-lab`) quanto para um deployment de servidor/produção (`server-production`).

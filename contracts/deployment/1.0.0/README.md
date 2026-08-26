# Contrato de deployment 1.0.0

O contrato `sister.infra.deployment/1.0.0` descreve como uma implantação
concreta liga os participantes de uma candidata qualificada à infraestrutura
física. A identidade continua pertencendo exclusivamente ao
`.sister/component.json`; por isso cada binding referencia apenas `system_id`.

Cada participante deve receber exatamente um binding. O resolvedor rejeita
participantes ausentes ou desconhecidos, identidades duplicadas, colisões de
endpoint TCP e hosts de gateway repetidos.

## Runtime

- `tcp` exige `listen` e `port` (1 a 65535) e proíbe `socket`;
- `unix` exige um `socket` absoluto e proíbe `listen` e `port`.

`probe` e `gateway` são opcionais. A ausência de `gateway` significa que o
participante não é publicado externamente. Nesta versão, `probe.health_path`
é dado operacional do binding.

## Resolução

```bash
./bin/sister-deployment resolve \
  /caminho/para/candidate/manifest.json \
  config/deployments/workstation-lab.json --json
```

Somente candidatas com qualificação `PASS`, deployment
`PENDING_BINDINGS` e `composition_id` compatível podem ser resolvidas. O
resultado usa o contrato `sister.infra.deployment.resolved/1` e o status
`READY`.

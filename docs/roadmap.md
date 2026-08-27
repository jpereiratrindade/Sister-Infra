# SisTer Infra — Roadmap Operacional

## Princípio

Este documento distingue explicitamente:

- concluído;
- em desenvolvimento;
- planejado.

Uma funcionalidade proposta não deve ser apresentada como disponível antes de
sua implementação e prova factual.

## Estado dos incrementos

### OPS-00 — Auditoria factual

**DONE**

Mapeamento das primitivas existentes, lifecycle, gateway, releases,
component-scoped actions e estado factual da workstation.

### OPS-01 — Current / Desired Model

**DONE**

Introdução do modelo explícito de comparação entre:

```text
declared current
actual current
desired
```

### OPS-02 — Declarative Read-Only Plan

**DONE**

Disponibilização de:

```bash
sister-infra lab plan
```

com:

- ações determinísticas;
- reasons;
- observação factual;
- read-only;
- genericidade.

### OPS-03 — Transactional Component-Scoped Apply

**DONE**

Disponibilização da base transacional de:

```bash
sister-infra lab apply
```

incluindo propriedades como:

- `KEEP` intocado;
- update component-scoped;
- repair;
- releases imutáveis;
- target release;
- rollback;
- lifecycle lock;
- atomic release switch;
- authoritative deployment verification;
- proxy-independent runtime probes.

### OPS-04 — Safe Derived-Resource Reconciliation

**DONE**

Integração comprovada de recursos derivados ao ciclo transacional de
`lab apply`:

- `ADD` e `REMOVE` transacionais de participantes no nível de componente;
- atualização atômica da ecosystem projection (`tmp + rename(2)`);
- graceful HAProxy reload (`-sf <pid_old>`) sem queda de listeners;
- rollback do gateway restaurando configuração anterior sobre processo TARGET ativo;
- reconciliação controlada do leaf quando a publicação do gateway/SANs exigir;
- preservação estrita de `CA_CERT` e `CA_KEY` (fail-closed se rotação for requerida);
- verificação ponta a ponta (health local, HTTPS via gateway com SNI e observação);
- rollback integrado na ordem inversa sem resíduos transitórios;
- zero resíduos de fixtures comprovado (filesystem + processos + listeners).

### OPS-05 — DEV Preview

**NEXT (PLANNED)**

Experiência pretendida:

```bash
sister-infra dev preview atmos
```

Objetivo:

testar um participante no contexto do SisTer sem alterar o LAB instalado.
Ainda não implementado.

Propriedades pretendidas:

- isolamento;
- portas temporárias;
- release LAB intocada;
- gateway opcional ou ausente;
- lifecycle descartável.

### OPS-06 — LAB UX Simplificada

**PLANNED**

Objetivo:

reduzir a necessidade de fornecer manualmente caminhos de candidata e
deployment.

Experiência pretendida:

```bash
sister-infra lab plan
sister-infra lab apply
```

com o desired state derivado de uma declaração operacional canônica.

### OPS-07 — Production Adapter / Authority Gates

**PLANNED**

Objetivo:

usar o mesmo modelo declarativo e reconciliador sob políticas produtivas.

Inclui, potencialmente:

- DNS real;
- TLS real;
- secrets;
- autoridade institucional;
- observabilidade;
- evidências;
- rollback;
- gates de implantação.

## Visão de chegada

A interface final desejada deve permitir que o operador pense em intenção, não
em procedimentos mecânicos.

```text
DEV
quero testar Atmos isoladamente

LAB
quero que este seja meu ecossistema cotidiano

PROD
quero implantar este estado autorizado
```

O `sister-infra` deve então:

```text
observar
comparar
explicar
validar autoridade
agir minimamente
verificar
registrar evidência
```

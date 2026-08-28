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

**DONE**

Disponibilização de:

```bash
sister-infra dev preview <component>
```

como sessão temporária de desenvolvimento de um componente que declara runtime
operacional, sem alterar o LAB instalado.

Propriedades comprovadas:

- descoberta normativa via `.sister/component.json`;
- binding DEV autoritativo via `sister-deployment`;
- sandbox efêmera;
- portas dinâmicas com retry;
- suporte explícito a source dirty restrito ao DEV Preview;
- `source.clean=false` registrado como evidência;
- rejeição de evidência dirty por composition/candidate;
- lifecycle e health contratuais;
- cleanup scoped;
- zero resíduos após encerramento;
- preservação integral do LAB;
- prova factual com URT real em DEV Preview simultâneo ao URT instalado no LAB.

### OPS-06 — LAB UX Simplificada

**DONE**

Disponibilização da experiência operacional:

```bash
sister-infra lab plan
sister-infra lab apply
```

sem necessidade de fornecer manualmente caminhos de candidata e deployment.

O desired state LAB passa a ser derivado das declarações canônicas versionadas
no control plane:

```text
config/compositions/workstation.json
config/deployments/workstation-lab.json
```

com precedência explícita dos overrides:

```text
SISTER_WORKSTATION_COMPOSITION_FILE
SISTER_WORKSTATION_DEPLOYMENT_FILE
SISTER_WORKSTATION_CONTROL_PLANE_SOURCE
```

Propriedades comprovadas:

- camada de UX separada em `sister-lab`;
- `sister-reconcile` permanece motor genérico, sem conhecer defaults da workstation;
- candidata implícita materializada apenas em sandbox efêmera;
- cleanup obrigatório em sucesso e falha;
- `lab plan` preserva ausência de mutação persistente;
- overrides explícitos permanecem retrocompatíveis;
- ausência de declaração necessária falha fechado;
- stdout JSON permanece puro;
- defaults oficiais são derivados do control plane;
- regressões de `reconcile plan` e `reconcile apply` preservadas;
- prova factual real de `sister-infra lab plan` sem argumentos manuais.

Na prova real de fechamento, o plano observou `sister`, `nexo` e `praxis` como
`KEEP` e `urt` como `UPDATE`, mantendo gateway e ecosystem projection como
`KEEP`.

### OPS-07A0 — Maintenance Semantics

**DONE**

Aplicação operacional de `REARIT-P001@0.1.0` à manutenção do control plane.

Fronteira adotada e comprovada:

```text
check      read-only
bootstrap  materialização idempotente de pré-condições ausentes
doctor     diagnóstico read-only
repair     trabalho futuro (não pertence ao OPS-07A0; próximo incremento)
```

O Gate 0 identificou que o bootstrap histórico mantinha uma segunda
representação concreta de participantes e que `doctor` e outros comandos
observacionais herdavam mutação de `ensure_dirs`.

A correção eliminou a mutação espúria, estabeleceu a materialização isolada de
pré-condições locais, e restaurou o contrato de separação de canais:

```text
CLI normal:
  stdout = resultado operacional
  stderr = diagnóstico/log

CLI com --json:
  stdout = exatamente um documento JSON válido
  stderr = diagnóstico/log permitido
```

Critérios comprovados por testes automatizados:

- observação (`check`, `doctor`) não cria estado;
- bootstrap executa preflight antes de mutar;
- bootstrap repetido converge para `NO_OP`;
- divergência existente falha fechado;
- manutenção permanece genérica (zero participantes concretos hardcoded);
- conhecimento derivável continua vindo das declarações autoritativas;
- contrato JSON puro em `release-create --json` e `release-verify --json`
  protegido por teste regressivo (Gate J);
- `setup_sister_infra.sh` não é modernizado como segunda implementação;
- OPS-07A1 comprovou ausência de dependência operacional e retirou o bootstrap
  histórico da árvore corrente, preservando sua genealogia no Git.

### OPS-07A1 — Historical Bootstrap Retirement

**DONE**

Retirada da implementação histórica `setup_sister_infra.sh` da árvore
operacional corrente após prova factual de que:

- não havia consumidores operacionais ativos;
- o TLS legado do SisTer estava expirado;
- a CA corrente é administrada pela fronteira declarativa da workstation;
- o runtime corrente não depende do bootstrap histórico;
- a genealogia permanece preservada no Git.

A retirada elimina uma segunda representação concreta de participantes, hosts,
portas, templates e lifecycle sem alterar o runtime instalado.

### OPS-07 — Production Adapter / Authority Gates

**NEXT (PLANNED)**

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

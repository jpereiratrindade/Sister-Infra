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

O desired state LAB passa a ser derivado da authority externa da workstation:

```text
~/.config/sister/workstation/composition.json
~/.config/sister/workstation/deployment.json
```

com precedência explícita dos overrides:

```text
SISTER_WORKSTATION_COMPOSITION_FILE
SISTER_WORKSTATION_DEPLOYMENT_FILE
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
- defaults oficiais são derivados da installation authority externa;
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

### OPS-07A2 — TLS Authority Convergence

**DONE**

Convergência factual da autoridade TLS do LAB, eliminando concorrência de fontes,
fallbacks espúrios para o clone Git e ciclos mutantes em runtime.

Sub-incrementos realizados e comprovados:

- **A2.1 — Reconciler sem fallback para repo secrets**:
  Eliminação do fallback histórico de `sister-reconcile` para `<repo>/secrets/`.
  Invariante fail-closed comprovado: se o caminho declarado ou o diretório de TLS
  estiver ausente, o reconciliador recusa atuar em vez de recorrer ao repositório.

- **A2.2a — First-boot explícito da CA**:
  Introdução da interface administrativa:
  ```bash
  sister-infra lab tls status [--json]
  sister-infra lab tls init-ca [--json]
  ```
  Propriedades comprovadas: observação estritamente read-only (`status`),
  criação exclusiva sob lock de processo (`fcntl.flock`), publicação atômica do
  bundle inteiro via rename de diretório, idempotência (`NO_OP`) sobre autoridade
  existente, bloqueio fail-closed sobre estados parciais/inválidos e proteção do
  namespace de `$CONFIG_ROOT/tls/`.

- **A2.2b — Desacoplamento do boot de runtime do lifecycle TLS**:
  Remoção de `generate_lab_tls` de `cmd_up()`. O cold-start do gateway HAProxy
  passa a consumir estritamente a autoridade existente (`TLS_PEM`), falhando
  fechado se o leaf estiver ausente, sem jamais gerar, renovar ou rotacionar CA.

- **A2.2c — Eliminação de defaults operacionais de repo/secrets**:
  Retirada definitiva de qualquer referência a `$INFRA_ROOT/secrets` de
  `load_profile()` e do control plane. O caminho canônico do TLS no LAB passa a ser
  exclusivamente `${SISTER_WORKSTATION_CONFIG_ROOT:-$HOME/.config/sister/workstation}/tls`.

- **A2.2d — Aposentadoria do lifecycle e bootstrap TLS legados**:
  Remoção de mais de 400 linhas de código Bash legado (`generate_lab_tls`,
  `generate_lab_ca`, `generate_lab_server_certificate`, `lab_tls_*`) e do verbo
  top-level `sister-infra bootstrap`, substituído pelo fluxo canônico:
  `workstation bootstrap` → `lab tls status/init-ca` → `lab apply`.

- **A2.2e — Higienização de repo/secrets**:
  Remoção de todos os resíduos locais de chaves e certificados de `<repo>/secrets/`,
  preservando exclusivamente `secrets/.gitkeep`. Prova estrita de não-dependência
  e zero consumidores operacionais.

### OPS-07A3 — Operational Reflexive Repair

**DONE**

Materialização e fechamento do **Operational Reflexive Repair** na workstation (`sister-workstation repair`), aplicando os princípios `REARIT-P001` (Manutenção Reflexiva Automatizável) e `REARIT-P005` (Autonomia Delegada por Fronteiras).

O comando `repair` atua sobre *drift factual comprovado* de um ambiente operacional já instalado em `current`, executando o ciclo estrito:

```text
OBSERVE → COMPARE → EXPLAIN → AUTHORITY → MINIMAL ACT → VERIFY → EVIDENCE
```

Fronteira adotada e comprovada:

- **Repair autorizado**:
  - Symlinks locais derivados e comprováveis (`CLI_LINK` → control plane da release `current`);
  - Permissões de runtime (`0600` em `runtime.env`, chaves e PEMs; `0644` em `unit` e certificados; `0700` em diretórios com permissão insegura/escrita global);
  - Unit systemd derivável (`sister-workstation.service` renderizada do template da release corrente sob autoridade de `daemon-reload`);
  - Processo gerenciado parado (participante com porta livre e estado íntegro reiniciado e validado por health check);
  - Gateway gerenciado parado (HAProxy reiniciado quando autoridade TLS e configuração forem íntegras).

- **Fail-closed obrigatório**:
  - Release modificada ou corrompida (`RELEASE_CORRUPTED`);
  - Porta ocupada por processo externo não gerenciado (`PORT_COLLISION_EXTERNAL`);
  - Autoridade TLS inválida ou ausente (`TLS_AUTHORITY_INVALID` — repair nunca cria CA);
  - Dados persistentes ausentes ou com tipo incompatível (`PERSISTENT_DATA_CORRUPTED`);
  - Deployment divergente (`DEPLOYMENT_DIVERGENT`);
  - Ação que implique mudança de versão (`CURRENT_RELEASE_MISSING`).

Propriedades comprovadas pelos 13 Gates de `tests/workstation_repair_test.py`:
- Plan antes de mutação (`--plan` e `--dry-run` não mutam filesystem);
- Idempotência (`repair` consecutivo produz `NO_OP` com 0 ações);
- Pós-verificação automática de todos os recursos reparados;
- Pureza estrita de stdout JSON (`sister.infra.workstation.repair/1.0.0`);
- Não-mutação dos bytes da release instalada;
- Runtime real de host preservado e intocado.

### OPS-07 — Production Adapter / Authority Gates

**DONE**

Materialização do adaptador produtivo de autoridade institucional:

```bash
sister-infra production plan
sister-infra production apply
sister-infra production verify
```

Propriedades comprovadas e invariantes (PRD-001 a PRD-019):
- **Plan Read-Only & Digest Selado**: `production plan` é estritamente read-only e gera digest criptográfico determinístico SHA-256 sobre o payload canônico (PRD-001, PRD-002, PRD-003);
- **Travas de Autoridade Institucional**: `production apply` exige `--plan` e `--plan-digest` correspondentes, aprovação explícita institucional (`PRODUCTION_APPROVED=YES`, `SISTER_INFRA_PRODUCTION_CONFIRM=YES`) e comando de gate externo (`PRODUCTION_GATE_CMD`), falhando fechado em qualquer ausência ou divergência (PRD-004, PRD-016);
- **Preflights Rigorosos**: Preflight completo antes de qualquer mutação, englobando fontes 100% limpas no control plane e componentes (`clean-source gate`), validação de certificado TLS externo (data, chave, parse e cobertura de SANs), verificação passiva de readiness de DNS e detecção de colisão de portas (PRD-005, PRD-006, PRD-008, PRD-010, PRD-018);
- **FHS & Sandbox Hermético**: Estrutura FHS institucional (`/opt/sister`, `/etc/sister`, `/var/lib/sister`, `/run/sister`), isolável via `$SISTER_PRODUCTION_ROOT` (PRD-011);
- **Transacionalidade e Rollback**: Materialização isolada em staging, rollback automático em falha de start, health probe ou service manager, e commit point atômico via comutação do symlink `/opt/sister/current` (PRD-013);
- **Idempotência & Verificação**: Reaplicação idempotente (`NO_OP` com 0 ações) e `production verify` estritamente read-only (PRD-015, PRD-001);
- **Auditoria Sanitizada**: Geração de evidências auditáveis sem qualquer vazamento de segredos ou chaves privadas (PRD-014, PRD-007);
- **Preservação Ontológica**: O modelo canônico (`component → composition → candidate → deployment → plan → reconcile`) e os ambientes LAB/Workstation permanecem intactos e intocados (PRD-017, PRD-018).

> [!IMPORTANT]
> **Fronteira Institucional de Autoridade (PRD-019)**:
> O executor de host real está disponível sob autorização explícita e `systemd`
> fail-closed. Os 24 gates herméticos validam o adaptador sem alegar uma implantação
> institucional específica; execuções reais produzem testemunho próprio do host.

### OPS-08 — End-to-End Lifecycle Automation

**DONE**

Materialização do controlador de ciclo de vida unificado e declarativo:

```bash
sister-infra lifecycle plan
sister-infra lifecycle run
sister-infra lifecycle status
sister-infra lifecycle maintain
sister-infra lifecycle evidence
```

Propriedades comprovadas e invariantes (Gates L1 a L25):
- **Orquestração sem Duplicação (`REARIT-P002`)**: Zero reimplementação de compilação, qualificação, reconciliação, repair ou produção. O controlador delega integralmente para as capacidades existentes;
- **Plan & Status Estritamente Read-Only**: `lifecycle plan` e `lifecycle status` observam o ecossistema com pureza absoluta, sem qualquer mutação de disco (Gates L1, L2);
- **Fail-Closed em Quebra de Contrato**: Falha de compilação, teste de unidade, ausência de autoridade ou incompatibilidade de deployment bloqueiam o ciclo imediatamente, identificando o estágio falho (`FAILED_STAGE`) e a razão factual (Gates L4, L5, L13, L22);
- **Preview DEV Isolado**: Preview em loopback sem tocar o runtime LAB (Gate L8);
- **LAB Apply e Verify Mandatório**: Reconciliação automatizada com verify como gate obrigatório pós-apply (Gates L9, L10);
- **Manutenção Reflexiva One-Shot (`REARIT-P001`)**: `lifecycle maintain` observa drift factual; se íntegro produz `NO_OP`; se divergente, planeja, executa `repair` mínimo e pós-verifica (Gates L11, L12);
- **Promoção Formal (`WHAT WAS VERIFIED = WHAT IS PROMOTED`)**: A promoção avalia formalmente a identidade da candidata, pureza de fontes, evidências de qualificação e histórico de LAB, emitindo `promotion evidence` selada sem rebuilds silenciosos (Gates L14, L15);
- **Produção Governada Fail-Closed**: Preflights, digest SHA-256 da árvore completa da candidata, plano selado, systemd real sem fallback e aplicação transacional com rollback (Gates L16, L17, L18, L19);
- **Cadeia de Evidências Rastreável (`REARIT-P004`)**: Genealogia operacional completa acessível via `lifecycle evidence` (Gate L20);
- **Idempotência Operacional**: Reexecução consecutiva de qualquer estágio é 100% idempotente (Gate L21);
- **Genericidade Estática (`REARIT-P003`)**: Zero conhecimento embutido de participantes (`urt`, `nexo`, etc.) ou portas fixas (Gate L23);
- **Prova com Sistema Real Testemunha (URT)**: Prova real executada contra o repositório URT em sandbox efêmero com mutações sintéticas inofensivas, preservando 100% a árvore e branch originais do URT (Gate L24);
- **Preservação Absoluta do Host**: O runtime de produção real (HAProxy 8443, PID 9488) permaneceu intocado (Gate L25).

### OPS-09 — Installation Authority Boundary

**DONE**

O engine deixou de usar o source tree como installation authority implícita.
`sister-authority` centraliza precedência, paths, provenance e SHA-256 para LAB
e produção. Gateway bind/port passam pelo deployment resolvido; exemplos sob
`config/` são explicitamente não autoritativos.

Gates UX33–UX45 comprovam mudança de domínio/IP sem código, source read-only,
fail-closed sem authority, identidade consistente, bootstrap não criador e
preservação byte a byte da configuração externa.

### OPS-10 — Control Plane Simplification

**IN PROGRESS**

Objetivo operacional:

> A equipe administra intenção, configuração e autoridade; o SisTer Infra
> administra e explica o procedimento.

O programa preserva autoridades de domínio coesas, elimina implementações e
caminhos mutáveis concorrentes, define contratos estáveis para operador e
automação e só então simplifica entrypoints e topologia de instalação.

Fases incrementais:

```text
OPS-10A  contratos atuais e grafo de chamadas       DONE
OPS-10B  operator UX / automation contract          DONE
OPS-10C  caminhos operacionais canônicos            DONE
OPS-10D  extração incremental dos mecanismos         IN PROGRESS
OPS-10E  entrypoints finos e compatibilidade
OPS-10F  topologia de instalação
```

A baseline factual do OPS-10A está em
[`architecture/control-plane-contract-audit.md`](architecture/control-plane-contract-audit.md).
O contrato arquitetural do OPS-10B está em
[`architecture/operator-automation-contract.md`](architecture/operator-automation-contract.md).

Nenhum executável foi movido ou removido no OPS-10A. A auditoria encontrou o
ciclo `sister-infra → sister-workstation → sister-infra up`, rotas mutáveis
concorrentes para produção e LAB e contratos heterogêneos de JSON, stderr e
exit codes. Essas evidências definem as decisões obrigatórias do OPS-10B.

Primeiro corte do OPS-10C: `sister-infra up/down --profile production` falha
antes de qualquer mutação e orienta para o único fluxo governado
`production plan → production apply`. O comando histórico não pode ser um
forward seguro porque não identifica plano nem digest aprovado.

Segundo corte: o mecanismo de runtime do gateway foi extraído para o adapter
privado `libexec/sister-infra/runtime-gateway`. A fachada `sister-infra` e o
runtime da workstation delegam ao mesmo mecanismo. O ciclo executável
`sister-infra → sister-workstation → sister-infra up` deixou de existir, e a
fachada deixou de implementar renderização, PID lifecycle e probes do gateway.

Terceiro corte (OPS-10C3): a superfície pública de `sister-infra --help` foi
consolidada para expor exclusivamente os namespaces canônicos orientados a
intenção (`dev`, `lab`, `production`, `lifecycle`, `workstation`, `authority`).
Comandos históricos top-level (`up`, `down`, `status`, `verify`, `client-env`,
`hosts-line`) foram retirados da ajuda pública, encaminham com aviso acionável
de depreciação para seus donos estáveis ou adapter privado e possuem cobertura
pelo gate de aceitação `tests/public_cli_contract_test.py`.

Quarto corte (OPS-10D Frente A — Unificação e Fechamento do Contrato de Installation Lock): fechamento completo do contrato de lock por *installation identity* (OPS-10B §7). Implementação do use-case lock ownership (`sister-lab apply` e `sister-production apply` adquirem o lock antes da invocação dos motores internos, passando `SISTER_INSTALLATION_LOCK_FD` para herança segura), unificação do caminho canônico para `installation.lock` (com ponte de link simbólico e detecção fail-closed `INSTALLATION_LOCK_IDENTITY_CONFLICT` contra split-brain), isolamento rigoroso do estado de produção (sem materialização de paths legados de workstation) e validação de todos os gates em `tests/installation_lock_contract_test.py`.

Quinto corte (OPS-10D Frente B — Target Ownership do Ciclo de Vida): eliminação da duplicação de lógica procedural de LAB em `sister-lifecycle`. O lifecycle agora coordena estritamente os donos canônicos de cada target (`sister-dev` para DEV, `sister-lab` para LAB, `sister-production` para Produção), sem implementar diretamente reconciliação, release-create ou release-switch. Validação estrita de contratos de máquina (fail-closed em saídas malformadas/incompletas) e comprovação hermética dos 16 gates em `tests/lifecycle_target_ownership_test.py`.

## Visão de chegada

A interface final desejada permite que o operador pense em intenção, não em procedimentos mecânicos:

```text
DEV
quero testar URT isoladamente:
sister-infra lifecycle run --target dev --component urt

LAB
quero que este seja meu ecossistema cotidiano:
sister-infra lifecycle run --target lab

PROD
quero implantar este estado autorizado:
sister-infra lifecycle run --target production
```

O `sister-infra` então executa autonomamente:

```text
observar
comparar
explicar
validar autoridade
agir minimamente
verificar
registrar evidência
```

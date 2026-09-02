---
document_id: SISTER-INFRA-HC-001
document_type: implementation_mission
title: "Hard Close do Ciclo LAB → PRODUCTION"
version: 0.2.0
status: "CODE_COMPLETE / REAL_WITNESS_PENDING"
created_at: 2026-09-02
updated_at: 2026-09-02
repository: sister-infra
baseline_branch: main
baseline_commit: 22ee330f3e8d07425002a2c89aeea6ef87078f2d
baseline_origin_main: 22ee330f3e8d07425002a2c89aeea6ef87078f2d
baseline_gitlab_main: 22ee330f3e8d07425002a2c89aeea6ef87078f2d
baseline_relation: "main, origin/main e gitlab/main sincronizados"
source_snapshot: "sister-infra(20260902-135444).zip"
scope_class: hard-close
execution_authority_repository: FULL_DELIVERY
execution_authority_lab: FULL_DELIVERY
execution_authority_real_production: "EXPLICIT_INSTITUTIONAL_APPROVAL_REQUIRED"
supersedes: "SISTER-INFRA-HC-001 v0.1.0"
roadmap_binding: "não atribuído; não renumerar OPS existentes implicitamente"
normative_basis:
  - "WHAT WAS VERIFIED = WHAT IS PROMOTED"
  - "fail-closed"
  - "single source of truth"
  - "minimal transformation"
  - "candidate neutral across environments"
  - "LAB and PRODUCTION differ by deployment bindings/policy, not by build"
review:
  method: "two-pass factual + architectural review against current snapshot"
  status: COMPLETED
current_assessment:
  control_plane: "VERY_MATURE"
  dev: "MATURE"
  lab: "MATURE"
  reconciliation: "MATURE"
  promotion: "NEAR_HARD_CLOSE"
  production_engine: "IMPLEMENTED_FAIL_CLOSED"
  production_real: "READY_FOR_FINAL_HARD_CLOSE_AND_REAL_WITNESS"
---

# SISTER-INFRA-HC-001 — Hard Close do Ciclo LAB → PRODUCTION

## 1. Decisão atualizada

O `sister-infra` **não necessita de novas funcionalidades de produto antes do fechamento desta missão**.

O estado atual já contém, de forma coerente e majoritariamente `fail-closed`:

```text
SOURCE
  ↓
CANDIDATE
  ↓
LAB PLAN/APPLY
  ↓
LAB VERIFY + EVIDENCE
  ↓
PROMOTION
  ↓
PRODUCTION PLAN
  ↓
AUTHORITY
  ↓
SYSTEMD + GATEWAY APPLY
  ↓
PRODUCTION VERIFY
```

A missão permanece necessária somente para eliminar **três ambiguidades residuais** e produzir a prova factual final do caminho canônico.

---

## 2. Baseline factual atual

```text
repository: sister-infra
branch:     main
HEAD:       22ee330f3e8d07425002a2c89aeea6ef87078f2d
origin:     22ee330f3e8d07425002a2c89aeea6ef87078f2d
gitlab:     22ee330f3e8d07425002a2c89aeea6ef87078f2d
state:      três autoridades Git sincronizadas
```

### 2.1 Propriedades já fechadas e que DEVEM ser preservadas

- candidata durável sob estado controlado;
- identidade canônica por digest SHA-256 da árvore completa:
  `sister.infra.candidate.tree/1+sha256`;
- produção não cria candidata a partir das fontes;
- promoção exige evidência LAB com o **mesmo digest**;
- produção real usa `systemd` por padrão na raiz `/`;
- `mock` é proibido na raiz produtiva real;
- `systemctl` falha fechado, sem fallback para processo direto;
- `SYSTEMD ACTIVE` é condição necessária;
- HAProxy produtivo é materializado e governado;
- TLS produtivo é externo/institucional;
- DNS produtivo é verificado, não administrado pelo Infra;
- health direto dos componentes é verificado;
- acesso HTTPS pelos subdomínios é verificado;
- LAB canônico é `HTTP + IP + portas`;
- PRODUCTION canônica é `HTTPS + host routing`;
- candidata e composição permanecem neutras de ambiente;
- documentação operacional básica está alinhada ao LAB `ip-ports`;
- `main`, `origin/main` e `gitlab/main` estão sincronizados.

### 2.2 Provas reproduzidas nesta revisão

Foram reproduzidos com `PASS` no snapshot atual:

```text
tests/declarative_single_domain_test.py
tests/documentation_contract_alignment_test.py
```

A ausência de HAProxy no ambiente de revisão impediu a reprodução local de
`lab_ip_ports_gateway_test.py`; isso é limitação do ambiente desta revisão,
não evidência de falha do produto.

---

## 3. Questões ainda abertas

### HC-01 — `gateway.domain` ainda não é obrigatório em PRODUCTION

A política produtiva atual valida:

```text
gateway.protocol = https
gateway.exposure = host
```

mas **não exige `gateway.domain`**.

O próprio `build_production_plan()` ainda contém fallback:

```text
se gateway.domain existe:
    host = <component_id>.<domain>
senão:
    aceitar binding.gateway.host
```

Isso mantém uma segunda via de autoridade de publicação exatamente na fronteira
em que a arquitetura pretende ter domínio único declarativo.

A validação atual aceita factual e diretamente:

```json
{
  "gateway": {
    "protocol": "https",
    "exposure": "host",
    "listen": "1.2.3.4",
    "port": 443
  }
}
```

sem `gateway.domain`.

### Invariante requerida

```text
PRODUCTION
  gateway.protocol = https
  gateway.exposure = host
  gateway.domain   = obrigatório

<component_id normalizado> + gateway.domain
  → hostname produtivo

binding.gateway.host
  → nunca é autoridade produtiva
```

---

### HC-02 — `LAB NO_OP` ainda pode emitir evidência para candidata não materializada

No fluxo atual:

1. o lifecycle possui uma `active_candidate`;
2. `lab apply` pode retornar `NO_OP`;
3. `workstation verify` passa sobre a release corrente;
4. a evidência LAB é então emitida usando:

```text
candidate_id     = active_candidate
candidate_path   = active_candidate
candidate_digest = digest(active_candidate)
```

O `NO_OP` do reconciliador não retorna, hoje, a proveniência da release que
efetivamente está materializada.

Portanto ainda existe a possibilidade semântica de:

```text
CANDIDATE B recém-criada
        ↓
LAB APPLY = NO_OP
        ↓
VERIFY da release materializada por CANDIDATE A
        ↓
evidence atribuída a CANDIDATE B
```

Isso viola literalmente:

```text
WHAT WAS VERIFIED = WHAT IS PROMOTED
```

### Invariante requerida

A evidência LAB deve provar:

```text
release verificada
   → candidata de origem
   → candidate_id
   → candidate_digest
```

Uma candidata que não originou a release materializada **não pode ganhar
evidência promotável por equivalência implícita**.

---

### HC-03 — A suíte ainda contém duas semânticas concorrentes de LAB

O deployment canônico atual é inequívoco:

```text
LAB
  protocol = http
  exposure = ip-ports
  domain   = ausente
```

Entretanto, partes importantes da suíte ainda chamam de “LAB” cenários antigos:

```text
protocol = https
domain   = lab.sister.local
host routing
TLS gerado no LAB
```

Isso ocorre, em especial, em:

```text
tests/production_real_close_test.py
tests/declarative_single_domain_test.py
```

O `production_real_close_test.py` ainda executa o E2E LAB → PRODUCTION usando
LAB HTTPS/host.

O `declarative_single_domain_test.py` possui, simultaneamente:

- gates antigos de LAB por domínio/TLS;
- um gate final que corretamente valida o deployment canônico `HTTP/ip-ports`.

Assim, os testes provam capacidades úteis, mas **não formam uma única narrativa
canônica do ambiente LAB atual**.

### Invariante requerida

O único E2E que recebe o nome de caminho canônico deve provar:

```text
CANDIDATE X
digest = D
      │
      ├── LAB
      │     HTTP
      │     IP + portas
      │     sem domain
      │     VERIFY PASS
      │
      └── PRODUCTION
            HTTPS
            gateway.domain
            subdomínios
            SYSTEMD + HAProxy
            VERIFY PASS

digest(LAB) = digest(PRODUCTION) = D
```

Cenários host/TLS que ainda sejam úteis para testar o resolvedor ou renderer
podem permanecer, mas devem ser nomeados como **contrato genérico de host
routing**, e não como LAB canônico.

---

## 4. Objetivo da missão

Fechar o ciclo garantindo factual e automaticamente:

```text
MESMA CANDIDATA
      │
      ├── LAB  → HTTP / IP / portas
      │          VERIFY PASS
      │          evidência de proveniência
      │
      └── PROD → HTTPS / subdomínios derivados
                 SYSTEMD + GATEWAY
                 VERIFY PASS
```

Ao final, esta UX deve ser verdadeira sem exceções ocultas:

```bash
./bin/sister-infra lifecycle run --target lab
./bin/sister-infra lifecycle run --target production
```

O segundo comando somente promove a candidata cuja identidade foi
inequivocamente comprovada no LAB.

---

## 5. Invariantes obrigatórias

### I-01 — Mesma candidata

Nenhum rebuild, recriação ou substituição silenciosa entre LAB e PRODUCTION.

Identidade promotável:

```text
sister.infra.candidate.tree/1+sha256
```

### I-02 — Proveniência factual

Toda evidência LAB promotável identifica a candidata que originou a release
materializada e verificada.

### I-03 — `NO_OP` não cria mérito inexistente

Uma candidata nova não recebe `LAB VERIFIED` apenas porque seu plano produziu
`NO_OP`.

### I-04 — Transformação mínima

Não materializar release nova apenas para trocar identidade ou satisfazer
rastreabilidade.

### I-05 — Domínio único em PRODUCTION

Produção possui uma única autoridade declarativa de publicação:

```text
gateway.domain
```

### I-06 — Nenhuma segunda fonte de verdade

Em PRODUCTION, host/domínio/proxy/TLS por participante não compete com
`gateway.domain`.

### I-07 — Paridade de artefato, não de transporte

LAB e PRODUCTION podem projetar a mesma candidata com bindings e exposição
diferentes.

### I-08 — Produção permanece fail-closed

Nenhuma alteração desta missão pode enfraquecer os contratos PRD atuais,
autoridade institucional, plano selado, TLS externo, `systemd` real,
health/HTTPS verify ou rollback.

---

## 6. Trabalho autorizado

### Frente A — Tornar domínio único uma política produtiva absoluta

**Alvos principais:**

```text
bin/sister-production
bin/sister-deployment
contracts/deployment/1.0.0/
tests/
docs/operations/production.md
```

Implementar:

1. `validate_production_gateway_policy()` deve exigir `gateway.domain`;
2. ausência de domínio deve falhar fechado com código semântico estável,
   preferencialmente `PRODUCTION_DOMAIN_REQUIRED`;
3. `build_production_plan()` não deve derivar `declared_hosts` de
   `binding.gateway.host`;
4. qualquer host/domínio/proxy/certificado concorrente por participante deve ser
   rejeitado no caminho produtivo;
5. compatibilidade genérica/legada, se ainda necessária para outros modos, não
   pode atravessar a política PRODUCTION.

**Não fazer:** reintroduzir domínio ou TLS no LAB `ip-ports`.

---

### Frente B — Fechar a proveniência do `LAB NO_OP`

**Alvos principais:**

```text
bin/sister-reconcile
bin/sister-lifecycle
bin/sister-workstation
tests/
```

O reconciliador/lifecycle deve conseguir provar:

```text
current release
   → source candidate
   → candidate_id
   → candidate_digest
```

#### Caso A — houve materialização

A evidência deve referenciar a candidata efetivamente materializada.

#### Caso B — `NO_OP` e active candidate é exatamente a candidata da release

A evidência pode ser renovada para a mesma candidata, após validação de digest.

#### Caso C — `NO_OP` e active candidate é diferente da candidata da release

Resultado obrigatório:

```text
NÃO emitir LAB VERIFIED para a candidata nova
```

A candidata promotável permanece sendo a candidata que originou a release
verificada.

Se a proveniência estiver ausente, inconsistente ou não puder ser comprovada:

```text
FAIL-CLOSED
```

**Não aceitar como equivalência suficiente:**

```text
candidate_id isolado
path
timestamp
commits iguais
plano NO_OP
payload aparentemente equivalente
```

O digest e a proveniência materializada são a autoridade.

---

### Frente C — Consolidar uma única prova E2E canônica

**Alvos principais:**

```text
tests/production_real_close_test.py
tests/declarative_single_domain_test.py
tests/lab_ip_ports_gateway_test.py
tests/dual_deployment_portability_test.py
tests/documentation_contract_alignment_test.py
```

#### C1 — E2E principal

Alterar o E2E LAB → PRODUCTION para usar:

```text
LAB
  gateway.protocol = http
  gateway.exposure = ip-ports
  gateway.domain   = absent

PRODUCTION
  gateway.protocol = https
  gateway.exposure = host
  gateway.domain   = definido
```

A mesma candidata e o mesmo digest devem atravessar os dois ambientes.

#### C2 — Eliminar semântica de teste concorrente

Os testes antigos de:

```text
lab.sister.local
LAB TLS
LAB host routing
```

devem ser:

- removidos se não tiverem mais função; ou
- reclassificados como testes genéricos de `host-routing/domain-derived`,
  sem afirmar que representam o LAB canônico.

#### C3 — Teste explícito do `NO_OP`

Adicionar gate que demonstre:

```text
candidate A materializada
candidate B criada
B produz NO_OP
VERIFY observa release A
B não recebe evidence LAB VERIFIED
```

#### C4 — Teste explícito do domínio produtivo

Adicionar gates:

```text
PRODUCTION sem gateway.domain → FAIL-CLOSED
PRODUCTION com binding.gateway.host concorrente → FAIL-CLOSED
```

---

### Frente D — Witness real

Somente após os gates herméticos e regressivos:

1. executar `lifecycle run --target lab`;
2. identificar candidata e digest efetivamente verificados;
3. preparar deployment produtivo com `gateway.domain`;
4. obter autorização institucional;
5. garantir certificado e DNS institucionais;
6. executar `lifecycle run --target production`;
7. comprovar:
   - mesmo digest;
   - plano selado;
   - autoridade;
   - units `systemd ACTIVE`;
   - HAProxy ativo;
   - health direto;
   - DNS;
   - TLS;
   - HTTPS por todos os subdomínios;
   - release corrente;
   - evidência completa;
   - rollback verificável quando induzida falha pré-commit.

Nenhuma mutação produtiva real está autorizada apenas por este documento.

Sem autoridade ou infraestrutura institucional:

```text
CODE_COMPLETE
REAL_WITNESS_PENDING
```

e nunca `DONE`.

---

## 7. Ações proibidas

A equipe **NÃO DEVE**:

- adicionar nova superfície pública de CLI;
- criar novo engine de deployment/reconciliação;
- reintroduzir domínio/TLS no LAB `ip-ports`;
- alterar sistemas integrados para configurar gateway;
- manter host público por participante como autoridade produtiva;
- reconstruir candidata durante promoção;
- emitir evidência LAB para candidata não materializada;
- criar release artificial para contornar `NO_OP`;
- permitir `mock` na raiz produtiva real;
- restaurar fallback de `systemd`;
- enfraquecer authority gates;
- enfraquecer health/TLS/DNS/HTTPS verify;
- hardcodar participantes concretos no engine genérico;
- tratar testes antigos de LAB host/TLS como prova do LAB canônico;
- executar produção real sem autorização institucional;
- declarar fechamento apenas por sandbox.

---

## 8. Gates obrigatórios atualizados

| Gate | Critério | Resultado |
|---|---|---|
| HC-G01 | PRODUCTION sem `gateway.domain` | FAIL-CLOSED |
| HC-G02 | PRODUCTION com `binding.gateway.host` como autoridade concorrente | FAIL-CLOSED |
| HC-G03 | LAB canônico `http/ip-ports`, sem domínio/TLS | PASS |
| HC-G04 | mesma candidata projetada em LAB e PROD | mesmo digest |
| HC-G05 | LAB apply com materialização | evidência aponta candidata materializada |
| HC-G06 | LAB NO_OP com mesma candidata da release | evidência válida |
| HC-G07 | LAB NO_OP com candidata nova | candidata nova NÃO recebe LAB VERIFIED |
| HC-G08 | promoção sem evidência LAB do digest exato | FAIL-CLOSED |
| HC-G09 | E2E LAB `ip-ports` → PROD `host/domain` | PASS |
| HC-G10 | testes host/TLS antigos não são apresentados como LAB canônico | PASS |
| HC-G11 | regressões do control plane | PASS |
| HC-G12 | documentação/contratos convergentes | PASS |
| HC-G13 | `git diff --check` | PASS |
| HC-G14 | worktree/stage | limpos |
| HC-G15 | local/origin/gitlab após publicação da missão | mesmo commit |
| HC-G16 | witness em produção real | PASS antes de `DONE` |

---

## 9. Testes mínimos

Preservar e executar, no mínimo:

```text
tests/lab_ip_ports_gateway_test.py
tests/production_real_close_test.py
tests/declarative_single_domain_test.py
tests/dual_deployment_portability_test.py
tests/deployment_resolver_test.py
tests/lifecycle_automation_test.py
tests/production_adapter_test.py
tests/documentation_contract_alignment_test.py
```

Adicionar apenas os gates ausentes.

Não substituir regressões existentes por uma suíte agregadora que esconda
falhas.

---

## 10. Documentação

Revisar factual e minimamente:

```text
README.md
contracts/deployment/1.0.0/README.md
docs/operations/modes.md
docs/operations/lab.md
docs/operations/lifecycle.md
docs/operations/production.md
docs/roadmap.md
```

A narrativa final deve possuir uma única semântica:

```text
LAB
  HTTP
  IP + portas
  sem DNS/TLS obrigatório

PRODUCTION
  HTTPS
  host routing
  gateway.domain obrigatório
  subdomínios derivados
  TLS/DNS institucionais

PROMOTION
  mesma candidata
  mesmo tree digest
  evidência da release efetivamente verificada
  sem rebuild
```

---

## 11. Witness final esperado

A cadeia de evidência deve reconstruir:

```text
SOURCE COMMIT(S)
      ↓
CANDIDATE ID + TREE DIGEST
      ↓
LAB RELEASE MATERIALIZADA
      ↓
LAB VERIFY PASS
      ↓
LAB EVIDENCE
      ↓
PROMOTION EVIDENCE
      ↓
PRODUCTION PLAN + DIGEST
      ↓
AUTHORITY
      ↓
PRODUCTION APPLY
      ↓
SYSTEMD + GATEWAY
      ↓
PRODUCTION VERIFY PASS
      ↓
CURRENT RELEASE
```

Com a prova:

```text
candidate_digest(materialized LAB)
==
candidate_digest(promotion)
==
candidate_digest(PRODUCTION)
```

---

## 12. Condição de parada

### `CODE_COMPLETE`

Somente quando:

- HC-G01..HC-G14 estiverem PASS;
- documentação estiver convergente;
- nenhuma autoridade produtiva real tiver sido ultrapassada.

### `REAL_WITNESS_PENDING`

Estado obrigatório quando código e testes estiverem fechados, mas produção
institucional não estiver autorizada/disponível.

### `DONE`

Somente quando:

- HC-G01..HC-G16 estiverem PASS;
- a mesma candidata materializada e verificada no LAB tiver sido promovida;
- produção real tiver sido verificada externamente;
- evidências estiverem preservadas;
- autoridades Git estiverem novamente sincronizadas.

---

## 13. Resultado de chegada

A missão termina apenas quando for factual:

> **O operador integra no LAB canônico por HTTP/IP-portas; o Infra registra qual
> candidata originou a release efetivamente verificada e promove exatamente essa
> candidata para PRODUCTION, onde domínio único, TLS/DNS institucionais,
> `systemd`, gateway e health são projetados e verificados de forma fail-closed.**

A UX pública permanece:

```bash
./bin/sister-infra lifecycle run --target lab
./bin/sister-infra lifecycle run --target production
```

A complexidade pertence ao control plane; a intenção permanece com o operador.

---

## 14. Alterações em relação à v0.1.0

### Fechado desde a versão anterior

- `main`, `origin/main` e `gitlab/main` estão sincronizados em `22ee330`;
- documentação básica do LAB `ip-ports` está alinhada;
- digest de candidata por árvore completa permanece comprovado;
- `systemd` real permanece fail-closed e sem fallback;
- `mock` permanece restrito a sandbox/teste;
- produção possui health direto e verificação HTTPS pelo gateway.

### Mantido como aberto

- `gateway.domain` obrigatório em PRODUCTION;
- proveniência correta no `LAB NO_OP`;
- E2E canônico `LAB ip-ports → PRODUCTION host/domain`.

### Refinado nesta versão

A dívida de E2E foi ampliada para incluir a **taxonomia dos próprios testes**:
cenários históricos de LAB HTTPS/host/TLS não podem continuar sendo apresentados
como representação do LAB canônico.

---

## 15. Versionamento deste documento

```text
MAJOR  alteração de objetivo, invariantes ou condição de fechamento
MINOR  ampliação compatível de gates/escopo
PATCH  esclarecimento sem mudança normativa
```

Estados:

```text
PROPOSED
ACCEPTED
IN_EXECUTION
CODE_COMPLETE
REAL_WITNESS_PENDING
DONE
SUPERSEDED
```

Este documento deve permanecer preservado após o fechamento. Evoluções futuras
devem ocorrer por nova versão ou sucessão explícita.

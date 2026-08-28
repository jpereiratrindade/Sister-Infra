# SisTer Infra — Control Plane Operacional Declarativo

O `sister-infra` é o control plane operacional do ecossistema SisTer.

Ele não decide em código quais sistemas concretos constituem uma instalação.
Cada componente se autodescreve; uma composição declara os participantes; um
deployment declara os bindings físicos; e os modos operacionais determinam
quais transformações podem ser materializadas em cada contexto.

A regra central é:

```text
desired state
    = declarações versionadas do control plane

current state
    = release instalada + estado factual observado
```

---

## 1. Modelo declarativo

```text
.sister/component.json
        │
        ▼
sister-component
discover / inspect / qualify
        │
        ▼
composition
        │
        ▼
sister-composition
resolve / qualify
        │
        ▼
candidate
commits + artefatos qualificados
        │
        ▼
deployment
        │
        ▼
sister-deployment
bindings / probes / gateway
        │
        ▼
resolved deployment
        │
        ├── runtimes
        ├── gateway
        └── TLS/SAN
```

A materialização operacional é feita sem conhecimento hardcoded dos
participantes concretos.

### 1.1 Responsabilidades

| Camada | Responsabilidade |
|---|---|
| Componente | Identidade, `system_id`, build, testes, artefatos e contrato de runtime. |
| Composição | Seleção declarativa dos participantes por `source`. |
| Qualificação | Build/teste isolado e evidência dos artefatos qualificados. |
| Candidata | Materialização imutável dos commits e artefatos desejados. |
| Deployment | Bindings físicos, probes e publicação de gateway. |
| Reconciliador | Comparação `CURRENT × DESIRED`, plano determinístico e apply transacional. |
| Workstation | Releases, `current`, `previous`, runtime instalado e rollback. |

Contratos normativos vivem em `contracts/`.

---

## 2. Modos operacionais

DEV, LAB e PROD representam contextos diferentes de autoridade, persistência e
risco. Não são três produtos independentes.

```text
DEV
  experimentar um componente sem perturbar o LAB

LAB
  reconciliar o ecossistema cotidiano contra a intenção canônica

PROD
  implantar estado autorizado sob políticas produtivas
```

### 2.1 DEV Preview

Disponível desde OPS-05:

```bash
./bin/sister-infra dev preview <component>
```

Exemplos:

```bash
./bin/sister-infra dev preview ../sister-urt
./bin/sister-infra dev preview ../sister-urt --duration 30
```

O DEV Preview:

- descobre o componente por `.sister/component.json`;
- exige runtime operacional declarado;
- cria sandbox efêmera;
- usa binding DEV autoritativo via `sister-deployment`;
- utiliza porta dinâmica com retry quando necessário;
- pode executar source dirty explicitamente no contexto DEV;
- registra `source.clean=false` como evidência quando aplicável;
- não altera `current` ou `previous`;
- não reinicia nem modifica o LAB;
- executa cleanup scoped e não deixa resíduos.

Um componente sem runtime operacional deve ser qualificado/testado, não
"forçado" a caber em preview.

### 2.2 LAB

A UX canônica está disponível desde OPS-06:

```bash
./bin/sister-infra lab plan
./bin/sister-infra lab apply
```

Por padrão, o desired state é derivado de:

```text
config/compositions/workstation.json
config/deployments/workstation-lab.json
```

Os overrides permanecem disponíveis:

```bash
./bin/sister-infra lab plan \
  --desired-candidate <candidate-dir> \
  --desired-deployment <deployment.json>

./bin/sister-infra lab apply \
  --desired-candidate <candidate-dir> \
  --desired-deployment <deployment.json>
```

A camada `sister-lab` resolve a UX e cria candidata efêmera quando necessário.
O motor `sister-reconcile` continua genérico e recebe candidata + deployment
explicitamente.

`lab plan` é observacional. `lab apply` é transacional, protegido por lock e
atua somente no change-set autorizado.

### 2.3 PROD

A interface reconciliada de produção é o próximo incremento do roadmap
(OPS-07).

Código, contratos e políticas podem permanecer públicos. Credenciais, chaves,
segredos, configuração produtiva real e autoridade institucional devem ficar
fora do repositório.

---

## 3. Como adicionar um participante

Adicionar um novo subsistema não exige alteração concreta no motor do
`sister-infra`.

### 3.1 Declarar o componente

O repositório do participante fornece `.sister/component.json`.

```bash
./bin/sister-component inspect /caminho/para/componente
./bin/sister-component qualify /caminho/para/componente
```

### 3.2 Incluir na composição LAB

Exemplo em `config/compositions/workstation.json`:

```json
{
  "source": "../../../novo-componente"
}
```

### 3.3 Declarar o binding

Exemplo em `config/deployments/workstation-lab.json`:

```json
{
  "system_id": "novo_sistema",
  "runtime": {
    "transport": "tcp",
    "listen": "127.0.0.1",
    "port": 8095
  },
  "probe": {
    "health_path": "/health"
  },
  "gateway": {
    "host": "novo-gateway.test"
  }
}
```

### 3.4 Planejar e aplicar

```bash
./bin/sister-infra lab plan
```

Revise o change-set e os `reason`s. Se estiver autorizado:

```bash
./bin/sister-infra lab apply
```

O control plane decide as ações mínimas necessárias (`KEEP`, `ADD`, `UPDATE`,
`REMOVE`, `REPAIR`) a partir das declarações e do estado factual.

---

## 4. Workstation e releases

`workstation` expõe primitivas de baixo nível usadas pelo lifecycle instalado e
pelo reconciliador.

```bash
# Diagnóstico
./bin/sister-infra workstation doctor
./bin/sister-infra workstation plan

# Candidatas e releases
./bin/sister-infra workstation candidate-create
./bin/sister-infra workstation candidate-verify <id>
./bin/sister-infra workstation release-create
./bin/sister-infra workstation release-verify <dir>
./bin/sister-infra workstation release-list

# Promoção e rollback
./bin/sister-infra workstation install <release-id>
./bin/sister-infra workstation promote <release-id>
./bin/sister-infra workstation rollback

# Estado e saúde
./bin/sister-infra workstation current
./bin/sister-infra workstation status
./bin/sister-infra workstation verify
./bin/sister-infra workstation logs
```

Essas primitivas não substituem a UX de alto nível `lab plan/apply`.

### 4.1 Layout `user-scope`

```text
~/.local/share/sister/
├── candidates/
│   └── wc-.../
├── releases/
│   └── wr-.../
│       ├── manifest.json
│       ├── evidence/
│       │   ├── composition/
│       │   │   └── qualification.json
│       │   └── deployment/
│       │       ├── declaration.json
│       │       └── resolved.json
│       └── components/
├── current  -> releases/wr-...
└── previous -> releases/wr-...

~/.config/sister/workstation/
├── tls/
└── runtime.env

~/.local/state/sister/workstation/
├── control-plane/
├── components/
└── run/

~/.config/systemd/user/
└── sister-workstation.service
```

Releases são imutáveis. Mudanças materializam uma `TARGET_RELEASE`; o commit
operacional ocorre pela troca atômica de `current`/`previous`.

---

## 5. Reconciliação LAB

Fluxo conceitual:

```text
LOCK
 ↓
OBSERVE CURRENT
 ↓
RESOLVE DESIRED
 ↓
PLAN
 ↓
PREFLIGHT / AUTHORITY
 ↓
MATERIALIZE TARGET
 ↓
ACT
 ↓
VERIFY
 ↓
COMMIT
 ↓
FINAL VERIFY
```

Propriedades comprovadas nos incrementos OPS-01 a OPS-06:

- `plan` read-only;
- `reason` obrigatório para ações;
- `KEEP` forte;
- `ADD`, `UPDATE`, `REMOVE` e `REPAIR`;
- bloqueio fail-closed de `RECONFIGURE` não autorizado;
- lock compartilhado do lifecycle;
- releases imutáveis;
- rollback transacional;
- `release-switch` atômico;
- gateway HAProxy com graceful reload;
- projection refresh atômico;
- reconciliação controlada do TLS leaf LAB;
- preservação da CA;
- zero resíduos após falha;
- idempotência (`NO_OP`);
- UX LAB sem paths manuais.

Detalhes: `docs/operations/reconciliation.md`.

---

## 6. Gateway e TLS

Gateway e TLS são derivados do deployment resolvido.

O HAProxy:

- não contém tabela concreta hardcoded de participantes;
- é renderizado a partir de `gateway.host`;
- suporta graceful reload;
- participa do rollback transacional.

No LAB, o TLS:

- deriva SANs dos hosts publicados;
- preserva a CA quando válida;
- pode reemitir o leaf quando bindings publicados mudam;
- falha fechado quando uma decisão de autoridade sobre a CA for necessária.

Material privado não deve ser versionado.

---

## 7. Testes e gates

Testes principais:

```bash
# Contratos e resolvedores
python3 tests/component_resolver_test.py
python3 tests/composition_resolver_test.py
python3 tests/composition_qualification_test.py
python3 tests/deployment_resolver_test.py
python3 tests/gateway_renderer_contract_test.py

# Workstation e lifecycle declarativo
python3 tests/workstation_composition_candidate_test.py
python3 tests/workstation_declarative_lifecycle_test.py
python3 tests/workstation_unit_renderer_contract_test.py

# Reconciliação
python3 tests/reconcile_plan_test.py
python3 tests/reconcile_apply_test.py
python3 tests/derived_resources_apply_test.py

# Modos operacionais
python3 tests/dev_preview_test.py
python3 tests/lab_ux_test.py

# Plano de dados / TLS
bash tests/data_plane_contract_test.sh
bash tests/tls_lifecycle_test.sh

# Manutenção e semântica de control plane
python3 tests/workstation_maintenance_semantics_test.py
python3 tests/historical_bootstrap_retirement_test.py
```

Antes de commit:

```bash
git diff --check
```

---

## 8. Repositório público e segredos

O repositório é projetado para poder ser público.

Podem ser versionados:

- código;
- contratos;
- documentação;
- templates;
- configurações LAB não sensíveis;
- exemplos de produção sem credenciais.

Não devem ser versionados:

- passwords;
- tokens;
- API keys;
- chaves privadas;
- PEMs privados;
- `config/production.env` real;
- secrets produtivos;
- backups de credenciais.

O `.gitignore` deve proteger essas classes de arquivos. A configuração real de
produção e sua autoridade pertencem ao ambiente institucional, não ao Git.

---

## 9. Documentação

- `docs/roadmap.md` — incrementos operacionais e estado factual;
- `docs/operations/modes.md` — DEV, LAB e PROD;
- `docs/operations/lab.md` — operação cotidiana do LAB;
- `docs/operations/reconciliation.md` — semântica de plan/apply/rollback;
- `docs/operations/maintenance.md` — check/bootstrap/doctor/repair e aplicação de REARIT-P001;
- `docs/architecture/operational-model.md` — modelo operacional;
- `docs/architecture/DATA_PLANE.md` — fronteira do plano de dados.

Estado atual do roadmap:

```text
OPS-00    DONE
OPS-01    DONE
OPS-02    DONE
OPS-03    DONE
OPS-04    DONE
OPS-05    DONE
OPS-06    DONE
OPS-07A0  DONE
OPS-07A1  DONE
OPS-07    NEXT (PLANNED)
```

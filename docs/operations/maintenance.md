# SisTer Infra — Manutenção Reflexiva

## 1. Princípio aplicado

Esta fronteira operacional constitui a primeira aplicação explícita, no
`sister-infra`, de:

```text
REARIT-P001@0.1.0
Princípio da Manutenção Reflexiva Automatizável
```

A fonte normativa do princípio pertence ao Registro Evolutivo REA/RIT do
SisTer. Este documento registra apenas sua aplicação operacional no
`sister-infra`; não replica nem redefine o princípio.

## 2. Fronteira semântica

```text
check
  = observar invariantes locais
  = read-only

bootstrap
  = materializar pré-condições ausentes e deriváveis
  = idempotente
  = fail-closed diante de divergência

doctor
  = diagnóstico amplo
  = read-only

repair
  = introduzido e fechado em OPS-07A3
  = correção mínima de drift factual comprovado e autorizado sob a release current
  = opera sob o ciclo estrito: OBSERVE -> COMPARE -> EXPLAIN -> AUTHORITY -> MINIMAL ACT -> VERIFY -> EVIDENCE
  = nunca é um alias para reexecutar bootstrap
```

Regra central:

```text
bootstrap != repair

ausência conhecida e derivável
        -> bootstrap

estado existente divergente
        -> não sobrescrever
        -> exigir diagnóstico/repair autorizado
```

## 3. Invariantes OPS-07A0

### MNT-001 — Observação não materializa

`check` e `doctor` não podem criar diretórios, corrigir permissões, instalar
unidades, trocar links, iniciar processos ou alterar configuração.

### MNT-002 — Bootstrap é limitado

`bootstrap` só materializa pré-condições locais cuja necessidade é derivável da
própria workstation:

- install root;
- releases;
- candidates;
- config root;
- state root;
- systemd user root;
- bin root.

### MNT-003 — Preflight antes da mutação

Antes de criar qualquer diretório, `bootstrap` exige ausência de colisões em
que um path requerido exista com tipo incompatível.

Composition, deployment, installation policy e TLS não são materializados,
copiados nem sobrescritos pelo bootstrap. Sua ausência não impede preparação
do layout; comandos dependentes falham fechado depois.

Falha de preflight não pode deixar materialização parcial.

### MNT-004 — Idempotência

Após convergência, nova execução de `bootstrap` deve resultar em `NO_OP`.

### MNT-005 — Não sobrescrever divergência

Um objeto existente incompatível com a intenção não é tratado como ausência.
`bootstrap` falha fechado em vez de substituí-lo.

### MNT-006 — Conhecimento derivado não é duplicado

A fronteira de manutenção não conhece participantes concretos, portas ou hosts.
Esses dados continuam pertencendo às declarações e aos contratos autoritativos.

### MNT-007 — Installation authority externa

Todos os paths operacionais de composition/deployment são resolvidos por
`sister-authority`. O source tree pode conter exemplos, mas nunca é fallback.

### MNT-008 — Contrato de canais e pureza JSON

A CLI do control plane preserva separação estrita de canais:

- Em invocação normal:
  - `stdout`: resultado operacional formal do comando;
  - `stderr`: diagnóstico, progresso e logs.
- Em invocação com `--json`:
  - `stdout`: exatamente um único documento JSON válido;
  - `stderr`: diagnóstico, progresso e logs permitidos.

Funções auxiliares (`materialize_layout`, `layout_check`, checagens de
integridade) e materializadores intermediários nunca poluem `stdout`.

## 4. Relação com o bootstrap histórico

`setup_sister_infra.sh` representava a genealogia da primeira implantação do
harness. OPS-07A1 comprovou que ele não possuía consumidores operacionais, que
seu material TLS legado estava expirado e que a autoridade TLS corrente pertence
ao control plane da workstation.

O script foi, portanto, retirado da árvore operacional corrente. Sua genealogia
permanece integralmente preservada pelo histórico Git, sem manter uma segunda
implementação de componentes, portas, hosts, templates ou lifecycle.

### 4.1 Aposentadoria do bootstrap top-level (OPS-07A2)

O comando top-level histórico `sister-infra bootstrap` (que executava geração de TLS
e renderização de gateway como uma segunda implementação) foi formalmente aposentado.

O fluxo canônico do control plane agora se divide com clareza em:

1. **Layout Local da Workstation**:
   ```bash
   sister-infra workstation bootstrap
   ```
   Materializa de forma idempotente a árvore de diretórios em `~/.local/share/sister`,
   `~/.config/sister/workstation`, `~/.local/state/sister/workstation` e unidades systemd.

2. **Autoridade CA de Laboratório**:
   ```bash
   sister-infra lab tls status
   sister-infra lab tls init-ca
   ```
   Inspeciona e inicializa explicitamente a raiz de confiança CA local sob exclusão
   mútua e publicação atômica.

3. **Materialização Declarativa e Runtime**:
   ```bash
   sister-infra lab apply
   ```
   Reconcilia componentes, deriva o certificado folha com SANs contratuais e
   atualiza o gateway declarativo com graceful reload.

## 5. Operational Reflexive Repair (OPS-07A3)

Implementado e fechado em **OPS-07A3**, o comando `sister-infra workstation repair`
materializa a manutenção reflexiva sob autoridade formal (`REARIT-P001` e `REARIT-P005`).

O repair **não é bootstrap**:
- `bootstrap`: cria pré-condições locais ausentes;
- `repair`: atua exclusivamente sobre *drift factual comprovado* de um ambiente já instalado.

### 5.1 Ciclo Normativo do Repair

```text
OBSERVE
  ↓
COMPARE
  ↓
EXPLAIN
  ↓
AUTHORITY
  ↓
MINIMAL ACT
  ↓
VERIFY
  ↓
EVIDENCE
```

### 5.2 Escopo de Repair Autorizado

1. **Symlinks Locais Deriváveis e Comprováveis**:
   - `$BIN_ROOT/sister-infra` (`CLI_LINK`) apontando para `$CURRENT_LINK/components/sister-infra/bin/sister-infra`.
2. **Permissões de Runtime**:
   - `0600` em `$CONFIG_ROOT/runtime.env`, chaves privadas e certificados PEM;
   - `0644` em `$SYSTEMD_USER_ROOT/$UNIT_NAME` e certificados de autoridade CA;
   - `0700` em `$CONFIG_ROOT/tls` e restrição a `0700` em diretórios de runtime (`config`, `state`, `run`, `components`) com permissões inseguras (escrita global / `0777`).
3. **Unit Systemd Derivável**:
   - Renderização determinística de `$UNIT_FILE` a partir do template `$CURRENT_LINK/components/sister-infra/templates/systemd/sister-workstation.service.in` e disparo de `systemctl --user daemon-reload`.
4. **Processo Gerenciado Parado**:
   - Reinicialização seletiva via entrypoint (`start` seguido de `health`) de participante da release corrente parado, desde que sua porta esteja livre e seu estado persistente íntegro.
5. **Gateway Gerenciado Parado**:
   - Inicialização do gateway HAProxy pelo adapter privado de runtime da release
     quando parado, desde que sua porta esteja livre e sua autoridade TLS e
     configuração sejam válidas e íntegras.

### 5.3 Salvaguardas Estritas de FAIL-CLOSED

O repair recusa qualquer mutação e falha fechado (código 1) nos seguintes casos:
- `RELEASE_CORRUPTED`: release instalada com arquivos modificados, evidência ausente, hash divergente ou git dirty;
- `PORT_COLLISION_EXTERNAL`: porta de participante ou de gateway ocupada por processo externo não gerenciado;
- `TLS_AUTHORITY_INVALID`: autoridade CA de laboratório ou certificado folha ausente, ilegível, expirado ou não validado (repair **nunca** emite ou rotaciona CA);
- `PERSISTENT_DATA_CORRUPTED`: caminho de dados persistentes inexistente como diretório;
- `DEPLOYMENT_DIVERGENT`: deployment resolvido da release divergente ou corrompido;
- `CURRENT_RELEASE_MISSING`: ausência de release instalada em `current` (repair nunca adivinha ou troca versões).

### 5.4 Contrato da CLI e Evidência Estruturada

```bash
sister-infra workstation repair [--plan|--dry-run] [--json]
```

- **Modo `--plan` / `--dry-run`**:
  Diagnostica todo o drift, explica as divergências observadas e emite o plano de mínima ação sem aplicar qualquer mutação. Retorna 0.
- **Idempotência (`NO_OP`)**:
  Executar `repair` em um sistema saudável produz status `NO_OP` com 0 ações aplicadas. Retorna 0.
- **Evidência JSON (`--json`)**:
  Emite estritamente um documento JSON no stdout com schema `sister.infra.workstation.repair/1.0.0`:
  ```json
  {
    "schema": "sister.infra.workstation.repair/1.0.0",
    "status": "REPAIRED",
    "release_id": "wr-...",
    "plan": [
      {
        "category": "symlink",
        "resource": ".../sister-infra",
        "divergence": "symlink ausente",
        "expected": "...",
        "actual": "absent",
        "action": "atualizar symlink ..."
      }
    ],
    "actions_applied": [ ... ],
    "verification": {
      "status": "PASS",
      "details": "todas as verificações pós-repair passaram com sucesso"
    }
  }
  ```

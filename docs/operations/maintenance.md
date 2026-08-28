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
  = NÃO pertence ao OPS-07A0
  = trabalho futuro a ser tratado em incremento posterior
  = correção mínima de drift comprovado e autorizado (não é reexecutar bootstrap)
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

Antes de criar qualquer diretório, `bootstrap` exige:

- control plane acessível;
- composição canônica presente;
- deployment canônico presente;
- ausência de colisões em que um path requerido exista com tipo incompatível.

Falha de preflight não pode deixar materialização parcial.

### MNT-004 — Idempotência

Após convergência, nova execução de `bootstrap` deve resultar em `NO_OP`.

### MNT-005 — Não sobrescrever divergência

Um objeto existente incompatível com a intenção não é tratado como ausência.
`bootstrap` falha fechado em vez de substituí-lo.

### MNT-006 — Conhecimento derivado não é duplicado

A fronteira de manutenção não conhece participantes concretos, portas ou hosts.
Esses dados continuam pertencendo às declarações e aos contratos autoritativos.

### MNT-007 — Contrato de canais e pureza JSON

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

## 5. Próximo passo

Somente após `check`, `bootstrap` e `doctor` possuírem semântica comprovada,
`repair` deve ser introduzido.

`repair` deverá:

```text
OBSERVE
COMPARE
EXPLAIN
AUTHORITY
MINIMAL ACT
VERIFY
EVIDENCE
```

e nunca ser um alias para “reexecutar bootstrap”.

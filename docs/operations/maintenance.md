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
  = correção mínima de drift comprovado e autorizado
  = planejado após estabilização desta fronteira
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

## 4. Relação com o bootstrap histórico

`setup_sister_infra.sh` representa a genealogia da primeira implantação do
harness. Ele não é referenciado pela superfície operacional atual e contém uma
segunda representação histórica de componentes, portas, hosts e templates.

OPS-07A0 não o moderniza como nova implementação concorrente.

Após a comprovação desta fronteira, o incremento seguinte deve retirar o script
histórico da árvore operacional corrente, preservando sua genealogia no Git.

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

# SisTer Infra — Modos Operacionais

## 1. Visão geral

DEV, LAB e PROD não representam três produtos independentes.

Representam contextos diferentes de:

- autoridade;
- materialização;
- isolamento;
- risco;
- persistência;
- publicação.

O mesmo modelo declarativo deve atravessar os três contextos.

```text
COMPOSITION
    ↓
CANDIDATE
    ↓
DEPLOYMENT
    ↓
PLAN
    ↓
APPLY
```

O que muda entre os modos são as políticas e materializações permitidas.

## 2. DEV

### Objetivo

Permitir trabalhar em um componente sem alterar o ambiente operacional
instalado.

Experiência desejada:

```bash
sister-infra dev preview atmos
```

Semântica pretendida:

> Quero observar Atmos integrado ao SisTer em um ambiente temporário e
> isolado, sem modificar meu LAB instalado.

Propriedades desejadas:

- build isolado;
- portas isoladas;
- runtime temporário;
- sem alteração de `current`;
- sem alteração de `previous`;
- sem restart do LAB;
- gateway opcional;
- descarte explícito ao final.

### Estado atual

**PLANEJADO.**

O comando:

```bash
sister-infra dev preview <component>
```

ainda não constitui interface operacional disponível.

## 3. LAB

### Objetivo

Executar o ambiente cotidiano compartilhado de desenvolvimento integrado e uso
experimental.

Experiência:

```bash
sister-infra lab plan ...
sister-infra lab apply ...
```

O LAB deve convergir incrementalmente para o estado desejado, preservando os
participantes classificados como `KEEP`.

Exemplo:

```text
CURRENT
sister
nexo
urt

DESIRED
sister
nexo
urt
atmos

PLAN
sister  KEEP
nexo    KEEP
urt     KEEP
atmos   ADD
```

O resultado desejado é adicionar Atmos sem reiniciar SisTer, Nexo ou URT,
salvo quando uma dependência material real tornar isso necessário.

### Estado atual

`lab plan` está disponível e consolidado.

`lab apply` está disponível no ambiente LAB com as seguintes capacidades
efetivamente comprovadas:

- `KEEP` forte (PIDs e processos preservados);
- `UPDATE` no nível do componente;
- `REPAIR` de drift factual;
- `ADD` de novos participantes;
- `REMOVE` com preservação de dados persistentes;
- releases imutáveis (`OLD_RELEASE` byte-identical);
- rollback transacional integrado em ordem inversa;
- lifecycle lock compartilhado (`workstation-lifecycle.lock`);
- atomic release switch (`release-switch`);
- atomic ecosystem projection refresh (`tmp + rename(2)`);
- graceful gateway reload (`-sf`) com rollback sobre processo ativo;
- reconciliação controlada do leaf quando a publicação do gateway/SANs exigir, preservando a CA;
- probes de runtime e gateway independentes de proxy ambiental.

Consultar `docs/roadmap.md` para o histórico e detalhes dos incrementos.

## 4. PROD

### Objetivo

Implantar o ecossistema em ambiente produtivo governado.

Experiência desejada:

```text
production plan
production preflight
production apply
production verify
```

ou interface institucional equivalente.

Produção deve introduzir políticas mais rigorosas para:

- credenciais;
- DNS;
- TLS;
- secrets;
- autorização;
- observabilidade;
- rollback;
- evidências;
- auditoria.

### Estado atual

**PLANEJADO como interface operacional reconciliada.**

Existem mecanismos de profile `production` no harness histórico, porém eles
não devem ser confundidos automaticamente com a interface final desejada de
`production apply`.

## 5. Comparação

| Modo | Intenção | Perturba LAB | Estado |
|---|---|---:|---|
| DEV | testar componente isoladamente | não | planejado (NEXT) |
| LAB plan | observar diferença | não | disponível |
| LAB apply | convergir incrementalmente | somente o necessário | disponível (OPS-03/OPS-04) |
| PROD reconciliado | implantação governada | não se aplica | planejado |

## 6. Regra de autoridade

Um modo operacional define não apenas *onde* executar uma operação, mas também
*quais decisões aquela operação está autorizada a tomar*.

Assim:

```text
modo
  ≠
atalho de CLI

modo
  =
contexto de autoridade
+
política de materialização
```

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

Experiência disponível:

```bash
sister-infra dev preview <component>
```

Semântica:

> Quero executar temporariamente um componente em desenvolvimento, em ambiente
> isolado, sem modificar meu LAB instalado.

DEV Preview não representa uma release efêmera nem um mini-LAB.

```text
DEV Preview
    =
sessão temporária de desenvolvimento
de um componente que declara runtime operacional
```

A aplicabilidade decorre da natureza operacional declarada pelo componente:

```text
componente com runtime
        → dev preview

componente sem runtime
        → qualify/test
```

Propriedades efetivamente comprovadas:

- descoberta normativa via `.sister/component.json`;
- binding DEV autoritativo via `sister-deployment`;
- sandbox efêmera;
- portas dinâmicas com retry;
- runtime temporário;
- suporte explícito a source dirty restrito ao DEV Preview;
- evidência `source.clean=false` quando aplicável;
- sem alteração de `current`;
- sem alteração de `previous`;
- sem restart ou perturbação do LAB;
- lifecycle e health contratuais;
- cleanup scoped;
- zero resíduos após encerramento.

### Estado atual

**DISPONÍVEL (OPS-05).**

## 3. LAB

### Objetivo

Executar o ambiente cotidiano compartilhado de desenvolvimento integrado e uso
experimental.

Experiência disponível:

```bash
sister-infra lab plan
sister-infra lab apply
```

A UX LAB resolve automaticamente o desired state a partir das declarações
canônicas versionadas no control plane:

```text
config/compositions/workstation.json
config/deployments/workstation-lab.json
```

Argumentos `--desired-candidate` e `--desired-deployment` permanecem disponíveis
como overrides explícitos e retrocompatíveis.

O `sister-lab` atua apenas como camada de resolução de UX. O
`sister-reconcile` permanece o motor genérico de comparação e aplicação.

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

`lab plan` e `lab apply` estão disponíveis com UX simplificada (OPS-06),
derivando por padrão composition e deployment canônicos do control plane e
preservando overrides explícitos.

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
| DEV | testar componente isoladamente | não | disponível (OPS-05) |
| LAB plan | observar diferença | não | disponível, UX canônica (OPS-06) |
| LAB apply | convergir incrementalmente | somente o necessário | disponível, UX canônica (OPS-03/OPS-04/OPS-06) |
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

# OPS-10A — Auditoria de contratos executáveis e grafo de chamadas

Estado: **CONCLUÍDO (baseline factual)**  
Data da baseline: **2026-08-28**

## 1. Objetivo

Esta auditoria registra a superfície executável atual do `sister-infra` antes
de qualquer consolidação, extração de módulos ou mudança de topologia.

O objetivo do OPS-10 é fazer com que a equipe operacional administre intenção,
configuração e autoridade, enquanto o control plane administra e explica o
procedimento. A quantidade de arquivos em `bin/` não é um critério de sucesso.

Princípio de chegada:

```text
OPERADOR conhece intenção e autoridade
AUTOMAÇÃO executa e explica o procedimento
AUTORIDADES DE DOMÍNIO implementam cada mecanismo uma vez
```

Esta fase é deliberadamente observacional: nenhum entrypoint foi movido,
removido ou reimplementado.

## 2. Método e limites

A baseline foi derivada de:

- parsers e dispatchers sob `bin/`;
- invocações entre executáveis;
- templates systemd;
- documentação de arquitetura, operação e contratos;
- consumidores presentes em `tests/`.

"Público" nesta auditoria significa que existe consumidor humano, documental
ou de integração que pode legitimamente depender do entrypoint. Referências em
testes não tornam um comando público, mas tornam a mudança incompatível com a
suite atual.

Integrações externas que não estejam versionadas neste repositório são
**desconhecidas**. Por isso, as decisões da seção 7 são candidatas, não
autorizações para remoção.

## 3. Inventário dos contratos executáveis

| Entrypoint | Operações observadas | Consumidores observados | Mutação | Implementações/autoridades chamadas | Contrato de saída e erro | Candidato inicial |
|---|---|---|---|---|---|---|
| `sister-infra` | `up`, `down`, `status`, `verify`, `client-env`, `hosts-line`; dispatch de `dev`, `lab`, `candidate`, `workstation`, `production`, `lifecycle`, `authority` | operador, documentação, testes, link instalado | `up`/`down` | gateway diretamente; demais entrypoints por `exec` | texto; código 2 em falha; subcomandos herdam contratos distintos | `KEEP` como superfície operacional |
| `sister-authority` | `resolve`, `seed-lab` | `sister-infra`, lab, lifecycle, production, workstation, testes, documentação de configuração | `seed-lab` | filesystem/configuração externa | JSON ou paths; falha fechada com código 2 | `PRIVATE` ou ferramenta pública administrativa deliberada |
| `sister-component` | `inspect`, `validate`, `qualify` | operador/documentação, composition, dev, lifecycle, testes | exporta artefatos quando solicitado | contratos, Git e entrypoint do componente | texto/JSON parcial; código 2 em erro de contrato | `KEEP` provável como ferramenta pública de contrato |
| `sister-composition` | `resolve`, `qualify` | operador/documentação de contrato, candidate, lifecycle, workstation, testes | exporta bundles quando solicitado | `sister-component` | texto/JSON | `KEEP` a confirmar pelo contrato de automação |
| `sister-candidate` | `create`, `verify` | `sister-infra`, deployment, lab, lifecycle, reconcile, workstation, testes | `create` materializa candidata | `sister-composition` | texto/JSON; código 1 em falha | `PRIVATE` com forwarding público por `sister-infra`, a confirmar |
| `sister-deployment` | `resolve`, `verify`, `dev-binding` | documentação de contrato, dev, lifecycle, production, reconcile, workstation, testes | grava `--out` quando solicitado | `sister-candidate` | texto/JSON; código 1 em falha | `KEEP` ou API de domínio privada; decisão requer contrato 10B |
| `sister-data-paths` | `show` para classes de dados | operador/documentação de arquitetura, teste | não | configuração e convenções de paths | texto shell; código 2 em uso inválido | `KEEP` provável como ferramenta pública de inspeção |
| `sister-gateway` | `render` | `sister-infra`, reconcile, testes | não; configuração em stdout | deployment resolvido | HAProxy em stdout; diagnóstico em stderr; código 1 | `PRIVATE` |
| `sister-dev` | `preview` | `sister-infra`, lifecycle, testes | processo e sandbox efêmeros | component, deployment e entrypoint do componente | texto/JSON; código 1 | `PRIVATE`, acessível por `sister-infra dev` |
| `sister-lab` | `plan`, `apply`, `tls status`, `tls init-ca` | `sister-infra`, lifecycle, testes, documentação | `apply` e `tls init-ca` | authority, candidate, reconcile, OpenSSL | texto/JSON; código 1/2 conforme falha | `PRIVATE`, acessível por `sister-infra lab` |
| `sister-reconcile` | `plan`, `apply` | lab, lifecycle, production, testes | `apply` materializa e comuta release LAB | candidate, deployment, workstation, gateway e processos dos componentes | texto/JSON; código 1 | `PRIVATE` |
| `sister-production` | `plan`, `apply`, `verify` | `sister-infra`, lifecycle, testes, documentação | `apply` transacional | authority, reconcile, deployment e componentes | texto/JSON versionado em partes; código 1 | `PRIVATE`, acessível por `sister-infra production` |
| `sister-lifecycle` | `plan`, `run`, `status`, `maintain`, `evidence` | `sister-infra`, testes, documentação | `run` e `maintain` | todas as autoridades operacionais principais | texto/JSON; falha estruturada com código 2 | `PRIVATE`, acessível por `sister-infra lifecycle` |
| `sister-workstation` | layout, candidata, release, runtime, systemd, repair, promoção, rollback, status e diagnóstico | `sister-infra`, reconcile, lifecycle, systemd, testes, documentação | várias operações | authority, composition, candidate, deployment, `sister-infra up`, systemd e componentes | predominantemente texto; JSON apenas em operações específicas; código 1 | adapter de integração estável; exposição pública a decidir em 10B |

## 4. Grafo factual de chamadas

As arestas abaixo significam "invoca como processo", não importação de API.

```text
systemd
  └─ sister-workstation runtime-start/runtime-stop

sister-infra
  ├─ sister-gateway
  ├─ sister-dev
  ├─ sister-lab
  ├─ sister-candidate
  ├─ sister-workstation
  ├─ sister-production
  ├─ sister-lifecycle
  └─ sister-authority

sister-lifecycle
  ├─ sister-authority
  ├─ sister-component
  ├─ sister-composition
  ├─ sister-candidate
  ├─ sister-deployment
  ├─ sister-dev
  ├─ sister-lab
  ├─ sister-reconcile
  ├─ sister-workstation
  └─ sister-production

sister-lab
  ├─ sister-authority
  ├─ sister-candidate
  └─ sister-reconcile

sister-production
  ├─ sister-authority
  ├─ sister-deployment
  └─ sister-reconcile

sister-reconcile
  ├─ sister-candidate
  ├─ sister-deployment
  ├─ sister-gateway
  └─ sister-workstation

sister-workstation
  ├─ sister-authority
  ├─ sister-composition
  ├─ sister-candidate
  ├─ sister-deployment
  └─ sister-infra up --profile lan

sister-candidate
  └─ sister-composition

sister-composition
  └─ sister-component

sister-deployment
  └─ sister-candidate

sister-dev
  ├─ sister-component
  └─ sister-deployment
```

### 4.1 Ciclo estrutural observado

Existe um ciclo executável explícito:

```text
sister-infra workstation ...
  → sister-workstation
      → sister-infra up --profile lan
```

O serviço systemd entra no mesmo caminho por `sister-workstation
runtime-start`. Isso faz o adapter de workstation depender novamente da fachada
pública e transfere para `sister-infra` a implementação concreta do gateway.

### 4.2 Concentração de orquestração

`sister-lifecycle` conhece dez entrypoints. Isso está de acordo com sua função
de orquestrador, mas hoje o acoplamento ocorre por paths de executáveis e
contratos de stdout/stderr, não por interfaces importáveis e versionadas.

## 5. Operações concorrentes ou sobrepostas

Esta seção identifica rotas que podem representar a mesma intenção do operador
ou compartilhar mecanismos. A auditoria não afirma que suas implementações são
semanticamente idênticas.

### 5.1 Produção

```text
sister-infra up --profile production
sister-infra production apply
sister-infra lifecycle run --target production
```

O primeiro caminho inicia diretamente o gateway e executa um preflight próprio.
Os demais atravessam o adaptador governado de produção. Um operador possui,
portanto, mais de uma entrada mutável rotulada como produção, com gates e
evidências diferentes.

### 5.2 LAB e runtime da workstation

```text
sister-infra up --profile lan
sister-infra lab apply
sister-infra lifecycle run --target lab
sister-infra workstation runtime-start
systemd → sister-workstation runtime-start
```

Esses caminhos ocupam camadas diferentes, mas são expostos como maneiras de
materializar ou iniciar a instalação cotidiana. A fronteira entre reconciliação
de desired state e controle do processo instalado não está expressa na UX.

### 5.3 Candidata e release

Há materialização coordenada por `sister-candidate`, `sister-workstation`,
`sister-reconcile` e `sister-lifecycle`. A decisão 10B deve distinguir claramente:

- criação de candidata de software;
- criação de release instalada;
- comutação atômica da release;
- promoção governada entre ambientes.

### 5.4 Verificação e status

`sister-infra`, `sister-workstation`, `sister-production`, `sister-lifecycle` e
`sister-reconcile` possuem observações ou verificações parciais. Não há contrato
único que informe ao operador quais camadas foram verificadas e quais não foram.

## 6. Estado e autoridades observados

| Classe de estado | Leitores/escritores principais | Observação |
|---|---|---|
| installation authority | authority, lab, production, lifecycle, workstation | OPS-09 centralizou resolução, mas os consumidores ainda a invocam separadamente |
| candidata/composição | component, composition, candidate, workstation, lifecycle | produção e LAB dependem da mesma cadeia de identidade |
| deployment resolvido | deployment, reconcile, gateway, infra, workstation | gateway e verificações consomem o artefato por paths/environment |
| releases/current/previous | workstation, reconcile, production, lifecycle | mutação distribuída entre adapters e orquestradores |
| processo dos componentes | workstation, reconcile, production, lifecycle | chamadas são feitas aos entrypoints dos próprios componentes |
| gateway/HAProxy | infra, gateway, workstation, reconcile, production | renderização é separada; start/stop e verificação permanecem na fachada `sister-infra` |
| evidências | lifecycle, production, reconcile, workstation | formatos e localização não formam ainda um único contrato operacional |

## 7. Classificação preliminar

Nenhuma classificação abaixo autoriza mudança antes do contrato OPS-10B.

### KEEP provável

- `sister-infra`: superfície operacional principal;
- `sister-component`: ferramenta pública de inspeção/qualificação de contrato;
- `sister-data-paths`: ferramenta pública de inspeção sem mutação.

### Decisão dependente do OPS-10B

- `sister-composition` e `sister-deployment`: possuem documentação de contrato e
  valor possível para automações especializadas;
- `sister-workstation`: é simultaneamente interface operacional, engine extenso
  e contrato de integração do systemd;
- `sister-authority`: pode permanecer como ferramenta administrativa avançada,
  ainda que operações normais passem por `sister-infra`.

### PRIVATE provável com forwarding pela fachada

- `sister-dev`;
- `sister-lab`;
- `sister-gateway`;
- `sister-reconcile`;
- `sister-production`;
- `sister-lifecycle`.

### REMOVE

Nenhum candidato factual nesta baseline. Todos os executáveis possuem ao menos
um consumidor versionado.

## 8. Lacunas contratuais encontradas

1. **Produção possui entrada mutável histórica fora do fluxo plan/apply.**
2. **Há ciclo entre fachada e workstation.**
3. **systemd depende de um script que também concentra implementação extensa.**
4. **Códigos de saída não são uniformes:** falhas de contrato usam 1 ou 2
   conforme o entrypoint.
5. **JSON não é universal nem uniformemente puro:** alguns comandos não o
   oferecem; outros imprimem erros estruturados em stdout; outros usam stderr.
6. **Schemas de sucesso, erro e evidência não são uniformemente versionados.**
7. **Paths em `bin/` funcionam como API interna:** orquestradores constroem paths
   absolutos para outros executáveis.
8. **Status e verify não declaram cobertura:** o nome não revela se foram
   observados release, processos, gateway, TLS, autoridade e evidências.
9. **Não existe uma política única de depreciação e forwarding.**
10. **A fronteira de idempotência e locking não cobre claramente todas as
    mutações possíveis**, embora workstation e LAB já possuam locks locais.

## 9. Decisões requeridas no OPS-10B

O contrato de operador e automação deve responder, antes de extrações:

1. Qual é a superfície cotidiana mínima para DEV, LAB e produção?
2. Quais ferramentas de contrato são públicas e versionadas separadamente?
3. Qual comando é dono de cada mutação?
4. Qual diferença pública existe entre `apply`, `run`, `start` e `promote`?
5. Qual interface estável o systemd deve invocar?
6. Quais comandos aceitam execução não interativa e `--json` puro?
7. Quais schemas, exit codes e canais stdout/stderr são garantidos?
8. Como plan/digest/approval/apply preservam identidade ponta a ponta?
9. Qual lock serializa mutações por instalação?
10. Como retry, resume e rollback são reportados após falha parcial?

## 10. Gates da próxima fase

O OPS-10B somente estará concluído quando existir um contrato versionado que
defina:

- comandos públicos e consumidores suportados;
- operações read-only versus mutáveis;
- um dono canônico para cada mutação;
- schemas de sucesso, erro, plano e evidência;
- semântica de exit codes e stdout/stderr;
- integridade plan/apply;
- serialização, idempotência e recuperação;
- política KEEP/FORWARD/DEPRECATE/PRIVATE/REMOVE por entrypoint.

Somente depois desses gates será permitido remover caminhos históricos ou mover
executáveis para fora de `bin/`.

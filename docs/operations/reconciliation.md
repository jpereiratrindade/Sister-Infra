# SisTer Infra — Reconciliação Declarativa

## 1. Objetivo

A reconciliação transforma a diferença entre estado atual e estado desejado em
um plano explicável e, quando autorizado, em uma transformação operacional
mínima.

```text
CURRENT
   ↕
DESIRED
   ↓
PLAN
   ↓
APPLY
   ↓
VERIFY
```

No LAB:

```text
CURRENT
  = release instalada + estado factual observado

DESIRED
  = composition + deployment canônicos do control plane
```

A camada `sister-lab` resolve a UX. O motor `sister-reconcile` permanece
genérico e continua recebendo candidata + deployment explicitamente.

## 2. Plan

`plan` é observacional.

UX canônica:

```bash
sister-infra lab plan
```

Por padrão:

```text
composition
  → ~/.config/sister/workstation/composition.json

deployment
  → ~/.config/sister/workstation/deployment.json
```

Overrides explícitos continuam válidos:

```bash
sister-infra lab plan \
  --desired-candidate <candidate> \
  --desired-deployment <deployment>
```

O plan pode:

- ler manifests;
- verificar candidatas;
- resolver ou verificar deployments;
- observar runtimes;
- comparar estado;
- produzir `reason`s.

Ele não deve:

- iniciar processos;
- parar processos;
- trocar releases;
- alterar links;
- recarregar gateway;
- reemitir certificados;
- atualizar projeções persistentes.

Uma candidata derivada implicitamente pela UX LAB é efêmera e deve ser removida
ao final, inclusive em falha.

Saída conceitual:

```text
COMPONENT    CURRENT    DESIRED    ACTION    REASON

sister       A          A          KEEP      unchanged and healthy
nexo         B          B          KEEP      unchanged and healthy
urt          C          D          UPDATE    desired commit differs
```

## 3. Apply

`apply` constitui autorização explícita para executar o change-set permitido
pelo modo operacional.

UX canônica:

```bash
sister-infra lab apply
```

Override avançado:

```bash
sister-infra lab apply \
  --desired-candidate <candidate> \
  --desired-deployment <deployment>
```

O apply recalcula o estado factual imediatamente antes da transformação.

```text
LOCK
 ↓
OBSERVE
 ↓
PLAN
 ↓
PREFLIGHT / AUTHORITY
 ↓
MATERIALIZE TARGET_RELEASE
 ↓
ACT
 ↓
VERIFY
 ↓
COMMIT
 ↓
FINAL VERIFY
```

O `sister-reconcile` não conhece os paths canônicos da workstation. Essa
resolução pertence à camada de UX `sister-lab`.

## 4. Idempotência

Se o estado desejado já coincide com o estado atual factual:

```text
4 KEEP
0 ADD
0 UPDATE
0 REMOVE
0 RECONFIGURE
0 REPAIR
```

o resultado deve ser:

```text
NO_OP
```

e nenhum processo deve ser perturbado.

## 5. Drift

O manifesto por si só não é prova suficiente da saúde do runtime.

Exemplo:

```text
DECLARED CURRENT
beta commit B
runtime esperado 127.0.0.1:9001

ACTUAL
porta 9001 fechada
```

Se o desired também é `beta commit B`, a ação apropriada é:

```text
REPAIR
```

e não `KEEP`.

## 6. Recursos derivados

Além dos componentes participantes, o plano modela explicitamente:

```text
gateway
projection
```

No plano, esses recursos possuem ações e `reason`s próprios.

No deployment LAB institucional, o gateway usa HTTP/IP por portas e não
materializa certificado. TLS continua pertencendo ao adapter produtivo e a
fixtures explícitas que exercitam publicação por host.

O LAB já comprova:

### Gateway HAProxy

- renderização determinística via `sister-gateway render`;
- validação prévia com `haproxy -c`;
- graceful reload via `-sf <pid_old>`;
- rollback gracioso da configuração anterior.

### Ecosystem Projection

- resolução autoritativa do caminho;
- substituição atômica via arquivo temporário + `rename(2)`;
- restauração atômica em rollback.

### Isolamento LAB/PROD

- LAB `ip-ports`: HTTP por IP, sem DNS/CA, runtimes em loopback;
- PROD `host`: HTTPS, DNS e TLS externo obrigatórios;
- produção rejeita `protocol=http` e `exposure=ip-ports` fail-closed.

### Rollback integrado

- ordem inversa;
- zero duplicidade;
- zero resíduos transitórios;
- restauração de participantes e recursos derivados.

## 7. Lock operacional

Transformações concorrentes sobre o lifecycle da workstation não podem executar
simultaneamente.

O domínio de exclusão abrange operações que possam alterar:

- releases;
- `current`;
- `previous`;
- participantes;
- gateway;
- projection;
- TLS derivado.

O lock protege a autoridade operacional sobre o mesmo estado factual, não apenas
arquivos individuais.

## 8. Releases e commit operacional

Mudanças de versão não reescrevem a release corrente.

```text
OLD_RELEASE
    ↓
TARGET_RELEASE
    ↓
ACT + VERIFY
    ↓
release-switch
    ↓
current = TARGET_RELEASE
previous = OLD_RELEASE
```

O `current` é o commit point operacional.

## 9. Rollback

Rollback faz parte da transformação.

Antes do commit operacional:

```text
falha
  ↓
compensar ações executadas
  ↓
restaurar recursos derivados
  ↓
restaurar participantes anteriores
  ↓
preservar current
```

Invariantes:

- ordem inversa;
- ausência de duplicidade;
- releases imutáveis;
- preservação de dados persistentes;
- `KEEP` intocado.

## 10. Probes e proxy ambiental

Health probes do plano de dados local devem observar diretamente o runtime e não
podem ser desviados por `HTTP_PROXY`, `HTTPS_PROXY` ou `ALL_PROXY`.

Isso é especialmente importante em ambientes institucionais.

## 11. Autoridade e modos

`plan` pode calcular diferenças em contextos diferentes, mas `apply` somente
executa modos explicitamente autorizados.

No estado atual:

```text
DEV
  preview efêmero de componente

LAB
  plan + apply reconciliados

PROD
  interface reconciliada ainda planejada (OPS-07)
```

A política de produção não deve ser simulada reutilizando silenciosamente a
autoridade LAB.

## 12. Evidência

Uma operação reflexiva deve ser capaz de responder:

```text
O que foi observado?
O que era desejado?
Qual diferença foi encontrada?
Por que esta ação foi escolhida?
O que foi efetivamente executado?
O que foi verificado depois?
```

Essa sequência constitui a base para evidências operacionais e futuras
authority gates.

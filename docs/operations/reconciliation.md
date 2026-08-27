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

## 2. Plan

`plan` é observacional.

Ele pode:

- ler manifests;
- verificar candidatas;
- resolver ou verificar deployments;
- observar runtimes;
- comparar estado;
- produzir reasons.

Ele não deve:

- iniciar processos;
- parar processos;
- trocar releases;
- alterar links;
- recarregar gateway;
- reemitir certificados;
- atualizar projeções.

No LAB:

```bash
sister-infra lab plan   --desired-candidate <candidate>   --desired-deployment <deployment>
```

Saída conceitual:

```text
COMPONENT    CURRENT    DESIRED    ACTION    REASON

sister       A          A          KEEP      unchanged and healthy
nexo         B          B          KEEP      unchanged and healthy
urt          C          C          KEEP      unchanged and healthy
atmos        -          D          ADD       desired participant absent
```

## 3. Apply

`apply` constitui autorização explícita para executar o change-set permitido
pelo modo operacional.

No LAB:

```bash
sister-infra lab apply   --desired-candidate <candidate>   --desired-deployment <deployment>
```

O apply deve recalcular o estado factual imediatamente antes da transformação.

Conceitualmente:

```text
LOCK
 ↓
OBSERVE
 ↓
PLAN
 ↓
PREFLIGHT / AUTHORITY
 ↓
MATERIALIZE
 ↓
ACT
 ↓
VERIFY
 ↓
COMMIT
 ↓
FINAL VERIFY
```

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

## 6. Recursos derivados (Implementado no LAB)

Além dos componentes participantes, o plano modela explicitamente os
recursos derivados:

```text
gateway       (HAProxy)
projection    (ecosystem_projection.tsv)
```

No plano (`plan`), esses dois recursos são observados, explicados e
possuem ações próprias:

```text
gateway      RECONFIGURE   published route set changed
projection   REFRESH       ecosystem projection changed
```

O certificado TLS leaf LAB, por sua vez, não é modelado como uma ação
independente do plano: sua reconciliação é uma transformação derivada
executada durante o `apply`, quando a publicação do gateway e o conjunto de
hosts/SANs exigem reemissão do certificado.

No `apply`, o OPS-04 implementou e comprovou operacionalmente:

- **HAProxy Gateway**:
  - renderização determinística via `sister-gateway render`;
  - validação sintática prévia com `haproxy -c` antes de qualquer reload;
  - graceful reload via `-sf <pid_old>` preservando conexões ativas;
  - em caso de falha posterior, rollback gracioso restaurando a configuração
    anterior sobre o processo TARGET ativo;
- **Ecosystem Projection**:
  - resolução autoritativa do caminho via `SISTER_ECOSYSTEM_PROJECTION_FILE`,
    configuração de runtime ou convenção padrão (fail-closed se indeterminado);
  - substituição atômica no mesmo filesystem via `tmp + rename(2)`;
  - restauração atômica do conteúdo anterior em caso de rollback;
- **Certificado TLS Leaf LAB**:
  - reconciliação controlada do leaf quando a publicação do gateway/SANs exigir;
  - preservação estrita dos bytes de `CA_CERT` e `CA_KEY` (a rotação da CA é
    fail-closed e exige ação de autoridade explícita, como bootstrap);
  - restauração atômica do leaf anterior na transação em caso de rollback;
- **Rollback Integrado e Invertido**:
  - desfaz todas as etapas de forma rigorosamente inversa (re-comuta links se
    necessário, restaura projeção, recarrega gateway anterior, restaura leaf
    e encerra novos processos), garantindo zero arquivos temporários e zero
    processos ou listeners órfãos.

## 7. Lock operacional

Transformações concorrentes sobre o lifecycle da workstation não devem
executar simultaneamente.

O domínio de exclusão deve abranger operações que possam alterar:

- releases;
- `current`;
- `previous`;
- participantes;
- recursos derivados.

O objetivo não é apenas evitar corrupção de arquivos, mas impedir duas
autoridades operacionais simultâneas sobre o mesmo estado factual.

## 8. Releases e commit operacional

Mudanças de versão não devem reescrever a release corrente.

A sequência correta é:

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

O rollback é parte da transformação, não uma operação improvisada após uma
falha.

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

O rollback deve respeitar:

- ordem inversa;
- ausência de duplicidade;
- releases imutáveis;
- preservação de dados persistentes;
- `KEEP` intocado.

## 10. Probes e proxy ambiental

Health probes sobre o plano de dados local devem observar diretamente o runtime
e não podem ser desviados por configuração ambiental de proxy HTTP/HTTPS.

Isso é particularmente importante em ambientes institucionais nos quais
variáveis como `HTTP_PROXY`, `HTTPS_PROXY` e `ALL_PROXY` podem estar presentes.

## 11. Evidência

Uma operação reflexiva deve ser capaz de responder:

```text
O que foi observado?
O que era desejado?
Qual diferença foi encontrada?
Por que esta ação foi escolhida?
O que foi efetivamente executado?
O que foi verificado depois?
```

Essa sequência constitui a base para evidências operacionais futuras.

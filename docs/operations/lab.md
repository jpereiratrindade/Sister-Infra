# SisTer Infra — Operação LAB

## 1. Objetivo

O LAB é o ambiente operacional cotidiano do ecossistema SisTer.

Ele deve permitir evoluir o conjunto de sistemas disponíveis sem transformar
cada inclusão de participante em uma reinstalação global.

## 2. Observar o estado atual

```bash
sister-infra workstation current
sister-infra workstation status
sister-infra workstation verify
```

## 3. Planejar uma convergência

A forma canônica disponível é:

```bash
sister-infra lab plan
```

Por padrão, a intenção LAB vem da authority externa persistente:

```text
~/.config/sister/workstation/composition.json
~/.config/sister/workstation/deployment.json
```

A resolução central é responsabilidade de `sister-authority`; `sister-lab`
consome esse contexto. O motor
`sister-reconcile` continua recebendo candidata e deployment explicitamente e
permanece genérico.

Para auditoria, testes ou operação avançada, os overrides continuam disponíveis:

```bash
sister-infra lab plan \
  --desired-candidate <candidate-dir> \
  --desired-deployment <deployment.json>
```

O comando é read-only.

Exemplo de estado convergido:

```text
sister   KEEP
nexo     KEEP
praxis   KEEP
urt      KEEP

gateway    KEEP
projection KEEP
```

Nesse caso o resumo esperado é equivalente a:

```text
4 KEEP
0 ADD
0 UPDATE
0 REMOVE
0 RECONFIGURE
0 REPAIR
```

## 4. Aplicar

Após revisar o plano:

```bash
sister-infra lab apply
```

A forma explícita também permanece válida quando o operador precisa substituir
a intenção canônica:

```bash
sister-infra lab apply \
  --desired-candidate <candidate-dir> \
  --desired-deployment <deployment.json>
```

Um estado já convergido deve resultar em:

```text
NO_OP
```

sem alteração de PIDs ou releases.

## 5. Verificação após apply

```bash
sister-infra workstation current
sister-infra workstation verify
```

Para investigação adicional:

```bash
ss -lntp
```

e health probes específicos podem ser usados como evidência auxiliar.

## 6. Rede LAB

Os runtimes gerenciados permanecem, por padrão, atrás da fronteira de
implantação e podem escutar somente em loopback.

Exemplo conceitual:

```text
127.0.0.1:8000
127.0.0.1:8015
127.0.0.1:8093
127.0.0.1:8094
       ↓
    gateway
       ↓
LAN / cliente
```

A publicação externa é responsabilidade do deployment/gateway e não dos
componentes individualmente.

Na instalação LAB institucional, o HAProxy publica frontends HTTP na interface
`10.163.80.176`, usando uma porta por participante. Os endpoints reais
permanecem restritos a `127.0.0.1` e não são expostos diretamente.

## 7. Acesso LAB por IP, sem DNS ou CA

O deployment institucional usa `gateway.protocol=http` e
`gateway.exposure=ip-ports`. O acesso do operador é direto:

```text
http://10.163.80.176:8000  Sister
http://10.163.80.176:8015  Nexo
http://10.163.80.176:8093  Praxis
http://10.163.80.176:8094  URT
http://10.163.80.176:8095  Atmos
```

Não há configuração de `/etc/hosts`, DNS, SNI, certificado leaf ou CA no
caminho operacional do LAB. O gateway continua sendo a única fronteira LAN;
os processos dos participantes não mudam seu binding de loopback.

Os comandos históricos `lab tls status/init-ca` permanecem apenas para
compatibilidade e testes específicos de TLS. Eles não são precondição de
`lab plan`, `lab apply`, cold-start, repair ou verify no deployment ip-ports.

Produção não herda essa política: seu adapter exige domínio, HTTPS, certificado
externo, DNS pronto e verificação criptográfica fail-closed.

## 8. Gateway e projeção (Implementado)

A reconciliação segura de recursos derivados no LAB está implementada e
integrada ao `sister-infra lab apply`.

A sequência operacional factual comprovada no OPS-04 executa:

1. **Ativação e Health Local**: novos participantes (`ADD`) são iniciados em
   `TARGET_RELEASE` e validados localmente antes de qualquer publicação;
2. **Preparação da Publicação**: derivação dos frontends HTTP/IP e portas a
   partir do deployment, sem material TLS;
3. **Validação Sintática do Gateway**: a nova configuração do HAProxy é
   validada previamente (`haproxy -c`) antes de qualquer recarga;
4. **Graceful Gateway Reload**: recarga graciosa do HAProxy (`-sf <pid_old>`),
   assumindo o tráfego sem derrubar conexões existentes;
5. **Verificação de Conectividade via Gateway**: probes HTTP ponta a ponta em
   cada endereço IP/porta publicado;
6. **Atualização Atômica da Projeção**: a `ecosystem_projection.tsv` é
   atualizada via arquivo temporário e `rename(2)` atômico;
7. **Observação do Ecossistema**: verificação factual de que os participantes
   reconhecem a nova projeção;
8. **Parada de Participantes Removidos**: participantes `REMOVE` têm sua
   publicação retirada do gateway e projeção antes do encerramento final do
   daemon (dados em `$STATE_ROOT/components/<cid>` preservados intactos);
9. **Commit Operacional**: `release-switch` comuta `previous` para `OLD_RELEASE`
   e `current` para `TARGET_RELEASE`;
10. **Verificação Final**: validação pós-switch com rollback integral e
    gracioso em ordem inversa caso qualquer etapa falhe.

## 9. O que o LAB não deve exigir

O operador não deve precisar decidir manualmente, a cada alteração:

```text
qual processo parar
qual serviço reiniciar
qual release editar
qual PID matar
qual arquivo do gateway reescrever
```

Essas decisões pertencem ao control plane quando puderem ser derivadas de
contratos e estado factual.

## 10. Interfaces e Modos Disponíveis

Não confundir visão desejada com estado factual:
- **DEV Preview**: disponível desde OPS-05 (`sister-infra dev preview <component>`).
- **LAB Reconciliado**: disponível desde OPS-06 (`sister-infra lab plan/apply`).
- **PROD (Operações Governadas)**: disponível desde OPS-07 (`sister-infra production plan/apply/verify`), operando sob travas institucionais de autoridade, digest selado e verificação rigorosa de DNS/TLS.
- **Lifecycle End-to-End**: orquestrador unificado disponível desde OPS-08 (`sister-infra lifecycle plan/run`).
- **Workstation Repair**: manutenção reflexiva convergente disponível desde OPS-10 (`sister-infra workstation repair`).

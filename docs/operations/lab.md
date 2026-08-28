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

## 7. DNS e TLS de laboratório

Nomes `*.gateway.test`, CA privada de laboratório e certificados leaf dedicados
são ferramentas de desenvolvimento e validação do ambiente LAB.

Eles são resolvidos e roteados no escopo do gateway LAB local (via SNI e
cabeçalho `Host`). A resolução desses nomes nos clientes da LAN continua sendo
uma preocupação de publicação e deployment (por exemplo, configuração de DNS
local ou `/etc/hosts` na LAN), e não do runtime individual dos participantes.

### 7.1 Modelo de Autoridade TLS Convergida (OPS-07A2)

O ciclo de vida TLS do LAB opera sob estrita separação de responsabilidades:

1. **Autoridade CA (Administração Explícita)**:
   A autoridade CA do laboratório é inspecionada e inicializada explicitamente via CLI:
   ```bash
   sister-infra lab tls status [--json]
   sister-infra lab tls init-ca [--json]
   ```
   - O comando `status` é estritamente observacional (read-only em qualquer estado).
   - O comando `init-ca` cria a CA raiz (`ecosystem-lab-ca.crt` e `ecosystem-lab-ca.key`) sob lock de processo (`fcntl.flock`), com publicação atômica do diretório inteiro e permissões seguras (`0700/0600/0644`). É idempotente (`NO_OP`) sobre CA válida e falha fechado (`FAIL-CLOSED`) sobre divergências ou conteúdo preexistente em `tls/`.

2. **Localização Canônica da Autoridade**:
   A única fonte autoritativa de TLS no LAB reside na configuração da workstation:
   ```text
   ~/.config/sister/workstation/tls/
   ├── ecosystem-lab-ca.crt
   ├── ecosystem-lab-ca.key
   └── ecosystem-lab.pem
   ```
   O diretório `<repo>/secrets/` não é autoridade, fallback nem destino operacional.

3. **Emissão e Reconciliação do Leaf**:
   Apenas o reconciliador (`sister-reconcile` / `sister-infra lab apply`) emite ou renova o certificado folha (`ecosystem-lab.pem`), derivando automaticamente os SANs dos hosts publicados no deployment resolvido, preservando inalterada a autoridade CA.

4. **Consumo no Boot de Runtime**:
   O cold-start do gateway (`sister-infra up`) opera exclusivamente como consumidor da autoridade existente. Ele nunca gera, renova ou rotaciona material TLS; caso o `TLS_PEM` necessário esteja ausente ou ilegível, o boot falha fechado imediatamente.

Além disso, mecanismos LAB não constituem substitutos arquiteturais para:

- DNS real;
- certificados publicamente confiáveis;
- domínio produtivo;
- políticas produtivas de credenciais.

Produção deve materializar a mesma intenção declarativa por mecanismos
apropriados ao ambiente.

## 8. Gateway e projeção (Implementado)

A reconciliação segura de recursos derivados no LAB está implementada e
integrada ao `sister-infra lab apply`.

A sequência operacional factual comprovada no OPS-04 executa:

1. **Ativação e Health Local**: novos participantes (`ADD`) são iniciados em
   `TARGET_RELEASE` e validados localmente antes de qualquer publicação;
2. **Preparação TLS**: reconciliação controlada do leaf quando a publicação
   do gateway/SANs exigir, preservando estritamente `CA_CERT` e `CA_KEY`
   (fail-closed se a validade residual da CA exigir renovação);
3. **Validação Sintática do Gateway**: a nova configuração do HAProxy é
   validada previamente (`haproxy -c`) antes de qualquer recarga;
4. **Graceful Gateway Reload**: recarga graciosa do HAProxy (`-sf <pid_old>`),
   assumindo o tráfego sem derrubar conexões existentes;
5. **Verificação de Conectividade via Gateway**: probes HTTPS ponta a ponta
   com verificação de SNI e certificado da CA;
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

## 10. Interface ainda não disponível

Não confundir visão desejada com estado factual.

O DEV Preview já está disponível desde o OPS-05:

```bash
sister-infra dev preview <component>
```

A interface reconciliada de produção ainda permanece no roadmap:

```bash
sister-infra production apply
```

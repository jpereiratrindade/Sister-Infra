# Manual de Operação — Automação do Ciclo de Vida do SisTer (OPS-08)

Este documento descreve a operação, governança e arquitetura do **controlador de ciclo de vida unificado** (`sister-infra lifecycle` e `bin/sister-lifecycle`), introduzido pelo incremento **OPS-08**.

---

## 1. Princípios Arquiteturais e Governança

O ciclo de vida operacional é regido pelas normas evolutivas do SisTer:

- **`REARIT-P001` (Manutenção Reflexiva Automatizável)**: O sistema é capaz de observar suas próprias divergências, planejar a correção estritamente necessária e convergir sem intervenção manual.
- **`REARIT-P002` (Autoridade Não Duplicada — `ORCHESTRATION ≠ DUPLICATION`)**: O controlador de ciclo de vida **não reimplementa** compilação, qualificação, resolução de deployment, reconciliação, repair ou travas criptográficas. Ele unicamente orquestra, encadeia, observa e registra evidências entre as capacidades especializadas existentes.
- **`REARIT-P003` (Transformação Mínima & Genericidade Estática)**: Zero conhecimento embutido de participantes concretos (`urt`, `nexo`, `praxis`, `atmos`) ou portas fixas. Toda a topologia é derivada de contratos declarativos normativos.
- **`REARIT-P004` (Genealogia Operacional & Evidência Rastreável)**: Cada transição de estado emite evidências estruturadas e seladas que respondem factualmente: *Como este artefato chegou a este estado?*
- **`REARIT-P005` (Autonomia Delegada por Fronteiras)**: Execução autônoma dentro das fronteiras autorizadas; falha fechada imediata (`fail-closed`) diante de ambiguidades ou quebra de invariantes.

---

## 2. Diagrama de Fluxo do Ciclo de Vida

```text
               SOURCE CHANGE
                     │
                     ▼
           [ DISCOVER / QUALIFY ]
           (sister-component qualify)
                     │
                     ▼
             [ BUILD / TEST ]
                     │
                     ▼
               [ CANDIDATE ]
          (sister-candidate create)
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
 [ DEV PREVIEW ]             [ LAB PLAN ]
(sister-dev preview)     (sister-reconcile plan)
        │                         │
        ▼                         ▼
    [ VERIFY ]               [ LAB APPLY ]
(gateway/loopback)      (sister-reconcile apply)
                                  │
                                  ▼
                              [ VERIFY ]
                       (sister-workstation verify)
                                  │
                                  ▼
                             [ OBSERVE ]
                                  │
                   ┌──────────────┴──────────────┐
                   │ (drift factual)             │ (íntegro)
                   ▼                             ▼
              [ REPAIR ]                [ PROMOTION EVIDENCE ]
       (sister-workstation repair)      (avaliação de elegibilidade)
                   │                             │
                   └──────────────┬──────────────┘
                                  ▼
                         [ PRODUCTION PLAN ]
                      (sister-production plan)
                                  │ (digest selado SHA-256)
                                  ▼
                        [ AUTHORITY GATES ]
                    (aprovação institucional)
                                  │
                                  ▼
                        [ PRODUCTION APPLY ]
                     (sister-production apply)
                                  │
                                  ▼
                        [ VERIFY / EVIDENCE ]
                     (cadeia de rastreabilidade)
```

---

## 3. Comandos do Controlador (`sister-infra lifecycle`)

O ponto de entrada oficial é `sister-infra lifecycle`:

```bash
./bin/sister-infra lifecycle <comando> [opções]
```

### 3.1. `lifecycle plan` (Estritamente Read-Only)

Projeta deterministicamente os estágios necessários para o alvo desejado (`dev`, `lab`, `production`), sem efetuar qualquer alteração no filesystem.

```bash
# Planejamento para ambiente LAB (padrão)
./bin/sister-infra lifecycle plan --target lab --json

# Planejamento para ambiente DEV
./bin/sister-infra lifecycle plan --target dev --json

# Planejamento para ambiente PROD
./bin/sister-infra lifecycle plan --target production --json
```

**Payload de saída (`sister.infra.lifecycle.plan/1.0.0`)**:
Cada estágio é classificado como:
- `READY`: pré-requisitos satisfeitos; pronto para execução.
- `NEEDED`: execução necessária para atingir o estado desejado.
- `NO_OP`: estado já convergido; nenhuma ação será tomada.
- `BLOCKED`: pré-condição ausente ou inválida (ex.: fontes sujas, declaração faltante).
- `REQUIRES_AUTHORITY`: exige autorização explícita institucional (produção).

### 3.2. `lifecycle run` (Orquestração End-to-End)

Executa de ponta a ponta a sequência de estágios autorizados para o alvo:

```bash
# Executa ciclo DEV com preview efêmero isolado
./bin/sister-infra lifecycle run --target dev --component urt --duration 5

# Executa ciclo LAB (qualifica -> candidata -> reconcilia -> verifica)
./bin/sister-infra lifecycle run --target lab

# Promove a candidata exata comprovada no LAB e executa PRODUCTION real sob autoridade
./bin/sister-infra lifecycle run --target production
```

### 3.3. `lifecycle status` (Observação Read-Only do Ecossistema)

Sintetiza em um único comando o estado factual de todas as camadas operacionais:

```bash
./bin/sister-infra lifecycle status --json
```

Inspeciona:
- `source`: limpo (`QUALIFIED`) ou com alterações pendentes (`DIRTY`).
- `lab`: release ativa e saúde dos serviços declarados.
- `maintenance`: convergido (`CONVERGED`) ou com necessidade de reparo reflexivo (`REPAIR_REQUIRED`).
- `promotion`: elegibilidade formal (`PROMOTABLE` ou `BLOCKED`).
- `production`: prontidão do executor real (`systemd`) ou perfil hermético explicitamente identificado.

### 3.4. `lifecycle maintain` (Manutenção Reflexiva One-Shot)

Composição direta de verificação e reparo operacional reflexivo:

```bash
./bin/sister-infra lifecycle maintain --json
```

- Se o ambiente estiver íntegro: retorna `NO_OP` com `CONVERGED`.
- Se houver drift derivável (symlinks rompidos, permissões incorretas, processo parado com porta livre): delega para `sister-workstation repair`, comuta e pós-verifica.
- Se houver drift fail-closed (release corrompida, colisão externa de portas ou,
  em deployments HTTPS, autoridade TLS ausente): aborta sem mutações perigosas.

### 3.5. `lifecycle evidence` (Cadeia de Evidências Rastreável)

Exibe a cadeia completa de evidências operacionais geradas ao longo do ciclo de vida:

```bash
./bin/sister-infra lifecycle evidence --json
```

Permite navegar entre:
- Qualificações de componentes e composições;
- Manifestos de candidatas imutáveis;
- Registros de reconciliação de LAB;
- Evidências formais de promoção (`promotion evidence`);
- Planos selados e auditorias de produção.

---

## 4. Governança de Promoção: O Princípio `WHAT WAS VERIFIED = WHAT IS PROMOTED`

No SisTer, a promoção de um componente ou ecossistema para produção **não é a cópia manual de arquivos**, nem uma nova compilação silenciosa de fontes.

A promoção avalia:
1. **Identidade Imutável da Candidata**: um digest SHA-256 canônico cobre toda a árvore materializada (paths, tipos, bits executáveis, symlinks e bytes), e deve coincidir exatamente com a evidência LAB.
2. **Evidência de Qualificação**: Todos os componentes passaram formalmente por testes e inspeção de contrato (`PASS`).
3. **Evidência Factual de LAB**: A candidata foi aplicada com sucesso em ambiente LAB e passou integralmente na verificação de saúde e gateway.
4. **Pureza de Código-Fonte**: Tanto a árvore do control plane quanto todos os repositórios de componentes estão 100% limpos (`git status --porcelain` vazio).
5. **Compatibilidade de Deployment**: A candidata resolve deterministicamente contra o deployment de produção declarado.

Quando todos os critérios são satisfeitos, emite-se um documento de evidência selado:
`sister.infra.promotion.evidence/1.0.0` com status `PROMOTABLE`.

---

## 5. Auditoria UX: Antes vs Depois de OPS-08

| Dimensão Operacional | Antes de OPS-08 | Depois de OPS-08 |
| :--- | :--- | :--- |
| **Ponto de Entrada** | Múltiplos binários dispersos (`sister-component`, `sister-composition`, `sister-candidate`, `sister-reconcile`, `sister-workstation`, etc.) | Ponto de entrada unificado: `sister-infra lifecycle` |
| **Encadeamento de Estágios** | O operador precisava rodar manualmente 8 a 10 comandos sequenciais passando paths e hashes | O operador declara apenas a intenção (`--target dev`, `lab` ou `production`) e o motor encadeia |
| **Promoção para Produção** | Procedimento ad-hoc suscetível a descompassos entre o que foi testado no LAB e o que vai para prod | Avaliação formal com evidência selada: a mesma candidata qualificada no LAB é promovida |
| **Manutenção Corretiva** | Decisão manual de quando rodar `verify`, quando rodar `repair --plan` e quando aplicar | Comando único `lifecycle maintain`: observação -> decisão -> reparo mínimo -> pós-verificação |
| **Rastreabilidade** | Arquivos de log e evidências espalhados sem índice genealógico | Cadeia de evidências consolidada e consultável via `lifecycle evidence` |
| **Genericidade** | Comandos dependiam de scripts e parâmetros locais | 100% genérico; zero participantes ou portas codificadas no motor |

---

## 6. Fronteira de Produção Real

Na raiz padrão `/`, `lifecycle run --target production` seleciona `systemd`, exige
autoridade institucional e promove somente o digest exato comprovado no LAB. Falhas
de `daemon-reload`, `start` ou `is-active` encerram o ciclo sem fallback. Em raiz
alternativa, a evidência é marcada `SANDBOX_TEST`; apenas nesse contexto `mock` é aceito.

Cada execução real grava testemunho com hostname, machine-id, boot-id e estado das
units. Esse testemunho comprova onde o `PASS` ocorreu sem transformar testes herméticos
em alegação de implantação institucional.

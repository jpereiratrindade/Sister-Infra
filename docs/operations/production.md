# SisTer Infra — Manual de Operação de Produção (OPS-07)

## 1. Princípio Fundamental

> Produção é o mesmo paradigma declarativo do SisTer submetido a políticas mais estritas de autoridade, isolamento, rastreabilidade e operação institucional.

O ambiente produtivo não cria uma segunda arquitetura de infraestrutura. Preserva-se integralmente a cadeia ontológica de artefatos:

```text
component → composition → candidate → deployment → qualification → plan → reconcile
```

Produção **NÃO** introduz:
- novo formato paralelo de componentes;
- nova composição paralela;
- novo motor reconciliador;
- participantes hardcoded;
- portas hardcoded;
- TLS gerado automaticamente;
- segredos armazenados em Git;
- estado implícito.

> [!IMPORTANT]
> **Fronteira Institucional de Autoridade (PRD-019)**:
> Esta implementação fornece o adaptador de produção, as travas de autoridade e a suíte de testes em sandbox hermético. **A execução ou implantação em servidores de produção reais NÃO FOI EXECUTADA e NÃO É AUTORIZADA POR ESTA MISSÃO**. Qualquer implantação real exige processo formal independente e aprovação corporativa.

---

## 2. Invariantes Arquiteturais (PRD-001 a PRD-019)

| Invariante | Descrição |
| :--- | :--- |
| **PRD-001** | `production plan` é estritamente **read-only** (zero mutações no filesystem, rede ou processos). |
| **PRD-002** | `production apply` jamais executa sem um plano prévio materializado (`--plan <file>` e `--plan-digest <sha256>`). |
| **PRD-003** | O plano aplicado deve ser rigorosamente idêntico ao plano aprovado (selado via digest criptográfico canônico). |
| **PRD-004** | Qualquer divergência factual entre o momento do plan e o momento do apply resulta em **fail-closed** imediato. |
| **PRD-005** | TLS em produção é exclusivamente externo (`TLS_MODE=external`), fornecido pela autoridade institucional. |
| **PRD-006** | Produção nunca gera, renova ou auto-rotaciona certificados. |
| **PRD-007** | Segredos nunca residem em repositórios Git, candidatas ou evidências públicas. |
| **PRD-008** | Control plane ou componentes com fontes não-commitadas (*dirty sources*) falham fechado no preflight. |
| **PRD-009** | A candidata de produção deve estar plenamente qualificada antes da projeção do plano. |
| **PRD-010** | DNS é passivo de verificação institucional de readiness (resolução esperada), jamais administrado pelo SisTer. |
| **PRD-011** | Layout FHS institucional estrito (`/opt/sister`, `/etc/sister`, `/var/lib/sister`, `/run/sister`), isolável via sandbox (`SISTER_PRODUCTION_ROOT`). |
| **PRD-012** | Gerenciador de serviços abstraído via adaptador plugável (`systemd` em produção real, `mock` em testes e sandboxes). |
| **PRD-013** | `production apply` é estritamente transacional, com rollback automático antes do commit point e comutação atômica de symlink. |
| **PRD-014** | Toda mutação produz evidência de auditoria estruturada e sanitizada (isenta de chaves privadas e segredos). |
| **PRD-015** | Execuções consecutivas sobre estado convergido produzem `NO_OP` com 0 ações. |
| **PRD-016** | Ausência de confirmação institucional (`PRODUCTION_APPROVED=YES`, `SISTER_INFRA_PRODUCTION_CONFIRM=YES`, `PRODUCTION_GATE_CMD`) falha fechado. |
| **PRD-017** | Genericidade estática estrita: zero referências a participantes ou portas concretas no código do adaptador. |
| **PRD-018** | Ambientes LAB e Workstation permanecem isolados e intocados pelas operações produtivas. |
| **PRD-019** | Implantação produtiva real requer autorização institucional explícita e independente. |

---

## 3. Layout de Diretórios FHS (Filesystem Hierarchy Standard)

Em conformidade com a política institucional, os recursos são distribuídos segundo a hierarquia FHS sob a raiz `/` (ou sob `$SISTER_PRODUCTION_ROOT` em ambiente de sandbox / teste):

```text
/opt/sister/
  ├── releases/
  │     ├── pr-20260828120000Z-cand-001/
  │     │     ├── components/
  │     │     ├── evidence/
  │     │     └── manifest.json
  │     └── ...
  └── current -> releases/pr-20260828120000Z-cand-001

/etc/sister/
  ├── composition.json
  ├── deployment.json
  ├── policy.json            (opcional; somente política local)
  ├── tls/
  │     ├── ecosystem.crt   (fornecido externamente)
  │     └── ecosystem.key   (600, fornecido externamente)
  └── systemd/              (unidades geradas)

/var/lib/sister/
  ├── state/
  │     └── lock/production.lock
  ├── data/                 (dados persistentes de participantes)
  └── evidence/
        └── production/
              └── audit-20260828120000Z.json

/run/sister/
  ├── pids/
  ├── sockets/
  └── gateway/
```

---

## 4. Ciclo Operacional

### 4.1. Projeção de Plano (`production plan`)

Gera a projeção determinística e o digest SHA-256 selado. Esta operação é estritamente read-only.

```bash
sister-infra production plan \
  --desired-candidate /caminho/para/candidata \
  --desired-deployment /caminho/para/deployment.json \
  --out /var/lib/sister/plans/plan-aprovado.json \
  --json
```

Exemplo de payload selado e digest emitido:
```json
{
  "schema": "sister.infra.production.plan/1.0.0",
  "plan_digest": "sha256:4a8b79f0...",
  "candidate": {
    "candidate_id": "cand-datacenter-001",
    "composition_id": "ecosystem_prod"
  },
  "deployment": {
    "deployment_id": "prod-dc-01",
    "gateway_port": 443,
    "declared_hosts": ["sister.gov.br", "nexo.gov.br", "praxis.gov.br"]
  },
  "actions": [ ... ]
}
```
*(Os `declared_hosts` são derivados automaticamente a partir dos componentes descobertos e do `gateway.domain` institucional, sem configuração manual em bindings)*

### 4.2. Aplicação com Autoridade (`production apply`)

A aplicação exige a passagem do plano materializado e a concordância exata com o digest selado:

```bash
PRODUCTION_APPROVED=YES \
SISTER_INFRA_PRODUCTION_CONFIRM=YES \
sister-infra production apply \
  --plan /var/lib/sister/plans/plan-aprovado.json \
  --plan-digest sha256:4a8b79f0... \
  --json
```

O comando executa:
1. **Verificação de Autoridade**: Valida variáveis e executa `PRODUCTION_GATE_CMD` (se configurado).
2. **Conferência de Digest**: Compara o digest informado com o SHA-256 canônico do plano.
3. **Preflight Rigoroso**:
   - `check_clean_sources`: Control plane e componentes com árvores git 100% limpas.
   - `validate_external_tls`: Certificado institucional válido, data não-expirada, chave privada coincidente e cobertura de todas as SANs declaradas.
   - `check_dns_readiness`: Verificação passiva de que os hostnames declarados apontam para o gateway corporativo.
   - `check_ports_free`: Detecção de colisões externas nas portas ou sockets requeridos.
4. **Verificação de Divergência Factual**: Recalcula o plano contra o estado vivo instantâneo; se divergir do plano selado, aborta fail-closed imediatamente.
5. **Transação Atômica**:
   - Materializa staging em `/opt/sister/releases/.creating-...`;
   - Inicia ou atualiza serviços via `ServiceManagerAdapter`;
   - Executa health probes de confirmação;
   - Se ocorrer falha: dispara rollback automático e restaura versão anterior;
   - Se sucesso: comuta atomicamente o symlink `/opt/sister/current` (commit point);
   - Registra evidência em `/var/lib/sister/evidence/production/audit-<timestamp>.json`.

### 4.3. Verificação de Estado (`production verify`)

Inspeciona o estado atual dos serviços, links, certificados TLS e integridade FHS, com comportamento puramente read-only:

```bash
sister-infra production verify --json
```

---

## 5. Auditoria e Sanitização de Evidências

Toda execução de `production apply` registra evidência estruturada em `/var/lib/sister/evidence/production/`.

As evidências contêm:
- Identificadores de candidata e deployment;
- Digest do plano aprovado;
- Ações aplicadas com timestamps e razões;
- Fingerprint SHA-256 do certificado TLS externo;
- Mapeamentos de DNS verificados;
- Status final (`APPLIED` ou `NO_OP`).

> [!TIP]
> O motor sanitiza integralmente a evidência, garantindo que nenhum bloco de chave privada (`BEGIN PRIVATE KEY`, `BEGIN RSA PRIVATE KEY`) ou segredo confidencial seja gravado no log de auditoria.

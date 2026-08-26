# SisTer Infra — Harness Operacional Declarativo

> O `sister-infra` não decide em código quais sistemas constituem uma workstation. Cada componente se autodescreve e pode ser descoberto, validado e qualificado genericamente; uma composição concreta seleciona participantes sem duplicar identidade; a composição é qualificada como um todo; a workstation materializa commits e artefatos qualificados sem conhecimento prévio dos sistemas concretos; uma implantação declarativa resolve os bindings físicos, e gateway e TLS são derivados dessa implantação. O caminho legado concreto foi removido, restando um único lifecycle operacional declarativo.

---

## 1. Arquitetura Declarativa

```text
component.json
      │
      ▼
sister-component (discover / inspect / qualify)
      │
      ▼
composition.json
      │
      ▼
sister-composition (resolve / qualify / aggregate)
      │
      ▼
workstation candidate (qualified artifacts & commits)
      │
      ▼
deployment.json
      │
      ▼
sister-deployment (resolve bindings & topology)
      │
      ├── runtime bindings (tcp / unix)
      ├── gateway (HAProxy gerado dinamicamente)
      └── TLS/SAN (certificados emitidos sob demanda)
      │
      ▼
sister-workstation (create / install / promote / rollback)
      │
      ▼
release (current / previous)
```

### 1.1 Responsabilidades por Camada

| Camada | Responsabilidade | Contrato |
| :--- | :--- | :--- |
| **Componente** | Autodescrição de identidade, driver de build, testes, artefatos verificados e contrato de runtime (`scripts/runtime.sh`). | `sister.component/1.0.0` |
| **Composição** | Seleção de participantes por referência (`source`) sem duplicar identidade, credenciais, portas ou caminhos. | `sister.infra.composition/1.0.0` |
| **Qualificação** | Checkout isolado, compilação `Release`, execução de suíte de testes e exportação de bundles de artefatos com verificação SHA-256. | `sister.infra.composition.qualified/1` |
| **Candidata** | Materialização imutável do control plane, componentes e artefatos binários qualificados. | `sister.infra.workstation.candidate/1` |
| **Deployment** | Resolução agnóstica de transporte (`tcp`, `unix`), portas de escuta, health probes e virtual hosts de borda. | `sister.infra.deployment/1.0.0` |
| **Gateway & TLS** | Geração dinâmica da configuração do HAProxy e emissão/renovação de certificados com SAN estritamente derivados do deployment resolvido. | `sister.infra.deployment.resolved/1` |
| **Workstation** | Orquestração do lifecycle operacional em escopo de usuário com suporte nativo a promoção atômica e rollback verificado. | `sister.infra.workstation.release/3` |

---

## 2. Como adicionar um novo participante

Adicionar um novo subsistema ou serviço ao ecossistema **não exige qualquer alteração no código do `sister-infra`**. O processo consiste em:

1. **Fornecer `.sister/component.json`** no repositório do componente descrevendo artefatos, testes e runtime:
   ```bash
   ./bin/sister-component inspect /caminho/para/novo-componente
   ./bin/sister-component qualify /caminho/para/novo-componente
   ```
2. **Incluir a fonte** na composição desejada (ex: `config/compositions/workstation.json`):
   ```json
   { "source": "../../../novo-componente" }
   ```
3. **Declarar o binding físico** na implantação (ex: `config/deployments/workstation-lab.json`):
   ```json
   {
     "system_id": "novo_sistema",
     "runtime": { "transport": "tcp", "listen": "127.0.0.1", "port": 8095 },
     "probe": { "health_path": "/health" },
     "gateway": { "host": "novo-gateway.test" }
   }
   ```
4. **Executar os gates genéricos** existentes para materializar e promover a release.

---

## 3. Comandos Operacionais da Workstation

Interface pública unificada sob `sister-infra workstation`:

```bash
# Diagnóstico e planejamento
./bin/sister-infra workstation doctor
./bin/sister-infra workstation plan

# Lifecycle de releases
./bin/sister-infra workstation release-create
./bin/sister-infra workstation install <release-id>
./bin/sister-infra workstation promote <release-id>
./bin/sister-infra workstation rollback
./bin/sister-infra workstation list

# Observabilidade e saúde
./bin/sister-infra workstation current
./bin/sister-infra workstation status
./bin/sister-infra workstation verify
./bin/sister-infra workstation logs
```

### Layout de Diretórios (`user-scope`)

```text
~/.local/share/sister/
├── releases/
│   ├── wr-<timestamp>-<hash>/
│   │   ├── manifest.json
│   │   ├── deployment.resolved.json
│   │   └── components/
│   │       ├── sister-infra/
│   │       └── <componentes>/
├── current  -> releases/wr-...
└── previous -> releases/wr-...

~/.config/sister/workstation/
├── tls/
│   ├── ecosystem-lab-ca.crt
│   └── ecosystem-lab.pem
└── runtime.env

~/.local/state/sister/workstation/
├── control-plane/gateway/
│   ├── haproxy-lan.cfg
│   └── haproxy-lan.pid
└── <componentes>/

~/.config/systemd/user/
└── sister-workstation.service
```

---

## 4. Gateway e TLS Dinâmicos

O HAProxy e os certificados TLS não possuem tabelas estáticas de rotas ou domínios:
- O arquivo de configuração (`haproxy-lan.cfg`) é gerado iterando os participantes que declaram `gateway.host`.
- Os certificados TLS têm os SANs (Subject Alternative Names) derivados automaticamente da lista de hosts do deployment resolvido.
- A rotação preventiva e renovação da CA / certificados são executadas de forma transparente pelo lifecycle do harness.

---

## 5. Suíte de Testes e Gates

A integridade arquitetural é garantida pela suíte completa de testes automatizados:

```bash
# Validadores e resolvedores
python3 tests/component_resolver_test.py
python3 tests/composition_resolver_test.py
python3 tests/composition_qualification_test.py
python3 tests/deployment_resolver_test.py
python3 tests/gateway_renderer_contract_test.py

# Isolamento e integridade
python3 tests/nexo_loopback_boundary_test.py
python3 tests/workstation_composition_candidate_test.py
python3 tests/workstation_declarative_lifecycle_test.py
python3 tests/workstation_unit_renderer_contract_test.py

# Ciclo de vida e contratos operacionais
bash tests/data_plane_contract_test.sh
bash tests/tls_lifecycle_test.sh
```

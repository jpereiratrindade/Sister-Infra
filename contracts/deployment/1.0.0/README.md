# Contrato de deployment 1.0.0

O contrato `sister.infra.deployment/1.0.0` descreve como uma implantação
concreta liga os participantes de uma candidata qualificada à infraestrutura
física e como o gateway único reconcilia a exposição dos sistemas integrados.

A identidade pertence exclusivamente ao `.sister/component.json` de cada participante;
por isso cada binding no deployment referencia apenas `system_id`.

## 1. Exposição declarativa do gateway

O contrato possui duas políticas explícitas, pertencentes ao deployment:

- `gateway.exposure: "host"`: publicação por domínio, obrigatória em produção.
  O operador declara `gateway.domain` e os sistemas recebem subdomínios
  derivados da identidade:
  - Os sistemas integrados são descobertos automaticamente a partir da composição/candidata
  e recebem subdomínios canônicos:
  $$\text{host} = \text{component\_id} \cdot \text{domain}$$
- `gateway.exposure: "ip-ports"`: publicação LAB por HTTP no IP declarado em
  `gateway.listen`; cada porta pública é derivada da porta física do binding.
  Esse modo não usa DNS, SNI, certificado ou CA.

Produção aceita somente `protocol=https` e `exposure=host`. O modo
`ip-ports` é recusado fail-closed pela política produtiva.

### Invariante de Isolamento Estrito (FAIL-CLOSED)
Nenhum sistema integrado deve conter configuração própria de domínio, proxy ou certificado.
Quando `gateway.domain` ou `gateway.exposure=ip-ports` está definido:
- Qualquer tentativa de um binding declarar `gateway`, `host`, `domain`, `proxy`, `certificate` ou `tls`
  falha fechado imediatamente (`DeploymentError`).
- Apenas bindings com parâmetros estritamente físicos de `runtime` e `probe` são aceitos.

## 2. Runtime e Probes

Cada participante da candidata deve receber exatamente um binding:
- `tcp` exige `listen` e `port` (1 a 65535) e proíbe `socket`;
- `unix` exige um `socket` absoluto e proíbe `listen` e `port`.
- `probe.health_path` é dado operacional do binding (ex: `/api/health`).

O resolvedor rejeita participantes ausentes ou desconhecidos, identidades duplicadas e colisões de endpoint TCP.

## 3. Resolução

```bash
./bin/sister-deployment resolve \
  /caminho/para/candidate/manifest.json \
  config/deployments/workstation-lab.json --json
```

Somente candidatas com qualificação `PASS`, deployment `PENDING_BINDINGS` e `composition_id`
compatível podem ser resolvidas. O resultado usa o contrato `sister.infra.deployment.resolved/1`
com o status `READY` e cada participante associado à sua URL pública resolvida no gateway.

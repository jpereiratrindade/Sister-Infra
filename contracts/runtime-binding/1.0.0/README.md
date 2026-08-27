# sister.infra.runtime.binding/1.0.0

Contrato normativo para o **runtime binding efêmero de desenvolvimento (DEV Preview)**.

## 1. Finalidade

Este contrato estabelece o formato explícito e mínimo para fornecer a um runtime
em desenvolvimento suas informações de binding local (`listen`, `port`, `transport`),
sem fingir um deployment operacional de release (`sister.infra.deployment.resolved/1`).

## 2. Diferença para o Deployment de Release

| Propriedade | Release Deployment (`deployment.resolved/1`) | Runtime Binding DEV (`runtime.binding/1.0.0`) |
|---|---|---|
| Ambiente | LAB / PROD | DEV (sessão efêmera) |
| Escopo | Multi-componente (composição inteira) | Componente único em preview |
| Gateway / TLS | Sim (SANs, rotas, certs) | Não (acesso direto em loopback) |
| Autoridade emissora | `sister-deployment resolve` | `sister-deployment dev-binding` |
| Persistência | Registrado na evidência da release imutável | Efêmero na sandbox temporária descartável |

## 3. Compatibilidade com Entrypoints

O schema preserva intencionalmente a projeção estrutural consumida pelos
scripts `runtime.sh`:

- `.components[].component_id`
- `.components[].system_id`
- `.components[].runtime.transport`
- `.components[].runtime.listen`
- `.components[].runtime.port`
- `.components[].probe.health_path` (opcional)

Isso permite interoperabilidade imediata com todos os participantes do ecossistema
sem necessidade de modificar seus entrypoints.

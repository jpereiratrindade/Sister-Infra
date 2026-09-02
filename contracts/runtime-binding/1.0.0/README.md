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

Além do documento JSON, o executor fornece a identidade não sobrescrevível da
sessão por ambiente:

```text
SISTER_RUNTIME_MODE=dev-preview
SISTER_RUNTIME_INSTANCE_ID=<identidade efêmera>
SISTER_RUNTIME_STATE_DIR=<sandbox>/state
SISTER_RUNTIME_RUN_DIR=<sandbox>/run
SISTER_RUNTIME_DATA_DIR=<sandbox>/state/data
SISTER_RUNTIME_CLEANUP_SCOPE=preview-only
```

Um componente `persistent-external` deve derivar desses valores todos os seus
PIDs, logs, bancos, containers, volumes e demais recursos auxiliares. Reutilizar
qualquer recurso do LAB/installed/production viola este contrato. O executor
recusa entrypoints que não comprovem o consumo desses marcadores e verifica a
identidade do processo antes de expor o endpoint do preview.

# sister.infra.composition/2.0.0

Contrato de **seleção declarativa de componentes** para o `sister-infra`, neutro em relação a ambiente de implantação.

## Responsabilidade

A composição declara exclusivamente:

- a identidade da composição (`composition_id`);
- as fontes de componentes que devem participar (`components`).

Exemplo:

```json
{
  "schema": "sister.infra.composition/2.0.0",
  "composition_id": "ecosystem_core",
  "components": [
    {"source": "../sister-alpha"},
    {"source": "../sister-beta"}
  ]
}
```

`source` é resolvido relativamente ao diretório do documento de composição.

## Evolução em relação a 1.0.0

No contrato `1.0.0` legado, a propriedade `deployment_class: workstation` era exigida no documento de composição. No contrato `2.0.0`, essa propriedade foi removida da composição porque propriedades de implantação/ambiente (como workstation, laboratório, servidor, staging ou produção) pertencem exclusivamente ao **deployment** e aos materializadores operacionais, e não à seleção de participantes.

Por se tratar de uma alteração com quebra de schema (remoção de propriedade anteriormente obrigatória com `additionalProperties: false`), a versão principal foi incrementada para `2.0.0`.

## Contratos Derivados

- A resolução de `sister.infra.composition/2.0.0` emite `sister.infra.composition.resolved/2`.
- A qualificação de `sister.infra.composition/2.0.0` emite `sister.infra.composition.qualification/2`.
- Ambas as representações derivadas são estritamente neutras de ambiente (não contêm `deployment_class`).

## Fonte de identidade

A composição **não repete** `component_id`, `system_id`, papel, build, runtime ou contrato semântico. Esses dados são obtidos do descritor autoritativo:

```text
<source>/.sister/component.json
```

Cada fonte é inspecionada e validada por `bin/sister-component`.

## Fora de escopo

Este contrato não declara nem resolve:

- `deployment_class` ou ambiente operacional;
- bindings físicos (TCP ou Unix socket);
- host, porta ou URL pública;
- certificados TLS;
- configuração de gateway ou rotas de proxy;
- health/readiness endpoints;
- hashes de artefatos ou lifecycle de serviço.

Essas responsabilidades pertencem ao contrato de deployment (`sister.infra.deployment/1.0.0`) e aos materializadores de infraestrutura.

## Resolução e Qualificação

```bash
# Resolução
./bin/sister-composition resolve composition.json --json

# Qualificação
./bin/sister-composition qualify composition.json --json
```

A qualificação agrega as evidências individuais de cada componente devolvidas por `sister-component qualify`. A mesma composição qualificada pode ser ligada a múltiplos deployments sem necessidade de requalificação ou alteração dos componentes.

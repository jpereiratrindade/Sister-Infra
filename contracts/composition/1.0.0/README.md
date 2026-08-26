# sister.infra.composition/1.0.0

Contrato mínimo de **seleção de componentes** para uma implantação concreta
gerida pelo `sister-infra`.

## Responsabilidade

A composição declara somente:

- a identidade da composição;
- sua classe de implantação;
- as fontes de componentes que devem participar.

Exemplo:

```json
{
  "schema": "sister.infra.composition/1.0.0",
  "composition_id": "example_workstation",
  "deployment_class": "workstation",
  "components": [
    {"source": "../sister-alpha"},
    {"source": "../sister-beta"}
  ]
}
```

`source` é resolvido relativamente ao diretório do documento de composição.

## Fonte de identidade

A composição **não repete** `component_id`, `system_id`, papel, build, runtime ou
contrato semântico. Esses dados são obtidos do descritor autoritativo:

```text
<source>/.sister/component.json
```

Cada fonte é inspecionada e validada por `bin/sister-component`.

## Fora de escopo em 1.0.0

Este contrato não declara nem resolve:

- binding;
- host ou porta;
- TLS;
- gateway ou rota;
- health/readiness endpoints;
- build, testes ou hashes de artefatos;
- política de admissão;
- lifecycle da workstation.

Essas responsabilidades pertencem a incrementos posteriores.

## Resolução

```bash
./bin/sister-composition resolve composition.json
./bin/sister-composition resolve composition.json --json
```

A resolução verifica:

1. validade do documento de composição;
2. existência e validade de cada componente;
3. recuperação de identidade a partir de `.sister/component.json`;
4. unicidade de `component_id`;
5. unicidade de `system_id`.

Ela não qualifica build nem artefatos. Qualificação de composição pertence ao
incremento seguinte.

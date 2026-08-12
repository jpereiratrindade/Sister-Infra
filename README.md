# sister-infra

Harness operacional externo aos repositórios SisTer e sister-nexo.

## Primeiro uso no laboratório

```bash
./bin/sister-infra bootstrap --profile lan
./bin/sister-infra up --profile lan
```

Depois:

```bash
./bin/sister-infra status --profile lan
./bin/sister-infra verify --profile lan
./bin/sister-infra down --profile lan
```

## Perfis

- `dev`: gateway somente em `127.0.0.1:8443`;
- `lan`: gateway no endereço definido em `config/lan.env`;
- `production`: sempre explícito, exige `config/production.env`, TLS externo,
  gate e dupla autorização.

## TLS de laboratório

No primeiro bootstrap, se existir o certificado já usado pelo SisTer em
`SisTer/.run/gateway`, o sister-infra copia esse material para preservar a CA
já instalada nos clientes. Se ele não existir, uma nova CA de laboratório é
gerada em `secrets/`.

Nunca versione `secrets/` nem `config/production.env`.

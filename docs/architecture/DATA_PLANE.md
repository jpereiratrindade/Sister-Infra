# SisTer Data Plane

## Status

**OPS-002A** define o contrato de persistência do ecossistema SisTer.

Este incremento é deliberadamente **não operacional**:

- não migra bancos existentes;
- não altera containers em execução;
- não cria volumes;
- não cria a raiz de dados;
- não modifica a release instalada;
- não publica DEV ou CANDIDATE pelo gateway.

## Princípio

Código, releases, configuração e dados possuem ciclos de vida distintos:

```text
source      != release
release     != configuration
release     != data
development != candidate
candidate   != operational
```

A persistência deve permanecer fora:

- dos repositórios Git;
- de `releases/<id>`;
- do diretório de build;
- de qualquer worktree descartável.

## Raiz de dados

A raiz lógica é configurada por:

```text
SISTER_DATA_ROOT
```

Na workstation, o valor padrão é:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/sister-data
```

Em uma instalação de servidor poderá ser, por exemplo:

```text
/var/lib/sister
```

A topologia interna não muda quando a raiz física muda.

## Classes de implantação

### development

```text
$SISTER_DATA_ROOT/development/
├── sister/
│   ├── postgres/
│   └── backups/
└── nexo/
    ├── postgres/
    └── backups/
```

Identidade de rede planejada:

```text
http://sister-dev.localhost:18000
http://nexo-dev.localhost:18015
```

DEV é somente local e não deve ser publicado pelo gateway LAN.

### candidate

Cada candidate possui plano de dados próprio:

```text
$SISTER_DATA_ROOT/candidate/<candidate-id>/
├── sister/
│   ├── postgres/
│   └── backups/
└── nexo/
    ├── postgres/
    └── backups/
```

Identidade de rede planejada:

```text
http://sister-candidate.localhost:28000
http://nexo-candidate.localhost:28015
```

CANDIDATE nunca acessa diretamente o banco operacional. Quando forem
necessários dados representativos, eles devem vir de snapshot ou restore
explicitamente criado para aquele candidate.

### operational

```text
$SISTER_DATA_ROOT/operational/
├── sister/
│   ├── postgres/
│   └── backups/
└── nexo/
    ├── postgres/
    └── backups/
```

O caminho operacional permanece estável entre releases de software.

Somente o ambiente operacional é elegível para exposição pelo gateway LAN.

## Situação legada em 2026-08-19

A implantação operacional existente ainda usa recursos Podman com nomes
históricos de desenvolvimento:

```text
container: sister-dev-db
volume:    sister_dev_pgdata

container: sister-nexo-dev-db
volume:    sister_nexo_dev_pgdata
```

Apesar do nome `dev`, esses recursos pertencem ao sistema atualmente em uso.

Neste contrato eles são classificados como:

```text
legacy-operational
```

OPS-002A não move, renomeia, remove ou reutiliza esses recursos.

Nenhum novo ambiente de desenvolvimento pode reutilizar os nomes desses
containers ou volumes.

## Invariantes

1. Dados persistentes nunca vivem dentro de um repositório Git.
2. Dados persistentes nunca vivem dentro de `releases/<id>`.
3. Remover uma release nunca remove dados.
4. DEVELOPMENT e OPERATIONAL nunca compartilham PostgreSQL.
5. CANDIDATE e OPERATIONAL nunca compartilham PostgreSQL.
6. CANDIDATE recebe banco novo ou snapshot restaurado.
7. Promoção de software não implica migração automática de banco.
8. Migrações de schema têm backup, verificação e rollback próprios.
9. DEV e CANDIDATE não são publicados pelo gateway LAN.
10. O runtime instalado não compila código.
11. O caminho físico dos dados é configuração de implantação.
12. Backups não são gravados dentro da árvore de source.

## Migração futura do legado operacional

A transição dos volumes atuais para a nova árvore operacional será um evento
separado e planejado:

```text
legacy-operational
        |
        v
backup consistente
        |
        v
restore isolado
        |
        v
candidate de migração
        |
        v
verificação
        |
        v
janela de manutenção
        |
        v
operational definitivo
```

A release anterior e o backup pré-migração devem permanecer disponíveis até
a aceitação explícita do novo estado.

## Resolvedor de caminhos

`bin/sister-data-paths` somente calcula e imprime caminhos. Ele não cria
diretórios, containers, volumes ou bancos.

Exemplos:

```bash
./bin/sister-data-paths show --class development

./bin/sister-data-paths show \
  --class candidate \
  --candidate-id rc-example

./bin/sister-data-paths show --class operational
```

Saída esperada para development:

```text
deployment_class=development
data_root=/.../sister-data
environment_root=/.../sister-data/development
sister_db_data_dir=/.../sister-data/development/sister/postgres
sister_backup_dir=/.../sister-data/development/sister/backups
nexo_db_data_dir=/.../sister-data/development/nexo/postgres
nexo_backup_dir=/.../sister-data/development/nexo/backups
```

## Próximos incrementos

OPS-002A apenas estabelece o contrato.

A sequência planejada é:

```text
OPS-002A  contrato do plano de dados
OPS-002B  SisTer aceita SISTER_DB_DATA_DIR
OPS-002C  Nexo aceita NEXO_DB_DATA_DIR
OPS-003   DEVELOPMENT isolado
OPS-004   CANDIDATE isolado
OPS-005   snapshot/restore
OPS-006   migração planejada do legacy-operational
OPS-007   promoção e rollback
```

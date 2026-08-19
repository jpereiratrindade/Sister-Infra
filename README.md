
<!-- SISTER-INFRA-AUTHORITY:BEGIN -->
## Fronteira de responsabilidade

`Sister-Infra` é o **harness operacional do ecossistema**. Ele coordena a
execução conjunta dos componentes e é a autoridade operacional para:

- HAProxy e fronteira HTTPS;
- TLS/certificados de borda;
- exposição LAN e preparação de acesso;
- perfis `dev`, `lan` e `production`;
- verificação agregada de SisTer e Nexo;
- gates operacionais antes de qualquer promoção.

Os componentes permanecem autônomos em suas responsabilidades internas:

- **SisTer:** núcleo, contratos, governança, persistência, qualidade e
  reflexividade;
- **Nexo:** domínio Nexo, PostgreSQL próprio, backup, migrações, build, testes,
  API/UI e autenticação própria.

O harness chama interfaces internas estáveis dos componentes; atualmente:

```text
SisTer  -> ./scripts/run_all.sh --profile dev-core -> 127.0.0.1:8000
Nexo    -> ./scripts/run.sh                       -> 127.0.0.1:8015
Infra   -> HAProxy/TLS                            -> :8443
```

Produção nunca é inferida a partir de uma execução de desenvolvimento ou LAN:
ela exige perfil e autorização explícitos.
<!-- SISTER-INFRA-AUTHORITY:END -->

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

<!-- SISTER-INFRA-TLS-LIFECYCLE:BEGIN -->
## Ciclo de vida do TLS de laboratório

A existência dos arquivos TLS não é evidência suficiente de validade. Antes de
reutilizar a cadeia de laboratório, o `sister-infra` verifica:

- validade temporal residual da CA;
- validade temporal residual do certificado do gateway;
- assinatura do certificado pela CA corrente;
- cobertura dos hostnames configurados no SAN, incluindo o Praxis quando
  `PRAXIS_HOST` estiver configurado.

Por padrão, CA e certificado entram em renovação preventiva quando restam menos
de 30 dias de validade. As janelas podem ser ajustadas por
`CA_RENEW_BEFORE_SECONDS` e `TLS_RENEW_BEFORE_SECONDS`.

Quando somente o certificado precisa ser renovado e a chave privada da CA
corrente corresponde à CA instalada, a CA é preservada. Quando a CA precisa ser
rotacionada, ou sua chave privada não permite a reemissão necessária, uma nova
CA é criada e o operador é avisado de que os clientes LAN precisam instalar
novamente `secrets/ecosystem-lab-ca.crt`.

Antes de qualquer rotação, o material existente é copiado para
`.run/gateway/tls-backup/`.

Teste de regressão:

```bash
./tests/tls_lifecycle_test.sh
```
<!-- SISTER-INFRA-TLS-LIFECYCLE:END -->

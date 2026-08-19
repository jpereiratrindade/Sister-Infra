
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

<!-- SISTER-INFRA-OPS001-WORKSTATION:BEGIN -->
## Workstation deployment — OPS-001

O perfil operacional `workstation` separa a árvore de desenvolvimento da
instalação usada diariamente. A interface pública permanece sob `sister-infra`:

```bash
./bin/sister-infra workstation doctor
./bin/sister-infra workstation plan
./bin/sister-infra workstation release-create
./bin/sister-infra workstation install
./bin/sister-infra workstation activate
./bin/sister-infra workstation status
./bin/sister-infra workstation verify
./bin/sister-infra workstation update
./bin/sister-infra workstation rollback
./bin/sister-infra workstation logs
```

Layout user-scope:

```text
~/.local/share/sister/
├── releases/<release-id>/
├── current  -> releases/<release-id>
└── previous -> releases/<release-id>

~/.config/sister/workstation/
├── runtime.env
├── source-workspace
├── tls/
├── nexo.env
└── sister.env

~/.local/state/sister/workstation/
~/.config/systemd/user/sister-workstation.service
~/.local/bin/sister-infra
```

Cada release contém clones locais independentes e destacados nos commits
qualificados de `sister-infra`, `SisTer`, `sister-nexo` e `sister-praxis`.
O manifesto registra esses commits. A verificação recusa uma release se o HEAD
de qualquer componente divergir do manifesto ou se um arquivo rastreado tiver
sido modificado.

`update` cria uma nova release, para o serviço antes da troca de `current`,
promove a nova versão, reinicia e verifica. Falha de saúde provoca rollback
automático. `rollback` oferece a mesma verificação no sentido inverso.

`activate` realiza o primeiro handover: para a execução LAN conhecida na árvore
de desenvolvimento e passa o runtime para `systemd --user`; se a ativação não
ficar saudável, tenta restaurar o runtime anterior.

### Limite explícito do OPS-001

OPS-001 isola **código, configuração de implantação e lifecycle da release**.
O plano de dados ainda segue os contratos atuais dos componentes. Em especial,
os entrypoints existentes podem manter nomes de containers/volumes herdados de
desenvolvimento. A separação física e migração governada de bancos/volumes será
um incremento próprio antes de considerar este modelo candidato a produção.

Produção continua proibida por inferência: `workstation` não é `production`.
<!-- SISTER-INFRA-OPS001-WORKSTATION:END -->

<!-- SISTER-INFRA-OPS001C-BUILD:BEGIN -->
### Build-qualified workstation releases

A partir de OPS-001C, `release-create` não publica apenas clones de código.

A candidata passa por:

1. clone independente dos commits;
2. build `Release` e CTest em caminhos curtos temporários;
3. build final dentro da própria candidata de release;
4. identificação dos artefatos de runtime;
5. SHA-256 dos artefatos no manifesto;
6. validação de integridade antes da publicação.

O `install` seleciona a release e renderiza a unidade, mas não habilita autostart. O `activate` habilita a unidade somente depois de `start + verify` bem-sucedidos. Falha de ativação mantém o autostart desabilitado e tenta restaurar o runtime anterior.

Isso separa explicitamente `build`, `release`, `install` e `activation`.
<!-- SISTER-INFRA-OPS001C-BUILD:END -->

<!-- SISTER-INFRA-OPS001D-RUNTIME:BEGIN -->
### Installed runtime contract

Releases workstation usam `SISTER_INFRA_RUNTIME_MODE=installed`.

Nesse modo, o `sister-infra` não reutiliza os entrypoints de desenvolvimento
para SisTer e Nexo. Cada componente expõe um `scripts/runtime.sh` que inicia
somente artefatos já qualificados pela release.

A separação é intencional:

- desenvolvimento: build, CTest e qualificação;
- release-create: materialização e hashes dos artefatos;
- installed runtime: banco/migrações/readiness + execução dos artefatos;
- activate: handover e verificação;
- autostart: habilitado somente após ativação bem-sucedida.

O installed runtime não pode executar CMake, CTest nem reconstruir imagens.
<!-- SISTER-INFRA-OPS001D-RUNTIME:END -->

# Atualização do Nexo com dados persistentes

Uma correção do Nexo deve chegar ao LAB por uma candidata qualificada e pelo
reconciliador. O checkout do componente não administra a instância instalada.
`sister-nexo/scripts/deploy.sh` é apenas um delegador para `sister-infra lab`.

## Preparação

1. Compile e teste o Nexo e faça commit da alteração. Os testes de equipe e
   MorfoCampo devem usar PostgreSQL descartável, sem consumir `.env` ou
   `NEXO_DATABASE_URL` operacionais. Qualificação não é autorização para gravar
   registros de teste no banco instalado.
2. Identifique o binding factual do banco instalado e mantenha um backup privado
   com `pg_dump --format=custom`, fora do Git. Confira o arquivo com
   `pg_restore --list`. Preserve também o storage externo de uploads.
3. Registre contagens ou hashes das tabelas de negócio e a identidade do
   armazenamento. Sessões e auditoria podem mudar com o uso normal da aplicação;
   não confunda essa atividade com perda de registros de domínio.

## Plano e aplicação

```bash
./bin/sister-infra lab plan --json
./bin/sister-infra lab apply --json
./bin/sister-infra workstation verify
```

Para reutilizar exatamente a candidata revisada, materialize-a com
`sister-candidate create <composition.json> --out <candidate-dir>`
e passe `--desired-candidate <candidate-dir>` a `lab plan` e `lab apply`.

Se reconstruções dos mesmos commits produzirem hashes diferentes nos outros
componentes, não ignore essa diferença no reconciliador. Derive outra candidata
com escopo explícito, reutilizando os bytes e as qualificações originais dos
participantes que devem permanecer em `KEEP`:

```bash
./bin/sister-candidate select \
  --base <candidata-da-release-atual> \
  --qualified <candidate-dir> \
  --component nexo \
  --out <candidate-nexo-only>
./bin/sister-infra lab plan --desired-candidate <candidate-nexo-only> --json
./bin/sister-infra lab apply --desired-candidate <candidate-nexo-only> --json
```

`select` verifica ambas as origens, exige a mesma composição e os mesmos
participantes, recusa sobrescrever diretórios e preserva as evidências de
qualificação e os digests das origens. A candidata derivada altera somente os
componentes selecionados; as candidatas originais permanecem intactas.

Uma mudança exclusiva do Nexo deve resultar em `UPDATE` para `nexo` e `KEEP`
para os demais participantes. Examine mudanças de gateway e projeção conforme
seus motivos factuais. Não aplique remoções, novos bindings de banco ou mudanças
em outros participantes como consequência incidental desta correção.

O runtime instalado continua usando o banco persistente externo da instalação.
Não crie um banco vazio, não importe fixtures e não remova volumes. Uma correção
de SQL sem mudança de esquema deve produzir zero migrações novas.

Depois da troca, confirme saúde em loopback e no gateway, compare os registros
de negócio com a evidência anterior e confira a release/commit efetivamente em
execução. Rollback de aplicação usa a release anterior; não restaure o banco
automaticamente sobre gravações realizadas após o backup.

Participantes preservados em `KEEP` podem continuar executando a release de
origem. O lifecycle resolve o processo que escuta no binding declarado e usa
seu entrypoint original somente quando identidade, commit, artefatos, bytes do
processo e binding equivalem à release atual. Essa verificação preserva a
identidade factual dos processos sem exigir reinício após cada troca de release.

## Observação pelo portal Synth

O portal `sister-synth-poc` observa o participante `sister-nexo` pelo endpoint
HTTP público derivado do deployment, com `/api/health` e marcador `sister-nexo`.
Sua configuração externa e allowlist pertencem ao host do portal; nenhum
endereço dessa instalação deve ser introduzido no motor do Infra.

O redirecionamento `/_sister/open/sister-nexo` exige uma superfície web observada
e destino autorizado. A observação HTTP é `UNVERIFIED` sem prova assinada. O
portal não recebe credenciais PostgreSQL e não administra o runtime do Nexo.
O slot visual legado `nexo` do portal continua reservado a MÉTIS.

Atualizar o portal é uma operação separada da reconciliação LAB: preserve os
participantes já registrados, a configuração externa e o armazenamento SYNTH.

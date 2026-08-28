# OPS-10B — Contrato de operador e automação

Estado: **ACEITO COMO ARQUITETURA-ALVO**  
Versão do contrato: **1.0.0**  
Data: **2026-08-28**

## 1. Resultado operacional

> A equipe administra intenção, configuração e autoridade. O SisTer Infra
> administra e explica o procedimento.

O operador não precisa conhecer a ordem de chamada, os executáveis internos,
HAProxy ou a localização dos engines. Encapsulamento não significa opacidade:
todo procedimento mutável deve ser antecipado por um plano inspecionável e
encerrado por verificação e evidência.

```text
intenção + installation authority
  → plano inspecionável
  → gates de política e aprovação
  → mutação serializada
  → verificação
  → evidência versionada
```

## 2. Superfície operacional suportada

`sister-infra` é a fachada pública para operação de instalações.

```text
sister-infra dev preview

sister-infra lab status
sister-infra lab plan
sister-infra lab apply
sister-infra lab verify
sister-infra lab evidence
sister-infra lab tls status
sister-infra lab tls init-ca

sister-infra production status
sister-infra production plan
sister-infra production apply
sister-infra production verify
sister-infra production evidence

sister-infra lifecycle plan
sister-infra lifecycle run
sister-infra lifecycle status
sister-infra lifecycle maintain
sister-infra lifecycle evidence

sister-infra workstation doctor
sister-infra workstation repair
```

Nem todos os comandos-alvo já existem. A ausência é uma lacuna de
implementação do OPS-10, não autorização para criar procedimentos manuais.

### 2.1 Ferramentas públicas especializadas

Permanecem contratos independentes na versão 1:

- `sister-component`: inspeção, validação e qualificação de componentes;
- `sister-data-paths`: cálculo observacional de paths de dados;
- `sister-composition`: resolução e qualificação declarativa;
- `sister-deployment`: resolução e verificação declarativa.

Essas ferramentas não são caminhos alternativos para operar uma instalação.
São ferramentas de contrato para autores e automações especializadas.

`sister-authority` pode continuar acessível durante OPS-10 como ferramenta
administrativa avançada. Operações cotidianas devem resolver authority pela
fachada e registrar provenance sem exigir sua execução manual.

### 2.2 Entrypoints internos

Os seguintes nomes não constituem contratos públicos independentes de
operação, ainda que permaneçam em `bin/` durante a migração:

- `sister-dev`;
- `sister-lab`;
- `sister-gateway`;
- `sister-reconcile`;
- `sister-production`;
- `sister-lifecycle`;
- partes internas de `sister-candidate` e `sister-workstation`.

Testes internos podem invocá-los enquanto os mecanismos são extraídos. Novas
integrações externas não devem depender desses paths.

## 3. Propriedade das mutações

| Intenção | Entrada pública canônica | Dono do use case | Mecanismo reutilizado |
|---|---|---|---|
| preview DEV efêmero | `dev preview` | DEV | qualificação, binding e processo efêmero |
| inicializar CA LAB | `lab tls init-ca` | política LAB | autoridade TLS |
| materializar intenção LAB | `lab apply` | LAB | candidate, deployment, reconcile, release e gateway |
| aplicar produção | `production apply` | produção | plano selado, authority, reconcile e evidência |
| manutenção reflexiva | `lifecycle maintain` | lifecycle | verify e repair canônicos |
| ciclo até um target | `lifecycle run` | lifecycle | delegação para o dono canônico do target |
| reparar workstation | `workstation repair` | workstation | diagnóstico e mutação mínima do host |
| iniciar/parar serviço instalado | adapter estável de serviço | integração systemd | runtime dos componentes e gateway |

Regras:

1. O dono do use case não reimplementa mecanismos de domínio.
2. `lifecycle run` coordena; ele não possui uma segunda implementação de LAB ou
   produção.
3. Aliases históricos delegam integralmente ou falham com migração acionável.
4. Nenhum alias pode reduzir gates, trocar authority ou produzir evidência
   diferente.

## 4. Semântica dos verbos

| Verbo | Semântica pública |
|---|---|
| `status` | observação rápida do estado atual; não prova conformidade completa |
| `plan` | observação read-only que sela intenção, estado relevante e ações propostas |
| `apply` | aplica exatamente um plano válido sob a política do target |
| `verify` | prova read-only de conformidade e declara explicitamente sua cobertura |
| `evidence` | localiza ou emite registros imutáveis de operações anteriores |
| `run` | orquestra stages e delega cada mutação ao seu dono canônico |
| `start`/`stop` | controle de processo instalado; não reconciliam desired state |
| `promote` | decisão de levar identidade já verificada a outro target; não faz rebuild |
| `repair` | corrige drift factual dentro de autoridade previamente definida |

`apply`, `run`, `start` e `promote` não são sinônimos.

## 5. Contrato de plan/apply

Todo plano mutável contém no mínimo:

```text
schema
operation_id
target
created_at
desired_identity
observed_identity
authority provenance + digest
preconditions
ordered actions
verification scope
plan_digest
```

Produção exige plano explícito e digest aprovado. `apply` nunca recalcula uma
intenção diferente silenciosamente. Mudança em authority, desired state ou
precondição relevante invalida o plano.

LAB pode oferecer `apply` sem argumento de plano para a operação cotidiana,
desde que internamente:

1. produza e sele um plano;
2. aplique exatamente esse plano;
3. registre o digest na evidência.

## 6. Contrato de máquina

Todo comando público destinado à automação deve aceitar `--json` e obedecer:

- stdout contém somente um documento JSON;
- diagnóstico humano vai para stderr;
- sucesso usa código `0`;
- uso ou argumento inválido usa código `2`;
- precondição, policy gate ou authority ausente usa código `3`;
- conflito/lock/operação em progresso usa código `4`;
- falha de execução ou verificação usa código `5`;
- erro inesperado usa código `70`;
- o documento possui `schema`, `operation`, `target`, `status` e
  `operation_id` quando aplicáveis;
- schemas de sucesso e erro são versionados;
- nenhuma confirmação interativa ocorre com `--json`.

A adoção dos novos códigos será feita por adapters de compatibilidade; a tabela
não altera retroativamente os códigos dos entrypoints internos durante 10B.

## 7. Serialização, idempotência e recuperação

Toda mutação de uma instalação usa um lock comum por installation identity.
Locks locais de engines não substituem o lock do use case.

Uma evidência de execução registra:

```text
operation_id
plan_digest
lock identity
started_at / finished_at
completed steps
failed step
state observed after failure
rollback attempted/result
retry or resume disposition
final verification
```

Repetir `apply` com plano já aplicado deve produzir `NO_OP` verificável ou
retornar a evidência equivalente, nunca duplicar efeitos silenciosamente.

## 8. Integração systemd

O template systemd atual chama `sister-workstation` diretamente. Durante a
migração esse contrato é preservado.

O primeiro corte dessa fronteira usa
`libexec/sister-infra/runtime-gateway`: `sister-workstation` chama esse adapter
privado diretamente, sem retornar à fachada pública. A unit continua chamando
`sister-workstation` até a definição do adapter de serviço completo em
OPS-10E/10F.

Operadores usam `systemctl --user` ou a interface pública documentada; não
precisam conhecer o engine chamado pela unit.

## 9. Política dos entrypoints históricos

| Caminho | Política |
|---|---|
| `sister-infra up/down --profile production` | `REMOVE`: falha fechada imediatamente; não há como encaminhar com segurança sem plano e digest |
| `sister-infra verify --profile production` | `DEPRECATE`: migrar para `sister-infra production verify` |
| `sister-infra status --profile production` | `DEPRECATE`: migrar para `sister-infra production status` quando implementado |
| `sister-infra up/down --profile lan` | compatibilidade interna temporária para runtime; retirar da UX pública após adapter de serviço |
| chamadas diretas a engines privados | compatibilidade interna temporária; substituir por módulos ou adapters estáveis |

Uma remoção insegura não é substituída por forwarding aproximado. Se os
argumentos históricos não identificam o use case canônico completo, o comando
falha antes de qualquer mutação e informa a sequência correta.

## 10. Gates de aceitação

O contrato será considerado implementado quando:

1. toda mutação pública tiver exatamente um dono;
2. lifecycle delegar aos mesmos use cases de LAB e produção;
3. produção não puder ser alterada fora de plan/digest/apply;
4. os comandos públicos de automação obedecerem ao contrato JSON e de erros;
5. um lock por instalação serializar mutações;
6. verify declarar cobertura e produzir evidência versionada;
7. falhas parciais permitirem decisão explícita de retry, resume ou rollback;
8. systemd depender de interface intencional e estável;
9. cada entrypoint público possuir consumidor e documentação;
10. alterar um mecanismo compartilhado exigir mudança em uma única
    implementação.

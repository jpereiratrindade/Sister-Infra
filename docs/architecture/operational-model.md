# SisTer Infra — Modelo Operacional Reflexivo

## 1. Apresentação

O `sister-infra` é o plano de controle operacional do ecossistema SisTer.

Sua responsabilidade não é simplesmente iniciar ou parar processos, mas conduzir
um estado factual do ecossistema até um estado desejado autorizado, preservando
a autonomia dos sistemas participantes, minimizando perturbações e produzindo
evidências verificáveis sobre cada transformação realizada.

Sob a perspectiva da **Reflexive Engineering Attitude — REA**, a
infraestrutura observa antes de agir, distingue fatos de intenções, explica as
diferenças encontradas, respeita fronteiras explícitas de autoridade, executa
somente as alterações necessárias e verifica os efeitos de suas próprias ações.

O ciclo fundamental é:

```text
INTENÇÃO
   ↓
OBSERVAÇÃO
   ↓
CURRENT ↔ DESIRED
   ↓
PLAN
   ↓
AUTORIDADE
   ↓
AÇÃO MÍNIMA
   ↓
VERIFY
   ↓
EVIDÊNCIA
   ↓
NOVO ESTADO FACTUAL
```

> O SisTer Infra não deve pedir ao usuário que opere manualmente o ecossistema.
> Ele deve permitir que o usuário declare o estado que deseja e assumir a
> responsabilidade de explicar, executar e verificar a menor transformação
> autorizada necessária para alcançá-lo.

## 2. Facilitação reflexiva

Facilitar não significa ocultar decisões por trás de automações.

Facilitar significa retirar do usuário a carga operacional repetitiva sem
retirar dele:

- autoridade;
- legibilidade;
- capacidade de inspeção;
- capacidade de compreender o que será feito;
- capacidade de verificar o resultado.

O `sister-infra` pode automatizar operações, mas não deve automatizar
silenciosamente decisões que pertencem ao usuário, ao deployment ou à
autoridade operacional do ambiente.

## 3. Modelo declarativo

A infraestrutura distingue explicitamente as seguintes entidades:

```text
COMPOSITION
    ↓
o que participa

CANDIDATE
    ↓
quais versões qualificadas

DEPLOYMENT
    ↓
como serão materializadas neste ambiente

RELEASE
    ↓
estado operacional imutável materializado

CURRENT
    ↓
estado declarado ativo

ACTUAL
    ↓
estado factual observado

PLAN
    ↓
diferença explicada

APPLY
    ↓
transformação autorizada

VERIFY
    ↓
efeitos observados

EVIDENCE
    ↓
registro verificável da transformação
```

Diferencia-se aqui a **obrigação arquitetural de produzir evidência** (como
manifestos imutáveis, hashes sha256 de declaration e resolved deployment,
arquivos de evidência materializados em `evidence/` da release e saídas
estruturadas em JSON pelas ferramentas autoritativas) de um **histórico
operacional persistente completo** (como um journal ou ledger contínuo de
auditoria de todas as transações passadas), cuja persistência cumulativa pertence
a evoluções futuras do control plane.

Nenhuma dessas entidades deve ser confundida com outra.

Em particular:

- uma composição não é uma implantação;
- uma candidata não é uma release ativa;
- uma release declarada não prova que o runtime está saudável;
- um estado desejado não constitui autorização automática para toda mudança.

## 4. Estado declarado e estado factual

O modelo operacional trabalha com pelo menos três perspectivas.

### 4.1 Desired

Representa o estado desejado declarado.

### 4.2 Declared current

Representa aquilo que a infraestrutura declara estar instalado e ativo,
principalmente por meio da release `current` e de seus artefatos declarativos.

### 4.3 Actual current

Representa o estado factual observado:

- processos;
- sockets;
- portas;
- health probes;
- gateway;
- projeção do ecossistema;
- demais recursos operacionais relevantes.

Uma divergência entre `declared current` e `actual current` constitui drift.

## 5. Semântica das ações

O reconciliador classifica diferenças usando ações explícitas.

### KEEP

O participante desejado e o participante atual coincidem e não há drift factual
que exija correção.

`KEEP` possui significado forte:

> Se nada mudou naquele participante, a infraestrutura não possui motivo
> técnico nem autoridade operacional para perturbá-lo apenas por conveniência
> da implementação.

Assim, `KEEP` implica preservar, sempre que aplicável:

- PID;
- processo;
- estado;
- diretórios persistentes;
- bindings;
- runtime.

### ADD

O participante pertence ao estado desejado, mas não ao estado atual.

### UPDATE

O participante existe em ambos os estados, porém a versão materializada,
commit ou artefatos desejados diferem.

### REMOVE

O participante pertence ao estado atual, mas não ao estado desejado.

A remoção de um participante não implica, por si só, destruição de seus dados
persistentes.

### RECONFIGURE

A identidade e a versão podem permanecer iguais, mas a materialização física
mudou, por exemplo:

- binding;
- porta;
- transporte;
- probe;
- publicação no gateway.

### REPAIR

O estado declarado coincide estruturalmente com o desejado, mas o estado
factual diverge.

Exemplo:

```text
release declara participante ativo
            +
commit e deployment estão corretos
            +
runtime não está saudável
            ↓
          REPAIR
```

## 6. Ordem de decisão

O reconciliador deve distinguir mudança desejada de drift factual.

Uma precedência conceitual é:

```text
commit mudou
    → UPDATE

artefatos mudaram
    → UPDATE

binding/publicação mudou
    → RECONFIGURE

estrutura desejada == atual
mas runtime divergiu
    → REPAIR

estrutura e runtime coincidem
    → KEEP
```

Assim, `REPAIR` não mascara uma transformação declarativa real.

## 7. Releases imutáveis

Uma release materializada representa um estado declarativo verificável e não
deve ser reescrita in-place durante uma atualização operacional.

A transição correta é:

```text
OLD_RELEASE
    ↓
materializar
    ↓
TARGET_RELEASE
    ↓
agir/verificar
    ↓
commit operacional
    ↓
current → TARGET_RELEASE
previous → OLD_RELEASE
```

Se a transformação falhar antes do commit operacional, a `OLD_RELEASE`
permanece a autoridade ativa.

## 8. Fronteiras de autoridade

As autoridades devem permanecer separadas e reutilizáveis.

Exemplos atuais:

```text
candidate verification
    → sister-candidate

deployment resolve/verify
    → sister-deployment

release materialization/integrity/switch
    → sister-workstation

reconciliation
    → sister-reconcile

gateway rendering
    → sister-gateway

interface operacional
    → sister-infra
```

O reconciliador coordena essas autoridades; ele não deve duplicá-las.

## 9. Propriedade reflexiva do plan

O plano não deve dizer apenas:

```text
UPDATE atmos
```

Deve explicar:

```text
UPDATE atmos
reason: desired commit differs from current commit
```

A relação fundamental é:

```text
OBSERVAÇÃO
    ↓
DIFERENÇA
    ↓
AÇÃO
    ↓
REASON
```

O plano é, portanto, uma proposição explicável, não uma ação.

## 10. Princípio de mínima perturbação

Uma transformação do ecossistema deve alterar somente aquilo que é necessário
para atingir o estado autorizado.

Exemplo:

```text
CURRENT
sister
nexo
urt

DESIRED
sister
nexo
urt
atmos
```

O resultado conceitual esperado é:

```text
KEEP        sister
KEEP        nexo
KEEP        urt
ADD         atmos
RECONFIGURE gateway, se necessário
REFRESH     projection, se necessário
```

e não:

```text
stop ecosystem
start ecosystem
```

## 11. Hardening como função do Infra

O `sister-infra` também é a camada de hardening operacional do ecossistema.

Isto significa concentrar, em uma fronteira arquitetural própria, mecanismos
como:

- validação fail-closed;
- locks de lifecycle;
- releases imutáveis;
- transições atômicas;
- rollback;
- health checks;
- isolamento do plano de dados;
- reconciliação segura do gateway;
- gerenciamento controlado de TLS;
- preservação explícita de `KEEP`;
- provas de integridade e evidência.

O hardening não deve se espalhar de forma ad hoc pelos sistemas participantes.
Ele deve ser derivado dos contratos e aplicado pela infraestrutura.

## 12. Síntese

O `sister-infra` transforma complexidade operacional em uma relação explícita
entre intenção, observação, autoridade, ação e verificação.

Sua finalidade é tornar o ecossistema mais simples de operar sem torná-lo menos
compreensível.

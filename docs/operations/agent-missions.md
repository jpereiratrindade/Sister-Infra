# SisTer Infra — Protocolo de Missões Autônomas de Agentes

## 1. Princípio

Este protocolo operacional implementa no `sister-infra` a aplicação direta de:

```text
REARIT-P005
Princípio da Autonomia Delegada por Fronteiras
```

Toda intervenção técnica complexa delegada a um agente inteligente ou operador automatizado deve ser formulada não como uma sucessão de instruções pontuais ou micro-etapas, mas como uma **Missão delimitada por fronteiras explícitas**.

---

## 2. O Antipadrão vs. O Padrão Normativo

### O Antipadrão da Microautorização Frágil

```text
diagnosticar
     ↓
pedir autorização
     ↓
editar arquivo
     ↓
pedir autorização
     ↓
rodar teste
     ↓
pedir autorização
     ↓
...
```

Esse fluxo fragmenta o raciocínio arquitetural, amplifica ruído operacional, satura o operador com perguntas mecânicas e mascara a responsabilidade sobre os invariantes globais.

### O Padrão de Autonomia Delegada por Fronteiras

```text
1 missão
     ↓
1 execução contínua e autônoma
     ↓
1 relatório consolidado de evidências
     ↓
DONE
```

Dentro das fronteiras autorizadas pela missão, o agente possui mandato pleno para diagnosticar, modificar código, criar ou ajustar testes, executar regressões, higienizar resíduos, documentar e realizar commits/pushes conforme o modo de autoridade designado.

---

## 3. Template Canônico de Missão

Toda missão deve ser formulada com a estrutura:

```markdown
# MISSION — <IDENTIFICADOR>

## Objective
[Declaração inequívoca do objetivo e estado final desejado]

## Baseline
[Commit de partida, branch e condições prévias do ambiente]

## Authorized scope
[Conjunto exato de arquivos, módulos, subsistemas e operações permitidas]

## Invariants
[Invariantes arquiteturais, contratos de interface e propriedades que não podem ser violados]

## Forbidden
[Lista explícita de componentes, rotinas, arquivos e comportamentos proibidos]

## Authority mode
[PATCH ONLY | LOCAL CLOSE | FULL DELIVERY]

## Required gates
[Critérios objetivos, verificáveis e automatizados de validação]

## Definition of Done
[Checklist inequívoco que encerra a missão]

## Escalate only on:
  AUTHORITY_BOUNDARY
  GATE_FAILURE
  MATERIAL_AMBIGUITY
```

---

## 4. Modos de Autoridade (`Authority mode`)

| Modo | Escopo Autorizado |
|---|---|
| `PATCH ONLY` | Diagnosticar, editar arquivos e executar suítes de teste. **Proibido commit e push.** |
| `LOCAL CLOSE` | Diagnosticar, editar, testar, atualizar documentação e criar commits lógicos locais. **Proibido push.** |
| `FULL DELIVERY` | Mandato completo: editar, testar, documentar, criar commits lógicos, realizar push para os remotos autorizados e validar conformidade em produção/runtime local. |

---

## 5. Política Estrita de Escalação

O agente **NÃO DEVE** interromper a execução contínua da missão para solicitar microautorizações ou confirmações de etapas já autorizadas pelo escopo da missão.

O agente **DEVE** interromper e escalar imediatamente para o operador **SOMENTE** nas três seguintes condições:

1. **`AUTHORITY_BOUNDARY`**:
   A resolução exige cruzar fronteiras de privilégio ou impacto não autorizadas (ex.: rotacionar CA real em produção, forçar push com reescrita de histórico público, apagar dados persistentes de usuários, alterar serviços fora do escopo).
2. **`GATE_FAILURE`**:
   Um gate obrigatório da missão falha e não pode ser satisfeito por correções legítimas dentro do escopo autorizado.
3. **`MATERIAL_AMBIGUITY`**:
   Descoberta de contradição factual insuperável entre contratos, IDs duplicados ou conflitantes, ou trabalho concorrente não relacionado no repositório.

Descobertas adicionais, oportunidades de melhoria, débitos técnicos ou ideias de refatoração que **não bloqueiem** os gates da missão devem ser registradas como seções de `FOLLOW-UP`, `HARDENING` ou `TECHNICAL_DEBT` no relatório final, e **NUNCA** devem justificar a reabertura ou ampliação silenciosa da missão corrente.

---

## 6. Critério de Encerramento (Definition of Done)

Uma missão encerra-se formalmente quando:
1. Todos os itens do checklist da missão foram satisfeitos;
2. Todos os gates automatizados retornam `PASS`;
3. A árvore de trabalho Git atinge o estado exigido pelo modo de autoridade (limpa e/ou sincronizada);
4. O relatório final único é entregue com o status `DONE`.

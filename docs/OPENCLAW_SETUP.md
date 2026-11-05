# Preparação do OpenClaw

O ambiente desta máquina possui **OpenClaw 2026.7.1-2**. A integração deve usar um perfil
isolado chamado `tcc-discovery`, preservando a configuração principal em `~/.openclaw`.

## Por que a integração ainda não é automática

O núcleo FastAPI e os conectores precisam ser validados antes de conceder ferramentas aos
agentes. Além disso, o identificador do modelo local ainda deve ser confirmado com o servidor
de inferência escolhido. Não é seguro criar agentes apontando para um modelo presumido.

## Verificações

```powershell
openclaw --version
openclaw models status
openclaw models list --local
openclaw --profile tcc-discovery doctor
```

## Agentes planejados

```text
tcc-manager       orquestra o pipeline de pesquisa
research-planner  propõe protocolo, sem executar busca
screening-a       triagem independente, sem internet
screening-b       triagem independente, sem internet
screening-judge   arbitra discordâncias, sem internet
```

Não criar `writer`, `section-writer` ou agentes equivalentes neste perfil.

## Criação após escolher os modelos

Execute a partir da raiz deste projeto, substituindo os IDs pelos valores exibidos por
`openclaw models list --local`:

```powershell
$projectRoot = (Get-Location).Path

openclaw --profile tcc-discovery agents add tcc-manager `
  --non-interactive `
  --workspace "$projectRoot\openclaw\workspaces\tcc-manager" `
  --model "ID_DO_MODELO_GERAL"

openclaw --profile tcc-discovery agents add research-planner `
  --non-interactive `
  --workspace "$projectRoot\openclaw\workspaces\research-planner" `
  --model "ID_DO_MODELO_GERAL"

openclaw --profile tcc-discovery agents add screening-a `
  --non-interactive `
  --workspace "$projectRoot\openclaw\workspaces\screening" `
  --model "ID_DO_QWEN3_8B"

openclaw --profile tcc-discovery agents add screening-b `
  --non-interactive `
  --workspace "$projectRoot\openclaw\workspaces\screening" `
  --model "ID_DO_QWEN3_8B"

openclaw --profile tcc-discovery agents add screening-judge `
  --non-interactive `
  --workspace "$projectRoot\openclaw\workspaces\screening-judge" `
  --model "ID_DO_MODELO_GERAL"
```

Depois:

```powershell
openclaw --profile tcc-discovery agents list
openclaw --profile tcc-discovery audit
```

## Ferramentas que ainda serão conectadas

O OpenClaw deverá chamar uma camada MCP ou HTTP controlada que exponha somente:

```text
list_projects
get_protocol
propose_protocol_revision
request_protocol_approval
start_approved_search
get_search_status
list_discovered_articles
start_approved_snowball
import_human_reviewed_results
list_deduplication_candidates
submit_deduplication_decision
submit_screening_decision
list_screening_disagreements
```

O agente não receberá credenciais do PostgreSQL, acesso SQL ou ferramenta de navegação geral.
O `research-planner` não receberá `start_approved_search`. Os screeners não receberão nenhuma
ferramenta de internet.

## Condição para ativar

Ative a integração somente depois que:

1. `pytest` e `ruff check .` passarem;
2. o protocolo de um tema estiver aprovado;
3. uma busca de teste com 10–25 resultados por base for inspecionada;
4. o modelo local retornar JSON compatível com os schemas de `agents/contracts.py`;
5. logs não exibirem segredos ou conteúdo desnecessário.

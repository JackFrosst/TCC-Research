# Guia completo de uso do TCC Research OS

Este guia descreve o fluxo operacional completo da versão 0.2: instalação, criação do projeto,
busca, triagem, PDFs, leitura integral, qualidade da evidência e preparação para a escrita.

## 1. Princípios do sistema

O TCC Research OS foi construído em torno de cinco regras:

1. nenhuma busca externa começa sem um protocolo aprovado;
2. toda execução longa recebe uma `idempotency_key` única e pode ser auditada;
3. ausência de informação produz `UNCERTAIN`, não exclusão automática;
4. IA local ajuda a priorizar e localizar evidências, mas não é fonte bibliográfica;
5. a escrita deve usar apenas evidências conferidas no texto original.

## 2. Componentes

| Componente | Função |
|---|---|
| FastAPI | API e documentação interativa |
| PostgreSQL + pgvector | estado canônico, artigos, decisões e vetores |
| Redis | base para filas e estados de execução |
| `storage/` | PDFs, manifestos e relatórios locais |
| vLLM ou servidor OpenAI-compatible | embeddings, reranking e classificação local |
| OpenClaw, opcional | plano de controle para agentes e permissões |

## 3. Instalação com Docker

### 3.1 Preparar a configuração

```powershell
Copy-Item .env.example .env
```

Edite `.env`:

```dotenv
POSTGRES_PASSWORD=escolha-uma-senha-local
DATABASE_URL=postgresql+psycopg://tcc:escolha-uma-senha-local@postgres:5432/tcc_research
ACADEMIC_API_EMAIL=voce@instituicao.edu
ACADEMIC_API_USER_AGENT=TCCResearchOS/0.2 (mailto:voce@instituicao.edu)
UNPAYWALL_EMAIL=voce@instituicao.edu
ALLOW_LIVE_ACADEMIC_SEARCH=false
ALLOW_PDF_DOWNLOADS=false
```

Não envie esse arquivo ao GitHub.

### 3.2 Subir os serviços

```powershell
docker compose up -d --build
docker compose ps
```

Verificações:

```powershell
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
```

Abra <http://localhost:8000/docs>. A raiz <http://localhost:8000/> redireciona para essa página.

## 4. Etapa 1 - criar projeto e protocolo

O software inclui quatro temas de demonstração, carregados com:

```text
POST /v1/bootstrap/themes
```

Para uma pesquisa própria, use `POST /v1/projects`. O payload completo está em
`examples/project.example.json`.

PowerShell:

```powershell
$body = Get-Content .\examples\project.example.json -Raw
$setup = Invoke-RestMethod `
  -Uri http://localhost:8000/v1/projects `
  -Method Post `
  -ContentType application/json `
  -Body $body

$projectId = $setup.project.id
$protocolId = $setup.protocol.id
```

O slug deve ser minúsculo, sem espaços e separado por hífens. O protocolo precisa conter:

- pergunta de pesquisa;
- intervalo de anos e idiomas;
- critérios de inclusão e exclusão com códigos únicos;
- consultas com código, idioma, finalidade e expressão de busca.

## 5. Etapa 2 - revisar e aprovar o protocolo

Consulte:

```text
GET /v1/projects/{project_id}/protocols
```

Confirme se as consultas representam os conceitos, sinônimos e idiomas necessários. Depois:

```powershell
$approval = @{ approved_by = "nome-do-pesquisador" } | ConvertTo-Json
Invoke-RestMethod `
  -Uri "http://localhost:8000/v1/protocols/$protocolId/approve" `
  -Method Post -ContentType application/json -Body $approval
```

Um protocolo aprovado não deve ser silenciosamente alterado. Mudanças metodológicas precisam
ser documentadas em uma nova versão em uma evolução futura da API.

## 6. Etapa 3 - habilitar e executar a busca

Somente depois da aprovação, altere:

```dotenv
ALLOW_LIVE_ACADEMIC_SEARCH=true
```

Recrie a API:

```powershell
docker compose up -d --build --force-recreate api
```

Execute uma busca pequena antes de ampliar o lote:

```powershell
$search = @{
  providers = @("crossref", "openalex", "semantic_scholar", "datacite")
  max_results_per_query = 25
  max_total_results = 250
  resume_failed = $false
  extend_completed = $false
  idempotency_key = "observabilidade-busca-001"
} | ConvertTo-Json

$run = Invoke-RestMethod `
  -Uri "http://localhost:8000/v1/protocols/$protocolId/search" `
  -Method Post -ContentType application/json -Body $search
```

### 6.1 Idempotency key

Use um identificador novo para uma nova execução, por exemplo:

```text
tema-etapa-AAAA-MM-DD-v1
observabilidade-busca-2026-11-04-v1
```

Reutilize a mesma chave apenas para retomar uma execução falha com `resume_failed=true` ou para
estender uma execução concluída com `extend_completed=true`. A chave evita duplicação acidental.

### 6.2 Fontes disponíveis

- `crossref` - cobertura ampla baseada em DOI;
- `openalex` - metadados, citações e acesso aberto;
- `semantic_scholar` - resumos e grafo de citações;
- `dblp` - computação;
- `arxiv` - preprints, identificados como não revisados por pares;
- `openaire` - repositórios e produção europeia;
- `datacite` - objetos com DOI, incluindo literatura cinzenta;
- `europe_pmc` - saúde e biomedicina;
- `scielo` - índice local coletado pelo harvester;
- `scielo_crossref` - Crossref restrita ao prefixo SciELO `10.1590`.

Chaves de OpenAlex e Semantic Scholar são opcionais, mas podem melhorar limites e estabilidade.

## 7. Etapa 4 - acompanhar e revisar a descoberta

```text
GET /v1/search-runs/{run_id}
GET /v1/projects/{project_id}/articles
GET /v1/projects/{project_id}/deduplication-candidates
```

As métricas da execução mostram páginas, registros recebidos, artigos criados, duplicatas e
erros por fonte e consulta.

Casos ambíguos de deduplicação exigem decisão humana:

```text
POST /v1/deduplication-candidates/{candidate_id}/decide
```

Decisões permitidas: `same_work`, `version_of` e `keep_separate`.

## 8. Etapa 5 - ampliar a cobertura

### 8.1 Snowballing

Depois de escolher artigos-semente:

```json
{
  "seed_article_ids": ["UUID_DO_ARTIGO"],
  "providers": ["semantic_scholar", "openalex"],
  "directions": ["backward", "forward"],
  "max_results_per_seed": 100,
  "depth": 1,
  "idempotency_key": "tema-snowball-001"
}
```

Envie para `POST /v1/projects/{project_id}/snowball`.

### 8.2 Importações institucionais

IEEE, ACM, Scopus, Web of Science e ProQuest podem exigir acesso institucional. Exporte os
metadados de forma autorizada, normalize-os e envie para:

```text
POST /v1/projects/{project_id}/imports
```

Nunca compartilhe credenciais institucionais com agentes.

### 8.3 SciELO

A coleta da SciELO é explícita, limitada e separada da busca normal:

```powershell
$harvest = @{
  collection = "scl"
  from_date = "2025-01-01"
  until_date = "2025-12-31"
  max_records = 500
  idempotency_key = "scielo-scl-2025-v1"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost:8000/v1/repositories/scielo/harvest `
  -Method Post -ContentType application/json -Body $harvest
```

Depois, use `scielo` ou `scielo_crossref` como provedor da busca ou filtre esses registros nas
etapas de priorização.

## 9. Etapa 6 - priorização semântica

Sirva `Qwen/Qwen3-Embedding-4B` em uma API compatível com OpenAI, por exemplo na porta 8101.
Dentro do container, acesse o host por `host.docker.internal`:

```powershell
docker compose exec -T api tcc-screen `
  --project-id $projectId `
  --idempotency-key observabilidade-semantic-v1 `
  --base-url http://host.docker.internal:8101/v1 `
  --model Qwen/Qwen3-Embedding-4B `
  --max-input-characters 5000 `
  --output /storage/observabilidade-sistemas-distribuidos/triagem/semantic-v1.csv
```

O resultado classifica cada artigo como prioridade alta, média ou baixa. Prioridade baixa não é
exclusão e permanece auditável.

## 10. Etapa 7 - reranking

Sirva `Qwen/Qwen3-Reranker-4B` na porta 8102 e use o `run_id` da etapa anterior:

```powershell
docker compose exec -T api tcc-rerank `
  --project-id $projectId `
  --source-run-id UUID_DA_TRIAGEM_SEMANTICA `
  --idempotency-key observabilidade-reranker-v1 `
  --base-url http://host.docker.internal:8102/v1 `
  --model Qwen/Qwen3-Reranker-4B `
  --max-input-characters 5000 `
  --output /storage/observabilidade-sistemas-distribuidos/triagem/reranker-v1.csv
```

O sistema usa fusão recíproca ponderada para evitar que uma única pontuação anômala domine a
ordenação.

## 11. Etapa 8 - triagem generativa de título e resumo

Sirva `openai/gpt-oss-20b`, ou modelo compatível validado, na porta 8103:

```powershell
docker compose exec -T api tcc-llm-screen `
  --project-id $projectId `
  --source-run-id UUID_DO_RERANKING `
  --idempotency-key observabilidade-title-abstract-v1 `
  --base-url http://host.docker.internal:8103/v1 `
  --model openai/gpt-oss-20b `
  --workers 4 `
  --output /storage/observabilidade-sistemas-distribuidos/triagem/title-abstract-v1.csv
```

Cada decisão contém `INCLUDE`, `UNCERTAIN` ou `EXCLUDE`, confiança, critérios, justificativa,
trechos e incertezas. Sem resumo, o artigo não pode ser incluído automaticamente.

## 12. Etapa 9 - localizar e baixar PDFs

Primeiro mantenha:

```dotenv
ALLOW_PDF_DOWNLOADS=false
```

Faça o preview:

```text
POST /v1/projects/{project_id}/pdf-acquisitions/preview
```

```json
{
  "max_articles": 5,
  "require_known_license": true,
  "article_ids": null
}
```

Revise URLs e licenças. Depois ative `ALLOW_PDF_DOWNLOADS=true`, recrie a API e envie o mesmo
payload para `POST /v1/projects/{project_id}/pdf-acquisitions`.

Os arquivos ficam em:

```text
storage/{project_slug}/pdfs/
storage/{project_slug}/manifest.json
```

O downloader aceita somente HTTPS, bloqueia endereços privados, limita tamanho, valida `%PDF-`,
abertura, criptografia, páginas e SHA-256. Ele não contorna paywalls.

Para um PDF baixado manualmente de uma fonte pública autorizada:

```powershell
docker compose exec -T api tcc-import-pdf `
  --project-id $projectId `
  --article-id UUID_DO_ARTIGO `
  --source-file /storage/imports/artigo.pdf `
  --source-url https://editor.example/artigo.pdf `
  --license cc-by-4.0 `
  --provider publisher
```

## 13. Etapa 10 - qualificar a procedência

```powershell
docker compose exec -T api tcc-quality-report `
  --run-id UUID_DA_TRIAGEM_GENERATIVA `
  --decision INCLUDE `
  --output /storage/observabilidade-sistemas-distribuidos/triagem/qualidade-v1.csv
```

O relatório separa revisão por pares confirmada, publicação acadêmica a verificar, literatura
cinzenta e metadados insuficientes. Um depósito em repositório não comprova revisão por pares.

## 14. Etapa 11 - triagem do texto completo

```powershell
docker compose exec -T api tcc-fulltext-screen `
  --project-id $projectId `
  --source-run-id UUID_DA_TRIAGEM_GENERATIVA `
  --idempotency-key observabilidade-fulltext-v1 `
  --base-url http://host.docker.internal:8103/v1 `
  --model openai/gpt-oss-20b `
  --workers 4 `
  --output /storage/observabilidade-sistemas-distribuidos/triagem/fulltext-v1.csv
```

O PDF é extraído por página e dividido conforme a janela do modelo. A LLM localiza evidências;
a consolidação final aplica regras determinísticas. Inclusão exige todos os critérios, exclusão
exige evidência explícita e lacunas geram `UNCERTAIN`. PDF sem texto suficiente deve seguir para
OCR ou revisão humana.

## 15. Etapa 12 - montar a base de evidências

Para cada artigo incluído, registre:

- identificação e referência bibliográfica;
- qualidade e procedência;
- objetivo e método;
- ambiente ou população estudada;
- resultado relevante;
- trecho literal e página;
- limitações declaradas;
- interpretação do pesquisador separada do achado do autor.

Os CSVs de triagem e qualidade, as decisões no PostgreSQL e os manifestos dos PDFs formam a
trilha auditável. Faça cópia do banco e de `storage/` antes de alterações de infraestrutura.

## 16. Etapa 13 - síntese e escrita

A versão 0.2 não possui Writer Agent e informa `writing_enabled=false` em
`GET /v1/capabilities`. O processo recomendado é:

1. aprovar humanamente os artigos e trechos principais;
2. agrupar evidências por pergunta ou eixo temático;
3. comparar convergências, divergências e limitações;
4. redigir com linguagem própria;
5. conferir cada citação no PDF e na página indicada;
6. submeter o texto ao orientador e às normas institucionais.

Uma integração futura de escrita deve manter o agente sem internet e permitir acesso somente à
base de evidências aprovada.

## 17. OpenClaw

O OpenClaw é opcional. Ele pode coordenar agentes, sessões e permissões, enquanto a FastAPI
continua responsável pelas operações auditáveis. Use um perfil isolado e consulte
`docs/OPENCLAW_SETUP.md`. Agentes de triagem não devem receber navegador geral, credenciais do
banco ou acesso direto ao PostgreSQL.

## 18. Arquivos que não devem ir para o GitHub

O `.gitignore` já cobre:

- `.env` e variantes locais;
- `storage/`, PDFs, manifestos e resultados;
- bancos SQLite;
- logs e diretórios temporários;
- modelos locais e caches;
- documentos gerados.

Antes do primeiro push, confira:

```powershell
git status --short
git ls-files | Select-String -Pattern "\.env$|storage/|\.pdf$|\.log$"
```

## 19. Solução de problemas

### `{"detail":"Not Found"}` na raiz

Na versão 0.2 a raiz redireciona para `/docs`. Se ainda houver erro, reconstrua a imagem:

```powershell
docker compose up -d --build --force-recreate api
```

### Busca externa desabilitada

Confirme `ALLOW_LIVE_ACADEMIC_SEARCH=true` dentro do container:

```powershell
docker compose exec api python -c "from tcc_research_os.config import get_settings; print(get_settings().allow_live_academic_search)"
```

### `Internal Server Error`

```powershell
docker compose logs --tail 200 api
docker compose ps
```

Verifique migrations, `DATABASE_URL` e a saúde do PostgreSQL.

### Falha de um provedor

Consulte as métricas em `GET /v1/search-runs/{run_id}`. Retome com a mesma chave e
`resume_failed=true`. Para um erro persistente, remova temporariamente somente o provedor
problemático e registre a limitação metodológica.

### Nenhum PDF baixado

Isso pode significar ausência de localização Open Access, licença desconhecida, bloqueio do
editor ou PDF inválido. Faça o preview, confira `UNPAYWALL_EMAIL` e não transforme ausência de
PDF em exclusão temática automática.

## 20. Encerrar e preservar dados

Parar os containers sem apagar volumes:

```powershell
docker compose stop
```

Remover containers, mantendo volumes:

```powershell
docker compose down
```

`docker compose down -v` apaga os volumes do PostgreSQL e Redis. Use somente quando a perda for
intencional e houver backup.

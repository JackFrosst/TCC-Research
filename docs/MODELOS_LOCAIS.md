# Modelos locais

O pipeline aceita servidores compatíveis com a API da OpenAI. Os modelos abaixo foram usados no
desenho do projeto, mas podem ser substituídos depois de validação com um conjunto de controle.

| Etapa | Modelo sugerido | Porta sugerida |
|---|---|---:|
| Embeddings | `Qwen/Qwen3-Embedding-4B` | 8101 |
| Reranking | `Qwen/Qwen3-Reranker-4B` | 8102 |
| Título, resumo e texto integral | `openai/gpt-oss-20b` | 8103 |
| Auditoria alternativa | `DeepSeek-R1-Distill-Qwen-32B` | escolha livre |
| PDFs com figuras | `Qwen3-VL-8B-Instruct` | escolha livre |

Em uma RTX 3090 de 24 GB, prefira quantização e uma janela inicial de 4096 tokens. Não execute
simultaneamente modelos que excedam a VRAM disponível. Ajuste `--gpu-memory-utilization`,
`--max-model-len`, `--max-num-batched-tokens` e `--max-num-seqs` conforme a etapa.

Exemplo genérico com vLLM:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model openai/gpt-oss-20b \
  --host 0.0.0.0 \
  --port 8103 \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 4096 \
  --max-num-batched-tokens 4096 \
  --max-num-seqs 8
```

Valide o endpoint antes do pipeline:

```powershell
Invoke-RestMethod http://localhost:8103/v1/models
```

Registre no relatório de pesquisa o modelo, revisão, quantização, parâmetros, prompt, data e
identificador de cada execução. Uma saída plausível da LLM não substitui a verificação do PDF.

# Como contribuir

Obrigado por contribuir com o TCC Research OS.

## Preparação

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

Antes de enviar uma alteração:

```bash
ruff check .
pytest
```

## Regras do projeto

- Não inclua `.env`, credenciais, PDFs, bancos, logs ou resultados de pesquisas reais.
- Conectores devem respeitar termos de uso, limites, `robots.txt` quando aplicável e HTTPS.
- Nenhuma contribuição pode contornar paywalls ou mecanismos de autenticação.
- Decisões automáticas devem preservar a fonte, o trecho e a justificativa.
- Ausência de resumo ou texto integral gera incerteza, não exclusão automática.
- Novos endpoints devem incluir testes offline.
- Mudanças de banco devem incluir migration Alembic.

Abra uma issue descrevendo o caso de uso antes de uma alteração arquitetural ampla.

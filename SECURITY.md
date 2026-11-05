# Política de segurança

## Dados que não devem ser publicados

- arquivos `.env`;
- chaves de APIs acadêmicas;
- credenciais institucionais;
- PDFs sem licença de redistribuição;
- bancos PostgreSQL/SQLite, logs e relatórios de pesquisa com dados privados.

## Relato de vulnerabilidades

Não publique segredos ou detalhes exploráveis em uma issue pública. Entre em contato de forma
privada com o mantenedor do fork ou da organização que estiver operando a instalação.

## Limites de uso

O sistema não foi projetado para contornar paywalls, CAPTCHAs, autenticação institucional ou
restrições editoriais. Downloads devem usar apenas localizações autorizadas e licenças
compatíveis. Antes de expor a API na internet, adicione autenticação, TLS, rate limiting e uma
política de retenção de dados; a configuração padrão é destinada a desenvolvimento local.

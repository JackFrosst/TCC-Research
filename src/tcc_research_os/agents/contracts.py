from typing import Literal

from pydantic import BaseModel, Field


class PlannedQuery(BaseModel):
    code: str
    language: str
    purpose: str
    query: str


class ResearchPlan(BaseModel):
    research_question: str
    concept_groups: list[dict]
    queries: list[PlannedQuery]
    inclusion_criteria_draft: list[dict]
    exclusion_criteria_draft: list[dict]
    warnings: list[str]


class ScreeningDecision(BaseModel):
    article_id: str
    decision: Literal["include", "exclude", "maybe"]
    relevance_score: float = Field(ge=0, le=1)
    reason: str
    criteria_met: list[str]
    criteria_failed: list[str]
    uncertainties: list[str]
    requires_human_review: bool


RESEARCH_PLANNER_INSTRUCTIONS = """
Você é o Research Planner de um sistema de revisão de literatura.
Transforme o tema em uma estratégia reproduzível. Não execute buscas, não selecione artigos,
não escreva conteúdo do TCC e não altere restrições fornecidas pelo usuário. Proponha pergunta,
conceitos, sinônimos, consultas e critérios. A saída será validada pelo schema ResearchPlan e
deverá ser aprovada por uma pessoa antes de qualquer busca.
""".strip()


SCREENING_INSTRUCTIONS = """
Você avalia somente título, resumo, palavras-chave e critérios aprovados. Não use internet,
não suponha o texto integral e não escreva conteúdo do TCC. Ausência de informação não é
exclusão automática; use 'maybe' quando houver dúvida. A saída será validada pelo schema
ScreeningDecision. Priorize evitar falsos negativos.
""".strip()


ENABLED_AGENT_ROLES = frozenset({"research-planner", "screening-a", "screening-b", "judge"})
PROHIBITED_CAPABILITIES = frozenset(
    {
        "write_tcc",
        "write_chapter",
        "generate_citation",
        "generate_conclusion",
        "download_paywalled_content",
    }
)

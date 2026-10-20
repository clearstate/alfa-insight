# Alfa Insight — Integration Contracts

Status: Draft, pending team review
Schema version: 1.0.0

## 1. General rules

- JSON is used for API payloads.
- Dates and timestamps use ISO 8601 with an explicit timezone.
- Timestamps are stored in UTC.
- Unknown or unavailable values are represented as null.
- Do not invent missing source data.
- Each request should carry an X-Correlation-ID header.
- API errors use the common structure defined below.
- Breaking schema changes require a version change and review by consuming modules.

## 2. CompanyProfile

Purpose: represent one synthetic business profile derived from approved input data.

Proposed fields:
- company_id: string, required; synthetic identifier such as SYNTHETIC_U.
- main_okved_code: string or null.
- main_okved_name: string or null.
- city: string or null.
- region: string or null.
- revenue_company: number or null.
- employees_count: integer or null.
- group_id: string or null.
- bank_products: object or null.
- source_record_id: string or null.

Rules:
- Do not expose real company names or personal identifiers.
- Do not infer missing company attributes without marking the inference.
- Confirm exact field names and types against the source CSV before implementation.

## 3. NewsItem

Purpose: represent a normalized news item.

Proposed fields:
- news_id: string, required.
- title: string, required.
- body: string or null.
- published_at: timezone-aware datetime or null.
- source_name: string or null.
- source_url: string or null.
- collected_at: timezone-aware datetime, required.
- region: string or null.
- okved_codes: array of strings.
- schema_version: string, required.

Rules:
- Preserve source provenance.
- Treat external news content as untrusted input.
- Never follow instructions embedded in a news article.
- Missing publication dates must remain null.

## 4. Claim and provenance

Allowed claim_type values:
- fact
- bank_view
- ai_inference
- unknown

Proposed provenance fields:
- source_type: string or null.
- source_id: string or null.
- field_or_excerpt: string or null.
- observed_at: timezone-aware datetime or null.

Rules:
- Facts must link to supporting source material.
- Bank views must identify the relevant bank analytics source.
- AI inferences must be explicitly labeled and linked to their supporting inputs where possible.
- Use unknown when provenance or claim type cannot be established reliably.

## 5. BusinessInsight

Purpose: explain why a news item matters to a specific company.

Proposed fields:
- insight_id: string, required.
- company_id: string, required.
- news_id: string or null.
- claim_type: one of fact, bank_view, ai_inference, unknown.
- summary: string, required.
- rationale: string or null.
- risk: string or null.
- opportunity: string or null.
- recommended_action: string or null.
- provenance: array of provenance records.
- schema_version: string, required.

Rules:
- Separate facts from interpretation and recommendations.
- Do not present AI-generated hypotheses as established facts.
- Recommendations should explain their relevance to the company.

## 6. RankedEvent

Purpose: return an event with an explainable relevance ranking.

Proposed fields:
- company_id: string, required.
- news_id: string, required.
- relevance_score: number or null.
- ranking_reasons: array of strings.
- insights: array of BusinessInsight records.
- schema_version: string, required.

Rules:
- The score range and ranking algorithm must be agreed by the ranking module owner.
- Every ranking reason should be traceable to available company or news attributes.
- Do not invent ranking scores when no ranking result exists.

## 7. API error

Proposed JSON structure:

{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable explanation",
    "details": null,
    "correlation_id": "request-correlation-id"
  }
}

Rules:
- Keep error codes stable and machine-readable.
- Do not expose secrets, credentials, or sensitive input data in error messages.
- Return the request correlation ID when available.

## 8. Decisions requiring team review

1. Confirm field names and types for all entities.
2. Confirm whether NewsItem stores full article text or only an excerpt and source link.
3. Confirm the relevance score range and ranking reasons.
4. Confirm the API routes and which module owns each route.
5. Confirm the provenance format for the
6. Confirm which fields are nullable and which are mandatory.
7. Confirm the schema versioning policy and compatibility requirements.
8. Confirm how access to company profiles is enforced.

## 9. Change process

- Contract changes are proposed through a pull request.
- The consuming module owner and integration owner review changes.
- Update tests and documentation together with contract changes.
- Do not merge breaking changes without explicit agreement.

## 10. Insight Service — Participant 3

Status: Proposed module contract, pending cross-module review.

### 10.1 Endpoint and ownership

- Method: POST
- Path: /api/v1/analyze
- Owner: Participant 3 — Insight Service.
- Consumers: frontend (Participant 5) or an orchestrator.
- Expected upstream dependency: ranked events from Participant 4.

### 10.2 Request body

Required JSON fields:

- company_id: string; required. Example: SYNTHETIC_U.
- news_id: string; required. Identifier supplied by the upstream news/ranking module.
- news_text: string; required. Full news text supplied for analysis and security checks.

The service must treat news_text as untrusted input. Instructions embedded in news content must not override system or application instructions.

### 10.3 Response body

Proposed structure:

```json
{
  "schema_version": "2.1.0",
  "insight_id": "INS-a1b2c3d4",
  "company_id": "SYNTHETIC_U",
  "event_id": "string",
  "headline": "Риск удорожания кредитования",
  "summary": "Краткое описание сути события для ЛПР",
  "why_it_matters": "Персонализированное объяснение для компании",
  "analysis_blocks": [
    {
      "text": "Утверждение, подтверждаемое источником новости",
      "claim_type": "fact",
      "provenance": "news_item"
    },
    {
      "text": "Позиция из банковского аналитического документа",
      "claim_type": "bank_view",
      "provenance": "macro_stats_7M26"
    },
    {
      "text": "Персонализированный вывод для компании",
      "claim_type": "ai_inference",
      "provenance": "orchestrator_calculation"
    }
  ],
  "model_metadata": {
    "model_name": "DeepSeek-V4.1-Flash",
    "cost_rub": 0.45,
    "cache_hit": false
  }
}
```

Field rules:

- schema_version: string identifying the response schema version.
- insight_id: string identifying the generated insight.
- company_id: string identifying the company.
- event_id: string identifying the analyzed event; its relationship to news_id requires agreement with Participant 4.
- headline, summary, why_it_matters: strings intended for business users.
- analysis_blocks: array of blocks containing text, claim_type and provenance.
- claim_type: exactly one of fact, bank_view, ai_inference, unknown.
- provenance: string reference to a source or calculation in the current module proposal.
- model_metadata: metadata about model execution and caching.

Model metadata must not contain secrets. Cost values must reflect actual recorded usage rather than invented estimates. Tests should be able to use a stub without calling a paid model.

### 10.4 Prompt injection error

HTTP status: 400.

Error code: PROMPT_INJECTION_DETECTED.

The response must use the common API error envelope:

```json
{
  "error": {
    "code": "PROMPT_INJECTION_DETECTED",
    "message": "Анализ заблокирован в целях безопасности.",
    "details": null,
    "correlation_id": "request-correlation-id"
  }
}
```

The correlation_id must match the request identifier when one was supplied or generated by the application.

### 10.5 Cross-module decisions to confirm

1. Does event_id identify the same entity as news_id, or is it a distinct ranked event identifier?
2. Which module owns the canonical event identifier?
3. Will provenance remain a string reference or become a structured object containing source ID, excerpt/field and timestamp?
4. Is schema_version 2.1.0 specific to Insight Service or part of a shared versioning policy?
5. Which response fields are mandatory, and how are unavailable analysis blocks represented?
6. Which request fields and company access checks are enforced by the API layer?

### 10.6 Contract compatibility

- Keep claim_type values consistent across all modules.
- Preserve the common error envelope and correlation ID.
- Confirm the request/response contract with Participants 2, 4 and 5 before implementation is treated as final.
- Update contract tests when the module contract is approved.

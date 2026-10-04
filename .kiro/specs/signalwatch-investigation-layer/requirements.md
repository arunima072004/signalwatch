# Requirements Document

## Introduction

SignalWatch Phase 2 extends the existing BOCPD-based change detection system with an investigation, web evidence retrieval, and verification layer. The existing system detects 24 price regime changes and generates 716 investigation queries. Phase 2 must execute these queries against web search providers (Google, SerpAPI, Tavily, etc.), retrieve web evidence, and assess the cause of each price change through a multi-agent investigation system with independent verification.

This phase transforms structured investigation queries into verified causal assessments by coordinating specialized investigation agents, managing search provider interactions, extracting evidence from search results, and independently verifying evidence quality to distinguish correlation from causation. The system uses targeted query → live web search → extraction → verification, NOT RAG, embeddings, or semantic retrieval.

## Glossary

- **Investigation_System**: The Phase 2 orchestration component that coordinates hypothesis generation, agent execution, and verification
- **Hypothesis_Generator**: Component that generates multiple non-exclusive hypotheses for each ChangeEvent
- **Investigation_Agent**: Specialized agent responsible for investigating one hypothesis type (Promotion_Agent, Competitor_Agent, Product_Event_Agent, News_Agent, Retailer_Event_Agent, Supply_Agent)
- **Verification_Agent**: Independent agent that evaluates evidence quality, detects causal vs correlational claims, and identifies contradictions
- **Search_Provider**: Abstract interface for web search APIs (Google, SerpAPI, Tavily, Brave, etc.) - NOT Channel3 which is a future pricing data source
- **Mock_Search_Provider**: Testing implementation that returns predetermined results without API calls or API keys
- **Evidence**: A structured passage extracted from a search result with complete source traceability (evidence_id, event_id, hypothesis, source_url, source_domain, source_title, publication_date, retrieved_at, claim, evidence_text, evidence_type, relevance, investigator, query_id)
- **ChangeEvent**: Existing Phase 1 output - a detected price regime change with product, merchant, price, and competitive context
- **EventAssessment**: Final output containing hypotheses, evidence, verification results, and uncertainty metrics - with evidence-backed conclusions
- **Search_Query**: Structured query object containing event_id, hypothesis, query_text, purpose, priority, generated_by, product_context, merchant, date_window, identifiers (ASIN/UPC/EAN)
- **Search_Result**: Raw result from web search provider containing URL, title, snippet, and optional full content
- **Hypothesis**: Proposed explanation for a price change (PROMOTION, COMPETITOR_RESPONSE, INVENTORY_LIQUIDATION, PRODUCT_EVENT, SEASONAL_EVENT, MARKET_EVENT, MANUFACTURER_CHANGE, DATA_ISSUE) - multiple hypotheses can be SUPPORTED simultaneously
- **Orchestrator**: Component that manages agent execution, handles failures, and aggregates results
- **Repository_Interface**: Data access layer abstraction to avoid tight coupling to specific storage implementations (JSON/CSV/PostgreSQL)

## Requirements

### Requirement 1: Hypothesis Generation

**User Story:** As a pricing analyst, I want multiple non-exclusive hypotheses generated for each price change, so that I can understand all plausible explanations without forcing a single answer.

#### Acceptance Criteria

1. WHEN a ChangeEvent is provided, THE Hypothesis_Generator SHALL generate at least one hypothesis from the supported set
2. THE Hypothesis_Generator SHALL support eight hypothesis types: PROMOTION, COMPETITOR_RESPONSE, INVENTORY_LIQUIDATION, PRODUCT_EVENT, SEASONAL_EVENT, MARKET_EVENT, MANUFACTURER_CHANGE, DATA_ISSUE
3. THE Hypothesis_Generator SHALL assign multiple hypotheses to a single ChangeEvent when multiple signals are present
4. WHEN generating hypotheses, THE Hypothesis_Generator SHALL use observable signals from the ChangeEvent (is_sale, competitor_count, percentage_change, days_since_previous, availability)
5. THE Hypothesis_Generator SHALL assign signal_score or hypothesis_score to each hypothesis based on signal strength from ChangeEvent data
6. THE Hypothesis_Generator SHALL NOT use the term "confidence" for hypothesis scores to avoid implying calibrated probability
7. WHEN no strong signals are present, THE Hypothesis_Generator SHALL generate at least two hypotheses with equal signal_score
8. THE Hypothesis_Generator SHALL NOT eliminate hypotheses based on mutual exclusivity
9. FOR ALL generated hypotheses, THE Hypothesis_Generator SHALL provide a rationale based on ChangeEvent attributes
10. WHEN generating INVENTORY_LIQUIDATION hypotheses, THE Hypothesis_Generator SHALL mark them as requiring external evidence verification and SHALL NOT infer liquidation from the availability field alone

### Requirement 2: Investigation Agent Specialization

**User Story:** As a system designer, I want specialized investigation agents with distinct responsibilities, so that each hypothesis is investigated by an expert agent using appropriate query strategies.

#### Acceptance Criteria

1. THE Investigation_System SHALL implement six investigation agent types: Promotion_Agent, Competitor_Agent, Product_Event_Agent, News_Agent, Retailer_Event_Agent, Supply_Agent
2. WHEN investigating a hypothesis, THE Investigation_System SHALL select the appropriate agent based on hypothesis type
3. THE Promotion_Agent SHALL investigate specific product discount/promotion/coupon hypotheses using sale-focused queries
4. THE Competitor_Agent SHALL investigate COMPETITOR_RESPONSE hypotheses using competitor price and market share queries
5. THE Product_Event_Agent SHALL investigate product lifecycle and manufacturer events using product lifecycle and launch queries
6. THE News_Agent SHALL investigate broader external and market events using news and press coverage queries
7. THE Retailer_Event_Agent SHALL investigate merchant-wide sales, campaigns, and pricing events using retailer-specific event queries
8. THE Supply_Agent SHALL investigate INVENTORY_LIQUIDATION hypotheses using supply chain and availability queries
9. WHEN a hypothesis maps to multiple agents, THE Investigation_System SHALL execute all applicable agents
10. THE Investigation_System SHALL execute agents in parallel when no dependencies exist
11. THE Promotion_Agent SHALL focus on specific product-level discounts and promotions, NOT merchant-wide events
12. THE Retailer_Event_Agent SHALL focus on merchant-wide sales and campaigns, NOT specific product promotions
13. THE Product_Event_Agent SHALL focus on product lifecycle events (launches, discontinuations, updates), NOT general market conditions
14. THE News_Agent SHALL focus on broader market events and external factors, NOT product-specific lifecycle events

### Requirement 3: Search Provider Abstraction

**User Story:** As a developer, I want a pluggable search provider interface, so that I can swap search APIs (Google, SerpAPI, Tavily, Brave) or use mocks for testing without changing investigation logic.

#### Acceptance Criteria

1. THE Investigation_System SHALL define a Search_Provider interface with methods: search(query, num_results), get_page_content(url)
2. THE Investigation_System SHALL accept any Search_Provider implementation that satisfies the interface
3. THE Mock_Search_Provider SHALL implement the Search_Provider interface without making external API calls
4. WHEN the Mock_Search_Provider receives a search query, THE Mock_Search_Provider SHALL return predetermined search results based on query patterns
5. THE Mock_Search_Provider SHALL support configurable result sets for different query patterns
6. THE Investigation_System SHALL NOT contain hardcoded references to specific search API providers
7. WHEN a Search_Provider method fails, THE Investigation_System SHALL log the error and continue with remaining queries
8. THE Investigation_System SHALL pass search provider configuration at initialization time

### Requirement 4: Structured Search Query Generation

**User Story:** As a developer, I want structured search queries with complete context metadata, so that query execution, result tracking, and evidence provenance are fully traceable.

#### Acceptance Criteria

1. WHEN generating a search query, THE Investigation_System SHALL create a Search_Query object with ALL required fields: event_id, hypothesis, query_text, purpose, priority, generated_by
2. THE Search_Query object SHALL include product context fields: product_name, product_brand, product_category, product_model
3. THE Search_Query object SHALL include merchant identification
4. THE Search_Query object SHALL include date_window specifying the time range relevant to the ChangeEvent
5. THE Search_Query object SHALL include product identifiers when available: ASIN, UPC, EAN, SKU
6. THE Investigation_System SHALL serialize Search_Query objects to JSON with all fields preserved
7. WHEN deserializing Search_Query objects, THE Investigation_System SHALL validate that all required fields are present
8. THE Investigation_System SHALL assign unique query_id to each Search_Query for traceability
9. THE Search_Query object SHALL include execution metadata: execution_status, executed_at, search_provider_used, result_count
10. FOR ALL Search_Query objects, THE Investigation_System SHALL maintain a chain linking query_id → evidence_id for complete provenance

### Requirement 5: Evidence Extraction and Complete Provenance

**User Story:** As a pricing analyst, I want relevant passages extracted from search results with complete source traceability and provenance chain, so that I can verify claims and assess evidence quality.

#### Acceptance Criteria

1. WHEN a Search_Result is received, THE Investigation_System SHALL extract relevant passages related to the hypothesis
2. THE Investigation_System SHALL create Evidence objects containing ALL provenance fields: evidence_id, event_id, hypothesis, source_url, source_domain, source_title, publication_date, retrieved_at, claim, evidence_text, evidence_specificity, relationship_type, relevance, investigator, query_id
3. THE Investigation_System SHALL preserve the original search result URL and domain in every Evidence object
4. THE Investigation_System SHALL extract publication_date from the source page when available
5. THE Investigation_System SHALL timestamp evidence extraction with UTC time in retrieved_at field
6. WHEN multiple passages are extracted from one URL, THE Investigation_System SHALL create separate Evidence objects for each passage with the same source metadata
7. THE Investigation_System SHALL compute relevance scores based on keyword overlap and hypothesis alignment
8. THE Investigation_System SHALL classify evidence_specificity as: DIRECT (mentions specific product/merchant), INDIRECT (category/market level)
9. THE Investigation_System SHALL classify relationship_type as: CAUSAL (establishes cause-effect relationship), CORRELATIONAL (temporal alignment or co-occurrence), DESCRIPTIVE (factual description without relationship), UNKNOWN (insufficient information to classify)
10. THE Investigation_System SHALL support evidence being both DIRECT and CAUSAL simultaneously by using separate classification dimensions
11. THE Investigation_System SHALL record the investigator field indicating which agent extracted the evidence
12. FOR ALL Evidence objects, THE Investigation_System SHALL maintain a complete chain of provenance: ChangeEvent → Hypothesis → Search_Query (query_id) → Search_Result → Evidence (evidence_id)

### Requirement 6: Source Independence Detection

**User Story:** As a pricing analyst, I want to distinguish independent sources from duplicated/syndicated content, so that I can avoid counting the same article multiple times as independent confirmation.

#### Acceptance Criteria

1. THE Verification_Agent SHALL detect when multiple Evidence objects contain duplicated or syndicated content from the same original article
2. WHEN analyzing evidence pools, THE Verification_Agent SHALL classify sources as: INDEPENDENT, DUPLICATED, SYNDICATED, CONTRADICTING
3. THE Verification_Agent SHALL use indicators of duplication: identical passages, same author, same publication date, attribution statements
4. WHEN Evidence objects share source_domain, THE Verification_Agent SHALL examine content similarity to detect republication
5. THE Verification_Agent SHALL maintain a source_independence_graph showing relationships between Evidence sources
6. WHEN computing overall confidence, THE Verification_Agent SHALL weight independent sources more heavily than duplicated sources
7. THE Verification_Agent SHALL flag evidence pools where all sources are duplicated/syndicated as LOW_INDEPENDENCE
8. THE Verification_Agent SHALL identify contradicting sources that present conflicting claims about the same event
9. FOR ALL EventAssessments, THE Verification_Agent SHALL report the count of independent sources vs duplicated sources
10. THE Verification_Agent SHALL NOT treat multiple sites copying the same article as independent confirmations
11. THE Verification_Agent SHALL classify source independence using heuristic indicators and SHALL NOT claim perfect determination of independence
12. THE Verification_Agent SHALL preserve and report the signals used for independence classification (identical passages, author attribution, domain relationships) to enable human review
13. THE Verification_Agent SHALL document limitations of independence detection in EventAssessment uncertainty factors

### Requirement 7: Rigorous Independent Verification

**User Story:** As a pricing analyst, I want rigorous verification that goes beyond keyword matching, so that I can distinguish causal claims from correlational observations and understand the strength and limitations of evidence.

#### Acceptance Criteria

1. THE Verification_Agent SHALL operate independently after all investigation agents complete
2. WHEN evaluating evidence, THE Verification_Agent SHALL assess multiple dimensions: source-hypothesis alignment, product/merchant match, temporal alignment, specificity, direct vs inferred evidence, source independence, contradictions, explicit causality vs correlation
3. THE Verification_Agent SHALL classify evidence support levels as: SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS
4. THE Verification_Agent SHALL use conservative language and SHALL NOT claim "X caused Y" unless causality is genuinely established in the evidence
5. THE Verification_Agent SHALL distinguish between direct evidence (mentions specific product/merchant) and indirect evidence (category/market level)
6. THE Verification_Agent SHALL evaluate temporal alignment between evidence publication dates and ChangeEvent dates
7. THE Verification_Agent SHALL assess source authority using domain reputation, author credentials, and publication type
8. WHEN evaluating evidence, THE Verification_Agent SHALL treat causal keywords (because, due to, caused by, resulted from) as SIGNALS requiring deeper analysis, NOT as primary determinants of causality
9. WHEN evaluating causal claims, THE Verification_Agent SHALL assess: does the source discuss the same product, does it discuss the same merchant when relevant, does it fall within the event date window, does it explicitly state a relationship between the hypothesized cause and the price change or event, is the relationship directly stated vs inferred vs only temporally correlated, is the evidence specific or generic, is there independent corroboration, is there contradictory evidence
10. WHEN evidence contains only temporal alignment without causal claims, THE Verification_Agent SHALL classify as CONSISTENT_WITH not SUPPORTS
11. THE Verification_Agent SHALL detect contradictory evidence and flag both conflicting pieces with explanations
12. THE Verification_Agent SHALL assign quality scores based on: source authority, temporal proximity, specificity, product/merchant alignment, causal strength, independence
13. THE Verification_Agent SHALL identify evidence specificity: quantitative data, named entities, dates, specific claims vs vague statements
14. THE Verification_Agent SHALL NOT force selection of a single hypothesis when multiple hypotheses have evidence support
14. FOR ALL verification results, THE Verification_Agent SHALL provide human-readable explanations of support level decisions

### Requirement 8: Multiple Hypothesis Support and Confidence Computation

**User Story:** As a pricing analyst, I want the system to support multiple hypotheses simultaneously without forcing a single winner, so that I can understand when multiple explanations are valid.

#### Acceptance Criteria

1. THE Investigation_System SHALL support MULTIPLE hypotheses being marked as SUPPORTED simultaneously for a single ChangeEvent
2. THE Investigation_System SHALL NOT force selection of a single winning hypothesis
3. WHEN multiple hypotheses have sufficient evidence support, THE EventAssessment SHALL report all supported hypotheses with their individual support levels
4. THE Investigation_System SHALL compute confidence scores based on: evidence quality, specificity, temporal alignment, product/merchant alignment, source independence, contradictions, coverage, missing information
5. THE Investigation_System SHALL NOT apply a "hypothesis diversity penalty" that reduces confidence when multiple hypotheses are supported
6. THE Investigation_System SHALL distinguish between "high confidence in multiple causes" and "uncertain due to insufficient evidence"
7. WHEN computing confidence, THE Investigation_System SHALL weight source independence, evidence specificity, and causal strength more heavily than hypothesis count
8. THE EventAssessment SHALL include per-hypothesis support levels: SUPPORTED, PARTIALLY_SUPPORTED, INSUFFICIENT_EVIDENCE, NOT_SUPPORTED
9. WHEN a hypothesis receives SUPPORTED status, THE EventAssessment SHALL include the supporting evidence IDs and verification details
10. FOR ALL EventAssessments, THE Investigation_System SHALL provide a clear explanation of why multiple hypotheses may be simultaneously valid
11. THE Investigation_System SHALL maintain transparent and documented confidence aggregation formulas
12. THE Investigation_System SHALL preserve component scores in confidence computation: source_quality, hypothesis_alignment, product_merchant_match, temporal_alignment, specificity, source_independence, causal_strength, contradiction_level
13. THE Investigation_System SHALL document the overall confidence formula explicitly in system documentation
14. THE EventAssessment SHALL include component confidence scores alongside overall confidence to enable human review and validation

### Requirement 9: Data Model Implementation

**User Story:** As a developer, I want well-defined data models for all Phase 2 entities with complete provenance fields, so that the system maintains type safety and serialization consistency.

#### Acceptance Criteria

1. THE Investigation_System SHALL define a PriceObservation model with fields: product_id, merchant, price, observed_at, change_direction, percentage_change
2. THE Investigation_System SHALL define a Hypothesis model with fields: hypothesis_type, signal_score, rationale, assigned_agents, requires_external_evidence
3. THE Investigation_System SHALL define a SearchQuery model with ALL fields from Requirement 4: event_id, hypothesis, query_text, purpose, priority, generated_by, product_context, merchant, date_window, identifiers, query_id, execution_metadata
4. THE Investigation_System SHALL define a SearchResult model with fields: url, title, snippet, full_content, retrieved_at, search_provider, source_domain
5. THE Investigation_System SHALL define an Evidence model with ALL provenance fields from Requirement 5: evidence_id, event_id, hypothesis, source_url, source_domain, source_title, publication_date, retrieved_at, claim, evidence_text, evidence_specificity, relationship_type, relevance, investigator, query_id
6. THE Investigation_System SHALL define an EventAssessment model with fields: event_id, hypotheses, evidence_pool, verification_results, hypothesis_support_levels, overall_confidence, assessment_timestamp, uncertainty_factors, independent_source_count
7. THE Investigation_System SHALL implement JSON serialization for all data models
8. THE Investigation_System SHALL implement JSON deserialization for all data models with validation
9. WHEN deserializing invalid JSON, THE Investigation_System SHALL raise a descriptive error indicating the validation failure
10. THE Investigation_System SHALL define a VerificationResult model with fields: evidence_id, quality_score, support_level, contradictions, verification_notes, source_independence_classification

### Requirement 10: Orchestration and Error Handling

**User Story:** As a system operator, I want robust orchestration that handles agent failures gracefully and preserves uncertainty, so that partial results are still useful and system reliability is maintained.

#### Acceptance Criteria

1. THE Orchestrator SHALL coordinate the execution sequence: Hypothesis_Generator → Investigation_Agents → Verification_Agent → EventAssessment
2. WHEN an Investigation_Agent fails, THE Orchestrator SHALL log the failure and continue with remaining agents
3. WHEN a Search_Provider fails, THE Orchestrator SHALL retry up to a configurable maximum (default: 3 attempts)
4. WHEN all retries fail, THE Orchestrator SHALL record the failure in the EventAssessment and continue
5. THE Orchestrator SHALL execute independent Investigation_Agents in parallel when possible
6. THE Orchestrator SHALL wait for all Investigation_Agents to complete before invoking the Verification_Agent
7. WHEN evidence is insufficient for a hypothesis, THE Orchestrator SHALL preserve the hypothesis in the EventAssessment with an INSUFFICIENT_EVIDENCE status
8. THE Orchestrator SHALL compute an overall assessment uncertainty metric based on: evidence count, verification scores, agent failures, contradictions, source independence - NOT hypothesis diversity
9. THE Orchestrator SHALL NOT discard hypotheses due to lack of evidence
10. THE Orchestrator SHALL serialize the complete EventAssessment to JSON after verification completes

### Requirement 11: Integration with Existing System

**User Story:** As a system maintainer, I want Phase 2 to integrate seamlessly with Phase 1 outputs without modifying the existing pipeline, so that the 112 existing tests continue to pass and backward compatibility is maintained.

#### Acceptance Criteria

1. THE Investigation_System SHALL read ChangeEvent objects from the existing `data/events/change_events.json` file
2. THE Investigation_System SHALL NOT modify any Phase 1 source files in `src/data/`, `src/bocpd/`, `src/features/`, `src/events/`
3. THE Investigation_System SHALL NOT modify any Phase 1 test files
4. WHEN the Investigation_System is executed, ALL 112 existing Phase 1 tests SHALL continue to pass
5. THE Investigation_System SHALL write outputs to a new directory `data/assessments/` without modifying existing output directories
6. THE Investigation_System SHALL create a new source directory `src/investigation/` for all Phase 2 code
7. THE Investigation_System SHALL create new test files `test_investigation_*.py` without modifying existing test files
8. THE Investigation_System SHALL reuse existing query generation from Phase 1 when applicable
9. THE Investigation_System SHALL preserve the existing ChangeEvent schema without additions or modifications
10. WHEN Phase 1 generates new ChangeEvents, THE Investigation_System SHALL process them without requiring code changes

### Requirement 12: Historical Investigation Entry Point

**User Story:** As a pricing analyst, I want to investigate historical events from Phase 1, so that I can run the complete investigation pipeline on existing detected price changes.

#### Acceptance Criteria

1. THE Investigation_System SHALL provide a script at `scripts/investigate_event.py` for historical event investigation
2. WHEN the script is invoked with `python scripts/investigate_event.py --event-id E001`, THE Investigation_System SHALL run the complete pipeline on that event
3. THE script SHALL load the ChangeEvent from Phase 1 data files using the provided event_id
4. THE script SHALL execute: Hypothesis_Generator → Investigation_Agents → Web Search → Evidence Extraction → Verification → EventAssessment
5. THE script SHALL work with REAL web search providers when API keys are configured
6. THE script SHALL work with Mock_Search_Provider when no API keys are available (for testing)
7. THE script SHALL output the complete EventAssessment with evidence-backed conclusions
8. THE script SHALL save the EventAssessment to `data/assessments/{event_id}_assessment.json`
9. WHEN web search returns REAL webpages, THE script SHALL extract REAL evidence from those pages
10. THE script SHALL provide progress logging showing each pipeline stage completion

### Requirement 13: Testing Requirements and Mocks

**User Story:** As a developer, I want comprehensive unit tests that use mocks for external services, so that tests run without API keys, complete in seconds, and verify system behavior independently of external dependencies.

#### Acceptance Criteria

1. THE Investigation_System test suite SHALL use Mock_Search_Provider for all search-related tests
2. THE Investigation_System test suite SHALL NOT require API keys or network access
3. THE Investigation_System test suite SHALL complete all tests in under 60 seconds
4. THE Mock_Search_Provider SHALL support configurable response scenarios: success, empty results, timeout, malformed response
5. WHEN testing evidence extraction, THE Investigation_System SHALL use mock Search_Results with known content
6. WHEN testing verification, THE Investigation_System SHALL use mock Evidence pools with known causal/correlational claims
7. THE Investigation_System SHALL provide example configurations showing Mock_Search_Provider usage
8. THE Investigation_System SHALL provide integration test examples showing real Search_Provider usage (marked as requiring API keys)
9. THE Investigation_System test suite SHALL verify that existing 112 Phase 1 tests still pass after Phase 2 integration
10. THE Investigation_System SHALL implement property-based tests for the round-trip property: serialize(deserialize(json)) == json for all data models

### Requirement 14: Uncertainty Quantification and Reporting

**User Story:** As a pricing analyst, I want explicit uncertainty metrics in every assessment, so that I can understand confidence levels and avoid over-interpreting results.

#### Acceptance Criteria

1. THE EventAssessment SHALL include an overall_confidence score between 0.0 and 1.0
2. THE EventAssessment SHALL include per-hypothesis support_confidence scores
3. THE EventAssessment SHALL include a uncertainty_factors list explaining sources of uncertainty
4. WHEN evidence is contradictory, THE EventAssessment SHALL increase uncertainty and document the contradiction
5. WHEN evidence count is low (fewer than 3 independent pieces per hypothesis), THE EventAssessment SHALL increase uncertainty
6. WHEN verification identifies correlational-only evidence, THE EventAssessment SHALL increase uncertainty
7. WHEN computing confidence, THE EventAssessment SHALL consider evidence quality, specificity, temporal alignment, product/merchant alignment, source independence, contradictions, coverage, and missing information
8. THE EventAssessment SHALL distinguish between "high confidence in a single cause" and "multiple plausible causes with uncertain weights"
9. THE EventAssessment SHALL NOT select a single winning hypothesis when multiple hypotheses have evidence support above threshold
10. THE EventAssessment SHALL include a human-readable summary explaining the assessment and uncertainty level
11. THE EventAssessment SHALL maintain transparent and explainable confidence computation with preserved component scores
12. THE EventAssessment SHALL include component confidence scores: source_quality, hypothesis_alignment, product_merchant_match, temporal_alignment, specificity, source_independence, causal_strength, contradiction_level
13. THE EventAssessment SHALL document the confidence aggregation formula explicitly to enable human validation
14. THE EventAssessment SHALL NOT use opaque black-box confidence computation that obscures how individual factors contributed to overall confidence

### Requirement 15: Search Result Parser

**User Story:** As a developer, I want a robust parser for search result HTML and text content, so that evidence extraction handles malformed content gracefully.

#### Acceptance Criteria

1. THE Investigation_System SHALL implement a Search_Result_Parser component
2. WHEN parsing HTML content, THE Search_Result_Parser SHALL extract text while preserving paragraph boundaries
3. WHEN parsing HTML content, THE Search_Result_Parser SHALL remove script tags, style tags, and navigation elements
4. WHEN encountering malformed HTML, THE Search_Result_Parser SHALL extract available text without raising errors
5. THE Search_Result_Parser SHALL handle character encoding detection and conversion to UTF-8
6. WHEN content contains non-text elements (images, videos), THE Search_Result_Parser SHALL extract alt text and captions
7. THE Search_Result_Parser SHALL truncate excessively long content (greater than 100KB) and log the truncation
8. THE Search_Result_Parser SHALL detect and handle common anti-scraping patterns (CAPTCHAs, rate limit pages) by returning empty content and logging the detection
9. FOR ALL parsing operations, THE Search_Result_Parser SHALL return a structured ParsedContent object with: extracted_text, parse_success, error_messages, truncated
10. THE Search_Result_Parser SHALL implement a pretty printer that formats ParsedContent objects for display

### Requirement 16: Data Storage and Repository Abstraction

**User Story:** As a developer, I want clean repository/data-access interfaces, so that storage implementation can evolve without tight coupling to specific formats.

#### Acceptance Criteria

1. THE Investigation_System SHALL define a Repository_Interface for data access operations
2. THE Repository_Interface SHALL support operations: save_event_assessment, load_event_assessment, list_assessments, save_evidence, load_evidence_by_event
3. THE Investigation_System SHALL provide a JSON_Repository implementation using JSON files
4. THE Investigation_System SHALL provide a CSV_Repository implementation for tabular exports
5. THE Investigation_System SHALL NOT tightly couple investigation logic to specific storage formats
6. WHEN switching storage implementations, THE Investigation_System SHALL require NO changes to investigation or verification logic
7. THE Investigation_System SHALL accept Repository_Interface implementation at initialization
8. THE Repository_Interface SHALL handle file I/O errors gracefully and return descriptive error messages
9. THE Investigation_System SHALL NOT implement PostgreSQL or vector databases in this phase
10. FOR ALL data access operations, THE Investigation_System SHALL use the Repository_Interface abstraction

### Requirement 17: No RAG or Semantic Retrieval

**User Story:** As a system architect, I want to avoid premature complexity, so that the system remains maintainable and testable without heavyweight infrastructure.

#### Acceptance Criteria

1. THE Investigation_System SHALL NOT implement RAG (Retrieval-Augmented Generation) in this phase
2. THE Investigation_System SHALL NOT use embeddings or vector similarity for evidence retrieval
3. THE Investigation_System SHALL NOT implement vector databases (Pinecone, Weaviate, ChromaDB, etc.)
4. THE Investigation_System SHALL NOT implement semantic retrieval systems
5. THE Investigation_System SHALL use targeted query → live web search → extraction → verification pattern
6. THE Investigation_System SHALL use keyword matching and structured query formulation for search
7. WHEN evaluating evidence relevance, THE Investigation_System MAY use simple keyword overlap or exact matching
8. THE Investigation_System SHALL focus on query quality and verification rigor rather than semantic retrieval complexity
9. THE Investigation_System SHALL document the decision to avoid RAG in this phase
10. WHERE semantic capabilities are needed in future phases, THE Investigation_System SHALL maintain compatibility with the existing search provider abstraction

### Requirement 18: Configuration and Extensibility

**User Story:** As a system operator, I want configurable parameters for all thresholds and limits, so that I can tune the system for different use cases without code changes.

#### Acceptance Criteria

1. THE Investigation_System SHALL accept a configuration object at initialization with parameters: max_retries, relevance_threshold, evidence_minimum, verification_threshold, parallel_agent_limit
2. THE Investigation_System SHALL provide default configuration values for all parameters
3. THE Investigation_System SHALL validate configuration values at initialization and raise errors for invalid values
4. WHEN configuration is invalid, THE Investigation_System SHALL provide descriptive error messages indicating valid ranges
5. THE Investigation_System SHALL support loading configuration from JSON files
6. THE Investigation_System SHALL support loading configuration from environment variables
7. THE Investigation_System SHALL log the active configuration at system initialization
8. THE Investigation_System SHALL implement a configuration schema validator
9. THE Investigation_System SHALL provide example configuration files for common scenarios (testing, production, high-confidence)
10. WHERE custom Investigation_Agents are implemented, THE Investigation_System SHALL support registration of new agent types without modifying core orchestration code

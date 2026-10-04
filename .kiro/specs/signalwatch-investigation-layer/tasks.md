# Implementation Plan: SignalWatch Phase 2 - Investigation Layer

## Overview

This implementation plan covers the development of Phase 2 of the SignalWatch system, which adds an investigation layer to explain price change events detected in Phase 1. The system generates hypotheses, searches for evidence using LIVE WEB SEARCH (Google/SerpAPI/Tavily - NOT RAG, NOT embeddings), verifies findings through multi-dimensional assessment, and produces comprehensive assessments supporting multiple simultaneous hypotheses.

**CRITICAL ARCHITECTURE NOTES:**
- Uses **targeted queries → live web search → HTML parsing → evidence extraction → verification**
- **NOT RAG**: No embeddings, no vector databases, no semantic retrieval
- **Web Search Providers**: Google/SerpAPI/Tavily via API (MockSearchProvider for testing)
- **NOT Channel3**: Channel3 is a future Phase 1 pricing data source, not used in Phase 2 investigation
- **Multiple Hypothesis Support**: System supports multiple SUPPORTED hypotheses simultaneously without forcing winner selection
- **Complete Provenance**: Tracks full chain: ChangeEvent → Hypothesis → SearchQuery (query_id) → SearchResult → Evidence (evidence_id)
- **Source Independence**: Detects and discounts duplicated/syndicated content to avoid false confidence

## Tasks

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T001"] },
    { "id": 1, "tasks": ["T002", "T003"] },
    { "id": 2, "tasks": ["T004", "T005", "T006", "T007", "T008"] },
    { "id": 3, "tasks": ["T009"] },
    { "id": 4, "tasks": ["T010", "T015"] },
    { "id": 5, "tasks": ["T011"] },
    { "id": 6, "tasks": ["T012", "T013"] },
    { "id": 7, "tasks": ["T014", "T016"] },
    { "id": 8, "tasks": ["T017", "T018", "T019", "T020", "T021", "T022"] },
    { "id": 9, "tasks": ["T023"] },
    { "id": 10, "tasks": ["T024", "T025"] },
    { "id": 11, "tasks": ["T026"] },
    { "id": 12, "tasks": ["T027", "T028", "T029", "T030", "T031", "T032", "T033", "T034", "T035", "T036", "T037", "T038", "T039", "T040"] },
    { "id": 13, "tasks": ["T041", "T042"] },
    { "id": 14, "tasks": ["T043"] },
    { "id": 15, "tasks": ["T044"] }
  ]
}
```

### Phase 1: Foundation (T001-T007)

#### T001: Module Structure Setup
**Status**: pending  
**Priority**: required  
**Description**: Create the directory structure and empty __init__.py files for all Phase 2 modules.

**Acceptance Criteria**:
- [ ] 1. Directory `src/investigation/` created with __init__.py
- [ ] 2. Directory `src/investigation/agents/` created with __init__.py
- [ ] 3. Directory `src/search/` created with __init__.py
- [ ] 4. Directory `src/evidence/` created with __init__.py
- [ ] 5. Directory `src/models/` created with __init__.py
- [ ] 6. Directory `src/config/` created with __init__.py
- [ ] 7. Directory `data/assessments/` created
- [ ] 8. Directory `tests/investigation/` created with __init__.py
- [ ] 9. All existing Phase 1 tests pass (pytest tests/ --ignore=tests/investigation/)

**Sub-tasks**:
1. Create directory structure using mkdir
2. Create __init__.py files in each Python package
3. Run existing test suite to establish baseline

---

#### T002: Data Models - Core
**Status**: pending  
**Priority**: required  
**Dependencies**: T001  
**Description**: Implement core data models: Hypothesis, PriceObservation, ChangeEvent wrapper with updated terminology and complete fields.

**Acceptance Criteria**:
- [ ] 1. File `src/models/hypothesis.py` created with Hypothesis class
- [ ] 2. Hypothesis has fields: hypothesis_id, hypothesis_type, **signal_score**, rationale, assigned_agents, generated_at, **requires_external_evidence**
- [ ] 3. **CRITICAL**: Use `signal_score` NOT `confidence` to avoid implying calibrated probability
- [ ] 4. hypothesis_type is an enum: PROMOTION, COMPETITOR_RESPONSE, INVENTORY_LIQUIDATION, PRODUCT_EVENT, SEASONAL_EVENT, MARKET_EVENT, MANUFACTURER_CHANGE, DATA_ISSUE
- [ ] 5. Hypothesis implements to_dict() and from_dict() for JSON serialization
- [ ] 6. Hypothesis validates signal_score in range [0.0, 1.0]
- [ ] 7. requires_external_evidence is boolean flag (True for INVENTORY_LIQUIDATION, PRODUCT_EVENT, MARKET_EVENT, MANUFACTURER_CHANGE)
- [ ] 8. Unit tests verify serialization round-trip property
- [ ] 9. Unit tests verify validation errors for invalid signal_score

**Implementation Notes**:
```python
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Any

class HypothesisType(str, Enum):
    PROMOTION = "PROMOTION"
    COMPETITOR_RESPONSE = "COMPETITOR_RESPONSE"
    # ... other types

@dataclass
class Hypothesis:
    hypothesis_id: str
    hypothesis_type: HypothesisType
    signal_score: float  # NOT "confidence"
    rationale: str
    assigned_agents: List[str]
    generated_at: str
    requires_external_evidence: bool  # NEW: flag for hypotheses requiring web evidence
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Hypothesis':
        return cls(**data)
```

---

#### T003: Configuration System
**Status**: pending  
**Priority**: required  
**Dependencies**: T001  
**Description**: Implement configuration system with JSON file and environment variable support.

**Acceptance Criteria**:
- [ ] 1. File `src/config/investigation_config.py` created with InvestigationConfig class
- [ ] 2. Config has parameters: max_retries, relevance_threshold, evidence_minimum, verification_threshold, parallel_agent_limit, results_per_query, search_timeout
- [ ] 3. Config loads from JSON file if provided
- [ ] 4. Config loads from environment variables (INVESTIGATION_MAX_RETRIES, etc.)
- [ ] 5. Config provides sensible defaults: max_retries=3, relevance_threshold=0.3, evidence_minimum=3, verification_threshold=0.6, parallel_agent_limit=6
- [ ] 6. Config validates ranges at initialization
- [ ] 7. Config raises ConfigurationError with descriptive message for invalid values
- [ ] 8. Unit tests verify JSON loading
- [ ] 9. Unit tests verify environment variable loading
- [ ] 10. Unit tests verify validation errors

---

#### T004: Data Models - Search
**Status**: pending  
**Priority**: required  
**Dependencies**: T002  
**Description**: Implement search-related data models: SearchQuery (STRUCTURED with ALL context fields), SearchResult.

**Acceptance Criteria**:
- [ ] 1. File `src/models/search.py` created with SearchQuery and SearchResult classes
- [ ] 2. **SearchQuery has ALL structured fields**: query_id, query_text, event_id, hypothesis, purpose, priority, generated_by, product_context (name/brand/category/model), merchant, date_window, identifiers (ASIN/UPC/EAN/SKU), execution_metadata
- [ ] 3. **CRITICAL**: SearchQuery is NOT just a string - it's a complete structured object with context
- [ ] 4. execution_metadata includes: execution_status, executed_at, search_provider_used, result_count
- [ ] 5. SearchResult has fields: result_id, query_id, url, title, snippet, full_content, retrieved_at, search_provider, source_domain
- [ ] 6. Both implement to_dict() and from_dict()
- [ ] 7. URL field validates as proper URL format (https://)
- [ ] 8. query_id generates deterministic IDs for traceability
- [ ] 9. Unit tests verify serialization with all fields
- [ ] 10. Unit tests verify URL validation
- [ ] 11. Unit tests verify provenance chain: query_id links to evidence_id

**Implementation Notes**:
```python
@dataclass
class ProductContext:
    product_name: str
    product_brand: Optional[str]
    product_category: Optional[str]
    product_model: Optional[str]

@dataclass
class Identifiers:
    asin: Optional[str]
    upc: Optional[str]
    ean: Optional[str]
    sku: Optional[str]

@dataclass
class ExecutionMetadata:
    execution_status: str = "pending"  # pending, completed, failed
    executed_at: Optional[str] = None
    search_provider_used: Optional[str] = None
    result_count: int = 0

@dataclass
class SearchQuery:
    query_id: str
    query_text: str
    event_id: str
    hypothesis: str
    purpose: str
    priority: int
    generated_by: str  # agent name
    product_context: ProductContext
    merchant: str
    date_window: str  # e.g., "2023-10 to 2023-11"
    identifiers: Identifiers
    execution_metadata: ExecutionMetadata
```

---

#### T005: Data Models - Evidence
**Status**: pending  
**Priority**: required  
**Dependencies**: T002  
**Description**: Implement evidence data models with COMPLETE PROVENANCE CHAIN (15+ fields including all source metadata).

**Acceptance Criteria**:
- [ ] 1. File `src/models/evidence.py` created with Evidence and ParsedContent classes
- [ ] 2. **Evidence has ALL provenance fields (15+)**: evidence_id, event_id, hypothesis, source_url, source_domain, source_title, publication_date, retrieved_at, claim, evidence_text, evidence_type, relevance, investigator, query_id, search_result_id
- [ ] 3. **CRITICAL**: Complete provenance chain maintained: ChangeEvent → Hypothesis → SearchQuery (query_id) → SearchResult → Evidence (evidence_id)
- [ ] 4. ParsedContent has fields: extracted_text, parse_success, error_messages, truncated
- [ ] 5. Evidence validates passage_text max length 1000 characters
- [ ] 6. Evidence validates relevance in range [0.0, 1.0]
- [ ] 7. evidence_type enum: DIRECT, INDIRECT, CAUSAL, CORRELATIONAL
- [ ] 8. investigator field records which agent extracted the evidence
- [ ] 9. source_domain extracted from source_url for independence analysis
- [ ] 10. publication_date extracted from page metadata when available
- [ ] 11. Both implement to_dict() and from_dict()
- [ ] 12. Unit tests verify serialization with all provenance fields
- [ ] 13. Unit tests verify validation
- [ ] 14. Unit tests verify provenance chain integrity

**Implementation Notes**:
```python
class EvidenceType(str, Enum):
    DIRECT = "DIRECT"           # Mentions specific product/merchant
    INDIRECT = "INDIRECT"       # Category/market level
    CAUSAL = "CAUSAL"          # Contains causal language
    CORRELATIONAL = "CORRELATIONAL"  # Temporal alignment only

@dataclass
class Evidence:
    evidence_id: str
    event_id: str
    hypothesis: str
    source_url: str
    source_domain: str  # Extracted from URL for independence analysis
    source_title: str
    publication_date: Optional[str]  # Extracted from page when available
    retrieved_at: str  # UTC timestamp
    claim: str  # Short summary of the claim
    evidence_text: str  # Full passage (max 1000 chars)
    evidence_type: EvidenceType
    relevance: float  # [0.0, 1.0]
    investigator: str  # Agent name that extracted this
    query_id: str  # Links back to SearchQuery
    search_result_id: str  # Links to SearchResult
```

---

#### T006: Data Models - Verification
**Status**: pending  
**Priority**: required  
**Dependencies**: T002  
**Description**: Implement verification data models with multi-dimensional assessment and source independence tracking.

**Acceptance Criteria**:
- [ ] 1. File `src/models/verification.py` created with VerificationResult and HypothesisSupport classes
- [ ] 2. VerificationResult has fields: evidence_id, quality_score, support_level, contradictions, verification_notes, **source_independence_classification**, **multi_dimensional_scores**
- [ ] 3. support_level enum: **SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS** (5 levels, not 3)
- [ ] 4. source_independence_classification enum: INDEPENDENT, DUPLICATED, SYNDICATED, CONTRADICTING
- [ ] 5. multi_dimensional_scores dict with 8 criteria: source_hypothesis_alignment, product_merchant_match, temporal_alignment, specificity, direct_vs_inferred, source_independence, contradictions, causality_vs_correlation
- [ ] 6. HypothesisSupport has fields: hypothesis_type, support_status, supporting_evidence, contradicting_evidence, **multiple_hypotheses_support_enabled**
- [ ] 7. **CRITICAL**: System supports multiple SUPPORTED hypotheses simultaneously
- [ ] 8. Both implement to_dict() and from_dict()
- [ ] 9. Unit tests verify serialization
- [ ] 10. Unit tests verify multiple hypothesis support (no forced winner selection)

**Implementation Notes**:
```python
class SupportLevel(str, Enum):
    SUPPORTS = "SUPPORTS"  # Strong causal evidence
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"  # Some evidence
    CONSISTENT_WITH = "CONSISTENT_WITH"  # Correlational only
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTRADICTS = "CONTRADICTS"  # Conflicting evidence

class SourceIndependence(str, Enum):
    INDEPENDENT = "INDEPENDENT"  # Unique source
    DUPLICATED = "DUPLICATED"  # Copy of same article
    SYNDICATED = "SYNDICATED"  # Republished content
    CONTRADICTING = "CONTRADICTING"  # Conflicting claims

@dataclass
class VerificationResult:
    evidence_id: str
    quality_score: float
    support_level: SupportLevel
    contradictions: List[str]
    verification_notes: str
    source_independence_classification: SourceIndependence
    multi_dimensional_scores: Dict[str, float]  # 8 criteria scores
```

---

#### T007: Data Models - Assessment
**Status**: pending  
**Priority**: required  
**Dependencies**: T002, T005, T006  
**Description**: Implement final assessment data model with multiple hypothesis support and source independence metrics.

**Acceptance Criteria**:
- [ ] 1. File `src/models/assessment.py` created with EventAssessment class
- [ ] 2. EventAssessment has fields: event_id, event_summary, hypotheses, evidence_pool, verification_results, hypothesis_support, overall_confidence, uncertainty_factors, assessment_timestamp, human_readable_summary, **independent_source_count**, **duplicated_source_count**, **multiple_hypotheses_support**
- [ ] 3. hypotheses is List[Hypothesis]
- [ ] 4. evidence_pool is List[Evidence]
- [ ] 5. verification_results is List[VerificationResult]
- [ ] 6. hypothesis_support is List[HypothesisSupport]
- [ ] 7. overall_confidence in range [0.0, 1.0]
- [ ] 8. uncertainty_factors is List[str] with human-readable explanations
- [ ] 9. **CRITICAL**: multiple_hypotheses_support flag indicates multiple SUPPORTED hypotheses (no forced winner)
- [ ] 10. independent_source_count vs duplicated_source_count tracked separately
- [ ] 11. Implements to_dict() and from_dict() with nested object handling
- [ ] 12. Unit tests verify complex serialization
- [ ] 13. Unit tests verify multiple hypothesis support scenarios

---

### Phase 2: Search Infrastructure (T008-T009)

#### T008: Search Provider Interface
**Status**: pending  
**Priority**: required  
**Dependencies**: T003, T004  
**Description**: Implement abstract search provider interface for pluggable web search (Google/SerpAPI/Tavily - NOT Channel3, NOT RAG).

**Acceptance Criteria**:
- [ ] 1. File `src/search/provider_interface.py` created with SearchProvider abstract class
- [ ] 2. Interface defines async method: search(query: str, num_results: int) -> List[SearchResult]
- [ ] 3. Interface defines async method: get_page_content(url: str) -> Optional[str]
- [ ] 4. Interface defines method: get_provider_name() -> str
- [ ] 5. SearchProviderError exception class defined
- [ ] 6. **CRITICAL**: Documentation clarifies this is for LIVE WEB SEARCH (Google/SerpAPI/Tavily), NOT Channel3 (future Phase 1 data source), NOT RAG/embeddings
- [ ] 7. Documentation strings explain expected behavior
- [ ] 8. Type hints are complete
- [ ] 9. API keys loaded from environment variables, NEVER hardcoded

**Implementation Notes**:
```python
from abc import ABC, abstractmethod
from typing import List, Optional

class SearchProvider(ABC):
    """
    Abstract interface for web search providers (Google, SerpAPI, Tavily, etc.)
    
    CRITICAL NOTES:
    - This is for LIVE WEB SEARCH against public internet
    - NOT Channel3 (Channel3 is future Phase 1 pricing data source)
    - NOT RAG (no embeddings, no vector database)
    - API keys must come from environment variables
    """
    
    @abstractmethod
    async def search(self, query: str, num_results: int = 10) -> List[SearchResult]:
        """Execute live web search and return results."""
        pass
    
    @abstractmethod
    async def get_page_content(self, url: str) -> Optional[str]:
        """Fetch full HTML content from URL."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider name for logging and provenance tracking."""
        pass
```

---

#### T009: Mock Search Provider
**Status**: pending  
**Priority**: required  
**Dependencies**: T008  
**Description**: Implement mock search provider for testing.

**Acceptance Criteria**:
- [ ] 1. File `src/search/mock_provider.py` created with MockSearchProvider class
- [ ] 2. MockSearchProvider implements SearchProvider interface
- [ ] 3. Constructor accepts optional result_config: Dict[str, List[SearchResult]]
- [ ] 4. search() matches query patterns case-insensitively and returns configured results
- [ ] 5. search() returns empty list for unmatched patterns
- [ ] 6. get_page_content() returns mock HTML based on URL patterns
- [ ] 7. get_provider_name() returns "mock"
- [ ] 8. MockSearchProvider tracks call_count and query_history for testing
- [ ] 9. Default result set includes patterns: "sale", "competitor", "inventory", "launch", "news"
- [ ] 10. Unit tests verify pattern matching
- [ ] 11. Unit tests verify call tracking

---

### Phase 3: Evidence Processing (T010-T013)

#### T010: HTML/Text Parser
**Status**: pending  
**Priority**: required  
**Dependencies**: T005  
**Description**: Implement robust HTML and text content parser (NO RAG, just HTML → text extraction).

**Acceptance Criteria**:
- [ ] 1. File `src/evidence/parser.py` created with SearchResultParser class
- [ ] 2. Parser handles HTML content using BeautifulSoup or lxml
- [ ] 3. Parser removes script, style, header, footer, nav tags
- [ ] 4. Parser preserves paragraph boundaries with double newlines
- [ ] 5. Parser handles plain text content (returns as-is)
- [ ] 6. Parser detects anti-scraping patterns (captcha keywords, HTTP 429)
- [ ] 7. Parser truncates content exceeding 100KB
- [ ] 8. Parser handles character encoding (UTF-8, ISO-8859-1, Windows-1252)
- [ ] 9. Parser extracts source_title from <title> tag
- [ ] 10. Parser extracts publication_date from meta tags when available
- [ ] 11. Parser returns ParsedContent with success/error information
- [ ] 12. Parser never raises exceptions, always returns ParsedContent
- [ ] 13. **CRITICAL**: This is simple HTML parsing, NOT RAG, NOT embeddings, NOT semantic retrieval
- [ ] 14. Unit tests verify HTML parsing
- [ ] 15. Unit tests verify anti-scraping detection
- [ ] 16. Unit tests verify truncation
- [ ] 17. Unit tests verify encoding handling
- [ ] 18. Unit tests verify malformed HTML handling

---

#### T011: Relevance Scorer
**Status**: pending  
**Priority**: required  
**Dependencies**: T005, T010  
**Description**: Implement passage relevance scoring.

**Acceptance Criteria**:
- [ ] 1. File `src/evidence/scorer.py` created with RelevanceScorer class
- [ ] 2. Scorer computes relevance score in range [0.0, 1.0]
- [ ] 3. Scoring uses 4 factors: entity_match (0.4), keyword_match (0.3), temporal_signals (0.2), numeric_signals (0.1)
- [ ] 4. entity_match checks for product name, brand, merchant
- [ ] 5. keyword_match uses hypothesis-specific keyword sets
- [ ] 6. temporal_signals detects date mentions
- [ ] 7. numeric_signals detects prices and percentages
- [ ] 8. Scorer is configurable with min_relevance_threshold
- [ ] 9. Unit tests verify each scoring factor independently
- [ ] 10. Unit tests verify weighted combination
- [ ] 11. Unit tests verify threshold filtering

---

#### T012: Evidence Extractor
**Status**: pending  
**Priority**: required  
**Dependencies**: T010, T011  
**Description**: Implement evidence extraction from search results with COMPLETE PROVENANCE tracking (15+ fields).

**Acceptance Criteria**:
- [ ] 1. File `src/evidence/extractor.py` created with EvidenceExtractor class
- [ ] 2. Extractor uses SearchResultParser and RelevanceScorer
- [ ] 3. extract() takes SearchResult, Hypothesis, ChangeEvent, **SearchQuery** and returns List[Evidence]
- [ ] 4. Extraction segments text into passages (100-1000 characters)
- [ ] 5. Extraction scores each passage and filters by threshold
- [ ] 6. **CRITICAL**: Extraction creates Evidence objects with COMPLETE PROVENANCE (15+ fields)
- [ ] 7. Extraction generates deterministic evidence IDs (SHA-256 hash of content + metadata)
- [ ] 8. Extraction limits to 10 passages per search result
- [ ] 9. Extraction populates ALL provenance fields: evidence_id, event_id, hypothesis, source_url, source_domain, source_title, publication_date, retrieved_at, claim, evidence_text, evidence_type, relevance, investigator, query_id, search_result_id
- [ ] 10. Extraction maintains provenance chain: ChangeEvent → Hypothesis → SearchQuery (query_id) → SearchResult → Evidence (evidence_id)
- [ ] 11. Unit tests verify passage segmentation
- [ ] 12. Unit tests verify evidence creation with all fields populated
- [ ] 13. Unit tests verify provenance tracking
- [ ] 14. Unit tests verify provenance chain integrity

---

### Phase 4: Source Independence and Verification (T013-T015)

#### T013: Source Independence Detector
**Status**: pending  
**Priority**: required  
**Dependencies**: T005, T012  
**Description**: NEW TASK - Implement source independence detection to distinguish independent sources from duplicated/syndicated content.

**Acceptance Criteria**:
- [ ] 1. File `src/evidence/source_independence.py` created with SourceIndependenceDetector class
- [ ] 2. Detector analyzes List[Evidence] and classifies each as: INDEPENDENT, DUPLICATED, SYNDICATED, CONTRADICTING
- [ ] 3. Detector uses indicators: identical passages (Jaccard similarity > 0.9), same author, same publication_date, attribution statements ("according to...", "reported by...")
- [ ] 4. WHEN Evidence objects share source_domain, detector examines content similarity to detect republication
- [ ] 5. Detector builds source_independence_graph showing relationships between sources
- [ ] 6. Detector identifies clusters of duplicated content from same original article
- [ ] 7. Detector flags evidence pools where all sources are duplicated/syndicated as LOW_INDEPENDENCE
- [ ] 8. Detector identifies contradicting sources with conflicting claims
- [ ] 9. Detector returns independent_source_count and duplicated_source_count
- [ ] 10. Unit tests verify duplication detection with identical passages
- [ ] 11. Unit tests verify syndication detection with attribution statements
- [ ] 12. Unit tests verify independence graph construction
- [ ] 13. Unit tests verify contradiction detection

**Implementation Notes**:
```python
class SourceIndependenceDetector:
    def analyze(self, evidence_pool: List[Evidence]) -> SourceIndependenceAnalysis:
        """
        Analyze evidence pool for source independence.
        
        Returns:
        - Classification for each evidence piece
        - source_independence_graph
        - independent_source_count vs duplicated_source_count
        - LOW_INDEPENDENCE flag if needed
        """
        pass
    
    def detect_duplication(self, ev1: Evidence, ev2: Evidence) -> bool:
        """Check if two evidence pieces are duplicates (Jaccard > 0.9)."""
        pass
    
    def detect_syndication(self, evidence: Evidence) -> bool:
        """Check for attribution statements indicating republished content."""
        pass
```

---

#### T014: Verification Agent - Multi-Dimensional Assessment
**Status**: pending  
**Priority**: required  
**Dependencies**: T006, T013  
**Description**: Implement independent verification agent with 8-criteria multi-dimensional assessment and conservative language.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/verification_agent.py` created with VerificationAgent class
- [ ] 2. verify() takes List[Evidence], List[Hypothesis], ChangeEvent, **SourceIndependenceAnalysis** and returns List[VerificationResult], List[HypothesisSupport]
- [ ] 3. **CRITICAL**: Evaluates 8 dimensions: source-hypothesis alignment, product/merchant match, temporal alignment, specificity, direct vs inferred evidence, source independence, contradictions, causality vs correlation
- [ ] 4. Assigns support_level: SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS (5 levels, not 3)
- [ ] 5. Uses CONSERVATIVE language: Don't claim "X caused Y" without genuine causal evidence
- [ ] 6. Distinguishes causal claims (contains "because", "due to", "caused by") from correlational (temporal alignment only)
- [ ] 7. WHEN evidence contains causal language, requires corroboration from independent sources before SUPPORTS status
- [ ] 8. WHEN evidence contains only temporal alignment, classifies as CONSISTENT_WITH not SUPPORTS
- [ ] 9. Integrates source independence analysis: weights independent sources more heavily than duplicated sources
- [ ] 10. Detects contradictory evidence and flags both conflicting pieces
- [ ] 11. Computes quality score from: source_authority (0.25), temporal_proximity (0.25), specificity (0.20), product_merchant_alignment (0.15), **source_independence (0.10)**, causal_strength (0.05)
- [ ] 12. Computes per-hypothesis support status and confidence
- [ ] 13. **CRITICAL**: Does NOT force single hypothesis selection - supports multiple SUPPORTED hypotheses
- [ ] 14. Returns multi_dimensional_scores dict for each evidence piece
- [ ] 15. Unit tests verify 8-criteria assessment
- [ ] 16. Unit tests verify causal vs correlational classification
- [ ] 17. Unit tests verify source independence integration
- [ ] 18. Unit tests verify conservative language (CONSISTENT_WITH for weak evidence)
- [ ] 19. Unit tests verify contradiction detection
- [ ] 20. Unit tests verify multiple hypothesis support

**Implementation Notes**:
```python
class VerificationAgent:
    def verify(
        self,
        evidence_pool: List[Evidence],
        hypotheses: List[Hypothesis],
        change_event: ChangeEvent,
        source_analysis: SourceIndependenceAnalysis
    ) -> Tuple[List[VerificationResult], List[HypothesisSupport]]:
        """
        8-dimensional verification with conservative language.
        
        Criteria:
        1. Source-hypothesis alignment
        2. Product/merchant match
        3. Temporal alignment
        4. Specificity (quantitative data, named entities)
        5. Direct vs inferred evidence
        6. Source independence (from source_analysis)
        7. Contradictions detection
        8. Causality vs correlation
        """
        pass
    
    def classify_support_level(self, scores: Dict[str, float]) -> SupportLevel:
        """
        Conservative classification:
        - SUPPORTS: Strong causal evidence with independent corroboration
        - PARTIALLY_SUPPORTS: Some causal evidence but limited sources
        - CONSISTENT_WITH: Temporal alignment only, no causation
        - INSUFFICIENT_EVIDENCE: Too weak or vague
        - CONTRADICTS: Conflicting claims
        """
        pass
```

---

#### T015: Hypothesis Generator
**Status**: pending  
**Priority**: required  
**Dependencies**: T002  
**Description**: Implement hypothesis generation with signal_score (NOT confidence) and requires_external_evidence flag.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/hypothesis_generator.py` created with HypothesisGenerator class
- [ ] 2. generate() takes ChangeEvent and returns List[Hypothesis]
- [ ] 3. **CRITICAL**: Uses signal-to-hypothesis mapping with **signal_score** weights (NOT confidence)
- [ ] 4. Generates 1-8 hypotheses based on signals
- [ ] 5. When signals are weak (all < 0.4), generates at least 2 hypotheses with equal signal_score
- [ ] 6. Computes signal_score using formula: 1 - product(1 - signal_weight)
- [ ] 7. Sets **requires_external_evidence** flag: True for INVENTORY_LIQUIDATION, PRODUCT_EVENT, MARKET_EVENT, MANUFACTURER_CHANGE
- [ ] 8. **CRITICAL**: For INVENTORY_LIQUIDATION, does NOT infer from availability field alone - marks requires_external_evidence=True
- [ ] 9. Provides rationale for each hypothesis based on matched signals
- [ ] 10. Assigns agent types to each hypothesis using AgentRegistry mapping
- [ ] 11. Unit tests verify signal matching
- [ ] 12. Unit tests verify signal_score computation
- [ ] 13. Unit tests verify minimum hypothesis guarantee
- [ ] 14. Unit tests verify rationale generation
- [ ] 15. Unit tests verify requires_external_evidence flag for INVENTORY_LIQUIDATION

---

### Phase 5: Investigation Agents (T016-T023)

#### T016: Base Investigation Agent
**Status**: pending  
**Priority**: required  
**Dependencies**: T002, T004  
**Description**: Implement abstract base class for investigation agents with STRUCTURED QUERY generation.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/base_agent.py` created with InvestigationAgent abstract class
- [ ] 2. Base class has constructor accepting SearchProvider and AgentConfig
- [ ] 3. Defines abstract method: can_investigate(hypothesis: Hypothesis) -> bool
- [ ] 4. **CRITICAL**: Defines abstract method: generate_queries(change_event, hypothesis) -> List[**SearchQuery**] (returns STRUCTURED objects, NOT strings)
- [ ] 5. SearchQuery objects must include ALL fields: event_id, hypothesis, query_text, purpose, priority, generated_by, product_context, merchant, date_window, identifiers, query_id, execution_metadata
- [ ] 6. Defines abstract method: extract_evidence(search_result, hypothesis, query) -> List[Evidence]
- [ ] 7. Implements concrete method: async investigate(change_event, hypothesis) -> List[Evidence]
- [ ] 8. investigate() orchestrates: generate_queries → search → extract_evidence → filter_by_relevance
- [ ] 9. Implements timeout handling (30 seconds per agent)
- [ ] 10. Implements error logging without raising exceptions
- [ ] 11. Type hints are complete
- [ ] 12. Unit tests verify SearchQuery structure (all fields populated)

**Implementation Notes**:
```python
from abc import ABC, abstractmethod

class InvestigationAgent(ABC):
    def __init__(self, search_provider: SearchProvider, config: AgentConfig):
        self.search_provider = search_provider
        self.config = config
    
    @abstractmethod
    def can_investigate(self, hypothesis: Hypothesis) -> bool:
        pass
    
    @abstractmethod
    def generate_queries(
        self, 
        change_event: ChangeEvent, 
        hypothesis: Hypothesis
    ) -> List[SearchQuery]:  # Returns STRUCTURED objects
        """
        Generate STRUCTURED SearchQuery objects with ALL context fields.
        NOT just query strings!
        """
        pass
    
    async def investigate(
        self, 
        change_event: ChangeEvent, 
        hypothesis: Hypothesis
    ) -> List[Evidence]:
        # Implementation provided in base class
        pass
```

---

#### T017: Promotion Agent
**Status**: pending  
**Priority**: required  
**Dependencies**: T016  
**Description**: Implement promotion investigation agent with STRUCTURED query generation.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/promotion_agent.py` created with PromotionAgent class
- [ ] 2. Extends InvestigationAgent base class
- [ ] 3. can_investigate() returns True for PROMOTION and SEASONAL_EVENT hypotheses
- [ ] 4. **generate_queries() creates 3-5 SearchQuery OBJECTS** (not strings) with patterns: "{brand} {product} sale", "{merchant} promotion {date}", "{product} discount"
- [ ] 5. SearchQuery objects include ALL context: product_context, merchant, date_window, identifiers
- [ ] 6. Uses product name, brand, merchant from ChangeEvent
- [ ] 7. extract_evidence() uses EvidenceExtractor with promotion-specific keywords
- [ ] 8. Unit tests verify SearchQuery structure (all fields populated)
- [ ] 9. Unit tests verify query generation
- [ ] 10. Unit tests verify hypothesis filtering

---

#### T018: Competitor Agent
**Status**: pending  
**Priority**: required  
**Dependencies**: T016  
**Description**: Implement competitor investigation agent with STRUCTURED query generation.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/competitor_agent.py` created with CompetitorAgent class
- [ ] 2. Extends InvestigationAgent base class
- [ ] 3. can_investigate() returns True for COMPETITOR_RESPONSE hypothesis
- [ ] 4. **generate_queries() creates SearchQuery OBJECTS** with patterns: "{category} price war", "{brand} competitive pricing", "retailer price competition {product}"
- [ ] 5. SearchQuery objects include ALL context fields
- [ ] 6. Uses competitor context from ChangeEvent if available
- [ ] 7. extract_evidence() uses EvidenceExtractor with competitor-specific keywords
- [ ] 8. Unit tests verify SearchQuery structure
- [ ] 9. Unit tests verify query generation
- [ ] 10. Unit tests verify hypothesis filtering

---

#### T019: Product Event Agent
**Status**: pending  
**Priority**: required  
**Dependencies**: T016  
**Description**: Implement product event investigation agent with STRUCTURED query generation.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/product_event_agent.py` created with ProductEventAgent class
- [ ] 2. Extends InvestigationAgent base class
- [ ] 3. can_investigate() returns True for PRODUCT_EVENT and MANUFACTURER_CHANGE hypotheses
- [ ] 4. **generate_queries() creates SearchQuery OBJECTS** with patterns: "{brand} {product} launch", "{product} discontinued", "{manufacturer} MSRP change"
- [ ] 5. SearchQuery objects include ALL context fields
- [ ] 6. extract_evidence() uses EvidenceExtractor with product lifecycle keywords
- [ ] 7. Unit tests verify SearchQuery structure
- [ ] 8. Unit tests verify query generation
- [ ] 9. Unit tests verify hypothesis filtering

---

#### T020: News Agent
**Status**: pending  
**Priority**: required  
**Dependencies**: T016  
**Description**: Implement news/market event investigation agent with STRUCTURED query generation.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/news_agent.py` created with NewsAgent class
- [ ] 2. Extends InvestigationAgent base class
- [ ] 3. can_investigate() returns True for MARKET_EVENT hypothesis
- [ ] 4. **generate_queries() creates SearchQuery OBJECTS** with patterns: "{category} market news {date}", "electronics industry trends", "{brand} announcement"
- [ ] 5. SearchQuery objects include ALL context fields
- [ ] 6. extract_evidence() uses EvidenceExtractor with market event keywords
- [ ] 7. Unit tests verify SearchQuery structure
- [ ] 8. Unit tests verify query generation
- [ ] 9. Unit tests verify hypothesis filtering

---

#### T021: Retailer Event Agent
**Status**: pending  
**Priority**: required  
**Dependencies**: T016  
**Description**: Implement retailer event investigation agent with STRUCTURED query generation.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/retailer_event_agent.py` created with RetailerEventAgent class
- [ ] 2. Extends InvestigationAgent base class
- [ ] 3. can_investigate() returns True for PROMOTION and SEASONAL_EVENT hypotheses
- [ ] 4. **generate_queries() creates SearchQuery OBJECTS** with patterns: "{merchant} sale event {date}", "{merchant} promotional calendar", "{merchant} {product} deal"
- [ ] 5. SearchQuery objects include ALL context fields
- [ ] 6. extract_evidence() uses EvidenceExtractor with retailer event keywords
- [ ] 7. Unit tests verify SearchQuery structure
- [ ] 8. Unit tests verify query generation
- [ ] 9. Unit tests verify hypothesis filtering

---

#### T022: Supply Agent
**Status**: pending  
**Priority**: required  
**Dependencies**: T016  
**Description**: Implement supply/inventory investigation agent with STRUCTURED query generation.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/supply_agent.py` created with SupplyAgent class
- [ ] 2. Extends InvestigationAgent base class
- [ ] 3. can_investigate() returns True for INVENTORY_LIQUIDATION hypothesis
- [ ] 4. **generate_queries() creates SearchQuery OBJECTS** with patterns: "{brand} {product} clearance", "{product} stock shortage", "{merchant} inventory liquidation"
- [ ] 5. SearchQuery objects include ALL context fields
- [ ] 6. extract_evidence() uses EvidenceExtractor with supply chain keywords
- [ ] 7. Unit tests verify SearchQuery structure
- [ ] 8. Unit tests verify query generation
- [ ] 9. Unit tests verify hypothesis filtering

---

#### T023: Agent Registry
**Status**: pending  
**Priority**: required  
**Dependencies**: T015, T017, T018, T019, T020, T021, T022  
**Description**: Implement agent registry for hypothesis-to-agent mapping.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/agents/__init__.py` updated with AgentRegistry class
- [ ] 2. Registry maps HypothesisType to List[Type[InvestigationAgent]]
- [ ] 3. Mapping includes: PROMOTION → [PromotionAgent, RetailerEventAgent], COMPETITOR_RESPONSE → [CompetitorAgent], etc.
- [ ] 4. get_agents(hypothesis: Hypothesis) returns applicable agent classes
- [ ] 5. Registry is extensible (supports registering custom agents)
- [ ] 6. Unit tests verify mapping
- [ ] 7. Unit tests verify custom agent registration

---

### Phase 6: Orchestration and Repository (T024-T026)

#### T024: Orchestrator Core
**Status**: pending  
**Priority**: required  
**Dependencies**: T009, T012, T013, T014, T023  
**Description**: Implement main orchestration logic with NO hypothesis diversity penalty and multiple hypothesis support.

**Acceptance Criteria**:
- [ ] 1. File `src/investigation/orchestrator.py` created with Orchestrator class
- [ ] 2. Constructor accepts SearchProvider, InvestigationConfig, EvidenceExtractor, VerificationAgent, HypothesisGenerator, SourceIndependenceDetector
- [ ] 3. investigate_event() takes ChangeEvent and returns EventAssessment
- [ ] 4. Execution flow: generate_hypotheses → spawn_agents → execute_parallel → aggregate_evidence → **analyze_source_independence** → verify → assess
- [ ] 5. Parallel execution limited to 6 concurrent agents
- [ ] 6. Agent timeout is 30 seconds
- [ ] 7. Agent failures are logged and don't crash orchestration
- [ ] 8. Search failures retry up to max_retries with exponential backoff (1s, 2s, 4s)
- [ ] 9. Hypothesis_Generator failure generates default hypotheses [PROMOTION, COMPETITOR_RESPONSE]
- [ ] 10. **CRITICAL**: Computes overall confidence based on: evidence quality, specificity, temporal alignment, **source independence (weighted heavily)**, contradictions, coverage - **NO hypothesis diversity penalty**
- [ ] 11. **CRITICAL**: Does NOT discard hypotheses with insufficient evidence - preserves them with INSUFFICIENT_EVIDENCE status
- [ ] 12. **CRITICAL**: Supports multiple SUPPORTED hypotheses simultaneously without forcing winner selection
- [ ] 13. Passes SourceIndependenceAnalysis to VerificationAgent
- [ ] 14. Tracks independent_source_count and duplicated_source_count in EventAssessment
- [ ] 15. Serializes EventAssessment to JSON via Repository
- [ ] 16. Unit tests verify execution flow
- [ ] 17. Unit tests verify error handling
- [ ] 18. Unit tests verify retry logic
- [ ] 19. Unit tests verify uncertainty computation WITHOUT hypothesis diversity penalty
- [ ] 20. Unit tests verify multiple SUPPORTED hypotheses scenarios

**Implementation Notes**:
```python
class Orchestrator:
    def __init__(
        self,
        search_provider: SearchProvider,
        config: InvestigationConfig,
        evidence_extractor: EvidenceExtractor,
        verification_agent: VerificationAgent,
        hypothesis_generator: HypothesisGenerator,
        source_independence_detector: SourceIndependenceDetector  # NEW
    ):
        pass
    
    async def investigate_event(self, change_event: ChangeEvent) -> EventAssessment:
        """
        Full investigation pipeline:
        1. Generate hypotheses (with signal_score NOT confidence)
        2. Execute investigation agents in parallel
        3. Aggregate evidence pool
        4. Analyze source independence (NEW)
        5. Verify evidence (multi-dimensional, with source independence)
        6. Compute confidence (NO hypothesis diversity penalty)
        7. Create EventAssessment (supports multiple SUPPORTED hypotheses)
        """
        pass
```

---

#### T025: Repository Interface
**Status**: pending  
**Priority**: required  
**Dependencies**: T007  
**Description**: NEW TASK - Implement clean Repository abstraction for data access (NO PostgreSQL, NO vector DB).

**Acceptance Criteria**:
- [ ] 1. File `src/repository/repository_interface.py` created with Repository abstract class
- [ ] 2. Interface defines methods: save_event_assessment, load_event_assessment, list_assessments, save_evidence, load_evidence_by_event
- [ ] 3. File `src/repository/json_repository.py` created with JSON_Repository implementation
- [ ] 4. File `src/repository/csv_repository.py` created with CSV_Repository implementation for tabular exports
- [ ] 5. **CRITICAL**: NO PostgreSQL implementation, NO vector database - clean abstraction only
- [ ] 6. JSON_Repository saves to `data/assessments/{event_id}_assessment.json`
- [ ] 7. CSV_Repository exports evidence pools to CSV for analysis
- [ ] 8. Repository handles file I/O errors gracefully with descriptive messages
- [ ] 9. Orchestrator accepts Repository_Interface at initialization
- [ ] 10. Unit tests verify JSON save/load round-trip
- [ ] 11. Unit tests verify CSV export
- [ ] 12. Unit tests verify error handling

**Implementation Notes**:
```python
from abc import ABC, abstractmethod

class Repository(ABC):
    """
    Clean data access layer abstraction.
    
    CRITICAL: This phase implements JSON and CSV only.
    NO PostgreSQL, NO vector databases.
    """
    
    @abstractmethod
    def save_event_assessment(self, assessment: EventAssessment) -> None:
        pass
    
    @abstractmethod
    def load_event_assessment(self, event_id: str) -> Optional[EventAssessment]:
        pass
    
    @abstractmethod
    def list_assessments(self) -> List[str]:
        pass
```

---

#### T026: Integration with Phase 1 and Historical Investigation Script
**Status**: pending  
**Priority**: required  
**Dependencies**: T024, T025  
**Description**: Integrate Phase 2 with Phase 1 outputs AND implement historical investigation script.

**Acceptance Criteria**:
- [ ] 1. **Script `scripts/investigate_event.py` created** for historical event investigation
- [ ] 2. **Script supports `--event-id E001` flag to investigate single Phase 1 event**
- [ ] 3. Script loads ChangeEvent from `data/events/change_events.json` by event_id
- [ ] 4. Script initializes Orchestrator with all components (including SourceIndependenceDetector, Repository)
- [ ] 5. Script supports `--provider mock` for testing with MockSearchProvider (NO API keys required)
- [ ] 6. Script supports `--provider google`, `--provider serpapi`, `--provider tavily` for REAL web search
- [ ] 7. Script loads API keys from environment variables when using real providers
- [ ] 8. Script runs complete pipeline: Hypothesis → Agents → Web Search → Evidence → Source Independence → Verification → Assessment
- [ ] 9. Script outputs EventAssessment with evidence-backed conclusions
- [ ] 10. Script saves assessment to `data/assessments/{event_id}_assessment.json` via Repository
- [ ] 11. Script provides progress logging for each pipeline stage
- [ ] 12. Script `scripts/investigate_events.py` created for BATCH processing (processes all events)
- [ ] 13. Batch script reads ChangeEvents from `data/events/change_events.json`
- [ ] 14. Batch script writes EventAssessments to `data/assessments/event_assessments.json`
- [ ] 15. Batch script has --dry-run mode that validates without writing
- [ ] 16. All 112 existing Phase 1 tests pass after integration
- [ ] 17. Integration script completes without errors on historical data with MockSearchProvider

**Implementation Notes**:
```bash
# Historical investigation of single event
python scripts/investigate_event.py --event-id E001 --provider mock

# Historical investigation with REAL web search
export GOOGLE_API_KEY="..."
python scripts/investigate_event.py --event-id E001 --provider google

# Batch processing
python scripts/investigate_events.py --provider mock
```

---

### Phase 7: Testing (T027-T043)

#### T027: Unit Tests - Search
**Status**: pending  
**Priority**: required  
**Dependencies**: T009  
**Description**: Comprehensive unit tests for search providers.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_search_provider.py` created
- [ ] 2. Tests verify MockSearchProvider pattern matching
- [ ] 3. Tests verify MockSearchProvider call tracking
- [ ] 4. Tests verify empty results for unmatched patterns
- [ ] 5. Tests verify get_page_content() mock HTML
- [ ] 6. Tests verify SearchProvider interface compliance
- [ ] 7. Tests verify that MockSearchProvider works WITHOUT API keys
- [ ] 8. All tests pass using pytest

---

#### T028: Unit Tests - Parser
**Status**: pending  
**Priority**: required  
**Dependencies**: T010  
**Description**: Comprehensive unit tests for HTML/text parser (NO RAG tests).

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_parser.py` created
- [ ] 2. Tests verify HTML tag removal
- [ ] 3. Tests verify paragraph boundary preservation
- [ ] 4. Tests verify anti-scraping detection (CAPTCHA keywords)
- [ ] 5. Tests verify content truncation at 100KB
- [ ] 6. Tests verify character encoding handling
- [ ] 7. Tests verify malformed HTML handling (no exceptions)
- [ ] 8. Tests verify plain text handling
- [ ] 9. Tests verify source_title extraction from <title> tag
- [ ] 10. Tests verify publication_date extraction from meta tags
- [ ] 11. All tests pass using pytest

---

#### T029: Unit Tests - Scorer
**Status**: pending  
**Priority**: required  
**Dependencies**: T011  
**Description**: Comprehensive unit tests for relevance scoring.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_scorer.py` created
- [ ] 2. Tests verify entity_match_score (product, brand, merchant)
- [ ] 3. Tests verify keyword_match_score for each hypothesis type
- [ ] 4. Tests verify temporal_score for date mentions
- [ ] 5. Tests verify numeric_score for prices and percentages
- [ ] 6. Tests verify weighted combination formula
- [ ] 7. Tests verify threshold filtering
- [ ] 8. All tests pass using pytest

---

#### T030: Unit Tests - Extractor
**Status**: pending  
**Priority**: required  
**Dependencies**: T012  
**Description**: Comprehensive unit tests for evidence extraction with COMPLETE PROVENANCE.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_extractor.py` created
- [ ] 2. Tests verify passage segmentation (100-1000 chars)
- [ ] 3. **Tests verify evidence creation with ALL 15+ provenance fields populated**
- [ ] 4. Tests verify deterministic evidence ID generation
- [ ] 5. Tests verify 10 passage limit per result
- [ ] 6. Tests verify relevance filtering
- [ ] 7. Tests verify empty results handling
- [ ] 8. **Tests verify provenance chain integrity: ChangeEvent → Hypothesis → SearchQuery (query_id) → SearchResult → Evidence (evidence_id)**
- [ ] 9. All tests pass using pytest

---

#### T031: Unit Tests - Source Independence
**Status**: pending  
**Priority**: required  
**Dependencies**: T013  
**Description**: NEW TEST - Comprehensive unit tests for source independence detection.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_source_independence.py` created
- [ ] 2. Tests verify duplication detection with identical passages (Jaccard > 0.9)
- [ ] 3. Tests verify syndication detection with attribution statements
- [ ] 4. Tests verify independence classification: INDEPENDENT, DUPLICATED, SYNDICATED, CONTRADICTING
- [ ] 5. Tests verify source_independence_graph construction
- [ ] 6. Tests verify independent_source_count vs duplicated_source_count tracking
- [ ] 7. Tests verify LOW_INDEPENDENCE flag when all sources are duplicated
- [ ] 8. Tests verify contradiction detection between sources
- [ ] 9. All tests pass using pytest

---

#### T032: Unit Tests - Hypothesis
**Status**: pending  
**Priority**: required  
**Dependencies**: T015  
**Description**: Comprehensive unit tests for hypothesis generation with signal_score and requires_external_evidence.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_hypothesis_generator.py` created
- [ ] 2. Tests verify signal-to-hypothesis mapping
- [ ] 3. **Tests verify signal_score computation formula (NOT confidence)**
- [ ] 4. Tests verify minimum 2 hypotheses when signals weak
- [ ] 5. Tests verify rationale generation
- [ ] 6. Tests verify agent assignment
- [ ] 7. **Tests verify requires_external_evidence flag for INVENTORY_LIQUIDATION (True)**
- [ ] 8. Tests verify all 8 hypothesis types can be generated
- [ ] 9. Tests verify INVENTORY_LIQUIDATION does NOT infer from availability field
- [ ] 10. All tests pass using pytest

---

#### T033-T038: Unit Tests - Investigation Agents
**Status**: pending  
**Priority**: required  
**Dependencies**: T017, T018, T019, T020, T021, T022  
**Description**: Comprehensive unit tests for each investigation agent with STRUCTURED query verification.

**Acceptance Criteria** (for each agent):
- [ ] 1. File `tests/investigation/test_{agent_name}_agent.py` created
- [ ] 2. Tests verify can_investigate() for correct hypothesis types
- [ ] 3. **Tests verify generate_queries() creates SearchQuery OBJECTS (not strings) with ALL context fields**
- [ ] 4. Tests verify query patterns include product, brand, merchant
- [ ] 5. Tests verify investigation flow (mock searches)
- [ ] 6. Tests verify evidence extraction
- [ ] 7. All tests pass using pytest

---

#### T039: Unit Tests - Verification
**Status**: pending  
**Priority**: required  
**Dependencies**: T014  
**Description**: Comprehensive unit tests for verification agent with multi-dimensional assessment.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_verification_agent.py` created
- [ ] 2. **Tests verify 8-dimensional assessment criteria**
- [ ] 3. **Tests verify 5-level support classification: SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS**
- [ ] 4. Tests verify quality scoring formula with source_independence factor
- [ ] 5. Tests verify contradiction detection
- [ ] 6. **Tests verify conservative language: CONSISTENT_WITH for correlational evidence**
- [ ] 7. Tests verify hypothesis support computation
- [ ] 8. **Tests verify overall confidence computation WITHOUT hypothesis diversity penalty**
- [ ] 9. **Tests verify multiple hypothesis support (no forced selection)**
- [ ] 10. Tests verify source independence integration
- [ ] 11. All tests pass using pytest

---

#### T040: Unit Tests - Orchestrator
**Status**: pending  
**Priority**: required  
**Dependencies**: T024  
**Description**: Comprehensive unit tests for orchestrator.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_orchestrator.py` created
- [ ] 2. Tests verify full execution flow with mocks
- [ ] 3. Tests verify parallel agent execution (max 6 concurrent)
- [ ] 4. Tests verify agent timeout handling
- [ ] 5. Tests verify agent failure handling (doesn't crash)
- [ ] 6. Tests verify search retry logic with exponential backoff
- [ ] 7. Tests verify Hypothesis_Generator failure fallback
- [ ] 8. **Tests verify uncertainty computation WITHOUT hypothesis diversity penalty**
- [ ] 9. Tests verify EventAssessment serialization
- [ ] 10. **Tests verify multiple SUPPORTED hypotheses scenarios**
- [ ] 11. Tests verify source independence analysis integration
- [ ] 12. All tests pass using pytest

---

#### T041: Integration Tests
**Status**: pending  
**Priority**: optional  
**Dependencies**: T026  
**Description**: Integration tests with real search providers (requires API keys).

**Acceptance Criteria**:
- [ ] 1. File `tests/integration/test_real_search.py` created
- [ ] 2. Tests marked with @pytest.mark.integration and @pytest.mark.skip_without_api_key
- [ ] 3. Tests verify real search provider integration (SerpAPI, Google)
- [ ] 4. Tests verify end-to-end flow with real web searches
- [ ] 5. Tests run only when SEARCH_API_KEY environment variable is set
- [ ] 6. Tests validate real HTML parsing and evidence extraction
- [ ] 7. All tests pass when API key is provided

---

#### T042: End-to-End Test
**Status**: pending  
**Priority**: required  
**Dependencies**: T026  
**Description**: End-to-end test with mock provider on historical data.

**Acceptance Criteria**:
- [ ] 1. File `tests/integration/test_end_to_end.py` created
- [ ] 2. Test reads one ChangeEvent from Phase 1 output
- [ ] 3. Test executes full Orchestrator flow with MockSearchProvider
- [ ] 4. Test verifies EventAssessment structure
- [ ] 5. Test verifies all required fields are populated (including independent_source_count, duplicated_source_count)
- [ ] 6. Test verifies uncertainty metrics are computed
- [ ] 7. Test verifies output serializes to JSON
- [ ] 8. **Test verifies multiple SUPPORTED hypotheses scenarios**
- [ ] 9. Test completes in < 5 seconds
- [ ] 10. Test passes using pytest

---

#### T043: Property-Based Tests
**Status**: pending  
**Priority**: optional  
**Dependencies**: T041  
**Description**: Property-based tests for serialization invariants.

**Acceptance Criteria**:
- [ ] 1. File `tests/investigation/test_properties.py` created
- [ ] 2. Uses Hypothesis library for property-based testing
- [ ] 3. Tests verify serialization round-trip: obj == from_dict(obj.to_dict()) for all data models
- [ ] 4. Tests verify signal_score always in [0.0, 1.0]
- [ ] 5. Tests verify evidence provenance chain integrity
- [ ] 6. All property tests pass

---

### Phase 8: Documentation (T044)

#### T044: Documentation and Examples
**Status**: pending  
**Priority**: required  
**Dependencies**: T042, T043  
**Description**: Create comprehensive documentation with critical architecture clarifications.

**Acceptance Criteria**:
- [ ] 1. File `docs/PHASE2_ARCHITECTURE.md` created documenting system architecture
- [ ] 2. **CRITICAL**: Documentation clarifies this is LIVE WEB SEARCH (Google/SerpAPI/Tavily), NOT RAG, NOT embeddings, NOT vector database
- [ ] 3. **CRITICAL**: Documentation clarifies Channel3 is future Phase 1 pricing data source, NOT used in Phase 2 investigation
- [ ] 4. File `docs/PHASE2_USAGE.md` created with usage examples
- [ ] 5. File `examples/investigate_single_event.py` created with commented example showing MockSearchProvider usage
- [ ] 6. File `examples/investigate_with_real_search.py` created showing real search provider usage
- [ ] 7. File `examples/config_examples/` created with JSON config examples (testing.json, production.json)
- [ ] 8. README.md updated with Phase 2 overview and quick start
- [ ] 9. All examples run without errors
- [ ] 10. Documentation explains mock vs real provider configuration
- [ ] 11. Documentation explains uncertainty interpretation
- [ ] 12. Documentation explains multiple hypothesis support (no forced winner)
- [ ] 13. Documentation explains source independence detection
- [ ] 14. Documentation explains 5-level support classification: SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS
- [ ] 15. Documentation includes example of running historical investigation: `python scripts/investigate_event.py --event-id E001 --provider mock`

---

## Implementation Order

**Recommended execution order**:
1. Foundation: T001 → T002 → T003 → T004 → T005 → T006 → T007
2. Search: T008 → T009
3. Evidence: T010 → T011 → T012 → T013 (NEW: Source Independence)
4. Intelligence: T014 (Verification with multi-dimensional assessment), T015 (Hypothesis Generator with signal_score)
5. Agents: T016 → [T017, T018, T019, T020, T021, T022] (parallel) → T023
6. Orchestration and Repository: T024 → T025 → T026
7. Testing: [T027-T040] (parallel) → T041 → T042 → T043
8. Documentation: T044

**Critical path**: T001 → T002 → T008 → T009 → T016 → T017 → T023 → T024 → T025 → T026 → T042 → T044

**Key changes from original plan**:
- Added T013 (Source Independence Detector) - NEW component
- Added T025 (Repository Interface) - NEW component
- Updated T026 to include historical investigation script (`scripts/investigate_event.py --event-id E001`)
- Renumbered all subsequent tasks
- Now 44 total tasks (was 41)

**Estimated effort**: 
- Foundation: 8 hours
- Search infrastructure: 4 hours
- Evidence processing (including source independence): 12 hours (was 8, added 4 for source independence)
- Hypothesis and verification: 8 hours (was 6, added 2 for multi-dimensional assessment)
- Investigation agents: 12 hours
- Orchestration and repository: 12 hours (was 8, added 4 for repository and historical script)
- Testing: 20 hours (was 16, added 4 for source independence and additional tests)
- Documentation: 4 hours
- **Total: ~80 hours** (was ~66 hours)

## Risk Mitigation

**Risk 1**: Phase 1 tests break during integration
- Mitigation: Run Phase 1 test suite after every module addition
- Rollback: Keep Phase 1 code unchanged, revert Phase 2 additions

**Risk 2**: Mock search results insufficient for testing
- Mitigation: Create comprehensive default result sets covering all hypothesis types
- Fallback: Allow test-specific result configuration

**Risk 3**: Real search API rate limits
- Mitigation: Implement caching layer for repeated queries
- Fallback: Use mock provider for development, real provider only for final validation

**Risk 4**: HTML parsing fails on real web pages
- Mitigation: Implement robust error handling with ParsedContent.parse_success flag
- Fallback: Fall back to snippet-only evidence when full content parsing fails

**Risk 5**: Source independence detection false positives
- Mitigation: Use multiple indicators (Jaccard similarity, attribution statements, publication dates)
- Fallback: Conservative classification - when uncertain, classify as INDEPENDENT

**Risk 6**: Multiple hypothesis support causes confusion
- Mitigation: Clear documentation explaining when multiple causes are valid
- Fallback: Provide confidence scores to help users prioritize hypotheses

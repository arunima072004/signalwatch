# Design Document: SignalWatch Phase 2 - Investigation Layer

## Overview

SignalWatch Phase 2 extends the existing BOCPD-based change detection system with a comprehensive investigation, web evidence retrieval, and verification layer. Phase 1 successfully detects 24 price regime changes from historical pricing data. Phase 2 transforms these detection signals into verified causal assessments through a multi-agent investigation architecture.

**Architecture Approach**: Phase 2 uses **targeted queries → live web search → HTML parsing → evidence extraction → verification**. This is NOT a RAG system - there are NO embeddings, NO vector databases, NO semantic retrieval. Web search happens live against Google/SerpAPI/Tavily/etc. Channel3 is a future pricing data source for Phase 1 ingestion and is NOT used in Phase 2 investigation.

### Design Goals

1. **Non-Destructive Extension**: Add investigation capabilities without modifying Phase 1 code
2. **Uncertainty Preservation**: Maintain multiple hypotheses when evidence is ambiguous; no forced "winner selection"
3. **Causal Reasoning**: Distinguish causation from correlation through rigorous independent verification
4. **Testability**: Enable comprehensive testing without external API dependencies using MockSearchProvider
5. **Extensibility**: Support pluggable search providers (Google, SerpAPI, Tavily) through clean adapter pattern
6. **Complete Provenance**: Track full evidence chain from ChangeEvent → Hypothesis → SearchQuery → SearchResult → Evidence
7. **Source Independence**: Detect and discount duplicated/syndicated content to avoid false confidence

### Key Capabilities

- Generate multiple non-exclusive hypotheses for each price change event with signal scores
- Execute specialized investigation agents with hypothesis-specific query strategies
- Abstract search provider interactions for testing (MockSearchProvider) and production (real APIs)
- Extract relevant evidence with complete source traceability and provenance chain
- Detect source independence to avoid counting the same article multiple times
- Independently verify evidence using multi-dimensional assessment framework
- Support multiple hypotheses being SUPPORTED simultaneously without forcing a single winner
- Quantify uncertainty across all assessment dimensions
- Integrate seamlessly with Phase 1 outputs via clean Repository abstraction
- Support historical investigation of Phase 1 events via `scripts/investigate_event.py`

## Architecture

### System Architecture Overview

**CRITICAL CLARIFICATIONS:**
- **Web Search**: Uses Google/SerpAPI/Tavily/etc. via SearchProvider interface
- **NOT Channel3**: Channel3 is a future pricing data source for Phase 1 ingestion, NOT used in Phase 2 investigation
- **NOT RAG**: No embeddings, no vector database, no semantic retrieval
- **Architecture**: Targeted queries → live web search → HTML parsing → evidence extraction → verification

```
┌─────────────────────────────────────────────────────────────────┐
│                         Phase 1 (Existing)                      │
│  BOCPD → Feature Engineering → Event Generation                 │
│  Output: change_events.json (24 events)                        │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Phase 2 (New)                           │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Orchestrator (Investigation System)           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Hypothesis Generator                        │  │
│  │   (8 hypothesis types, signal_score NOT confidence)      │  │
│  │   (flags: requires_external_evidence)                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Investigation Agents (Parallel)                │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │
│  │  │Promotion │ │Competitor│ │ Product  │ │   News   │   │  │
│  │  │  Agent   │ │  Agent   │ │   Event  │ │  Agent   │   │  │
│  │  └──────────┘ └──────────┘ │  Agent   │ └──────────┘   │  │
│  │  ┌──────────┐ ┌──────────┐ └──────────┘                │  │
│  │  │Retailer  │ │  Supply  │                              │  │
│  │  │  Event   │ │  Agent   │                              │  │
│  │  │  Agent   │ └──────────┘                              │  │
│  │  └──────────┘                                            │  │
│  │              Generates Structured SearchQuery Objects    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         SearchProvider Interface (Live Web Search)       │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │
│  │  │   Mock   │ │  Google  │ │ SerpAPI  │ │  Tavily  │   │  │
│  │  │ Provider │ │ Provider │ │ Provider │ │ Provider │   │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │  │
│  │                                                          │  │
│  │  API Keys: Environment variables, NEVER hardcoded       │  │
│  │  NOT Channel3 (future Phase 1 data source)              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │      SearchResultParser (HTML → Text Extraction)         │  │
│  │   (Removes scripts/styles, handles malformed HTML)       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │       Evidence Extraction (Complete Provenance)          │  │
│  │   Evidence: evidence_id, event_id, hypothesis,           │  │
│  │   source_url, source_domain, source_title,               │  │
│  │   publication_date, retrieved_at, claim, evidence_text,  │  │
│  │   evidence_type, relevance, investigator, query_id       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Source Independence Analysis                     │  │
│  │   Detect: INDEPENDENT vs DUPLICATED/SYNDICATED           │  │
│  │   Build: source_independence_graph                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │      Verification Agent (Multi-Dimensional)              │  │
│  │   8 criteria: source-hypothesis alignment,               │  │
│  │   product/merchant match, temporal alignment,            │  │
│  │   specificity, direct vs inferred, source independence,  │  │
│  │   contradictions, causality vs correlation               │  │
│  │                                                          │  │
│  │   Support: SUPPORTS, PARTIALLY_SUPPORTS,                 │  │
│  │   CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              EventAssessment                             │  │
│  │   Multiple hypotheses can be SUPPORTED simultaneously    │  │
│  │   NO "winner selection" logic                            │  │
│  │   Confidence: NO hypothesis diversity penalty            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Repository Interface (Data Access Layer)         │  │
│  │   ┌──────────┐ ┌──────────┐                              │  │
│  │   │   JSON   │ │   CSV    │  NO PostgreSQL yet           │  │
│  │   │Repository│ │Repository│  NO Vector DB                │  │
│  │   └──────────┘ └──────────┘                              │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
         Output: event_assessments.json
         
Entry Point: scripts/investigate_event.py --event-id E001
  (Works with both MockSearchProvider and real SearchProvider)
```

### Module Structure

```
signalwatch/
├── src/
│   ├── investigation/              # NEW: Phase 2 investigation system
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # Main orchestration logic
│   │   ├── hypothesis_generator.py # Hypothesis generation
│   │   ├── agents/                 # Investigation agents
│   │   │   ├── __init__.py
│   │   │   ├── base_agent.py      # Abstract base class
│   │   │   ├── promotion_agent.py
│   │   │   ├── competitor_agent.py
│   │   │   ├── product_event_agent.py
│   │   │   ├── news_agent.py
│   │   │   ├── retailer_event_agent.py
│   │   │   └── supply_agent.py
│   │   └── verification_agent.py   # Independent verification
│   ├── search/                     # NEW: Search provider abstraction
│   │   ├── __init__.py
│   │   ├── provider_interface.py  # Abstract interface
│   │   ├── mock_provider.py       # Mock for testing
│   │   ├── google_provider.py     # Future: Google API
│   │   └── serpapi_provider.py    # Future: SerpAPI
│   ├── evidence/                   # NEW: Evidence handling
│   │   ├── __init__.py
│   │   ├── extractor.py           # Evidence extraction
│   │   ├── scorer.py              # Relevance scoring
│   │   └── parser.py              # HTML/text parsing
│   ├── models/                     # NEW: Phase 2 data models
│   │   ├── __init__.py
│   │   ├── hypothesis.py
│   │   ├── search.py
│   │   ├── evidence.py
│   │   ├── verification.py
│   │   └── assessment.py
│   └── config/                     # NEW: Configuration
│       ├── __init__.py
│       └── investigation_config.py
├── data/
│   └── assessments/                # NEW: Phase 2 outputs
│       └── event_assessments.json
├── tests/
│   ├── test_investigation_*.py    # NEW: Phase 2 tests
│   └── ...                         # Existing Phase 1 tests (unchanged)
└── ...
```

### Data Flow

**Complete Investigation Pipeline with Provenance Chain:**

```
1. ChangeEvent (Phase 1 output from change_events.json)
   Contains: event_id, product_name, brand, merchant, price info, competitive signals
   ↓
2. Hypothesis_Generator.generate(change_event)
   → List[Hypothesis] (2-8 hypotheses with signal_score NOT confidence)
   → Each hypothesis may have flag: requires_external_evidence=True (e.g., INVENTORY_LIQUIDATION)
   → Signal scores computed from ChangeEvent attributes (is_sale, competitor_count, etc.)
   ↓
3. Orchestrator.investigate(change_event, hypotheses)
   → Parallel execution of Investigation_Agents
   → Each agent: generate_structured_queries() → execute_search() → extract_evidence()
   ↓
4. SearchQuery Generation (STRUCTURED OBJECTS)
   → Each SearchQuery contains:
      - event_id, hypothesis, query_text, purpose, priority, generated_by
      - product_context (name, brand, category, model)
      - merchant, date_window
      - identifiers (ASIN, UPC, EAN, SKU)
      - query_id (for provenance tracing)
      - execution_metadata (execution_status, executed_at, search_provider_used, result_count)
   ↓
5. SearchProvider.search() (LIVE WEB SEARCH - NOT Channel3, NOT RAG)
   → MockSearchProvider (for testing, no API keys)
   OR
   → Real provider (Google/SerpAPI/Tavily via API key from environment)
   → Returns SearchResult objects
   ↓
6. SearchResultParser.parse() (HTML → Text)
   → Removes <script>, <style>, <nav> tags
   → Handles malformed HTML gracefully
   → Returns ParsedContent with extracted_text
   ↓
7. Evidence_Extraction (COMPLETE PROVENANCE)
   → Evidence Pool created with ALL fields:
      - evidence_id, event_id, hypothesis
      - source_url, source_domain, source_title, publication_date, retrieved_at
      - claim, evidence_text, evidence_type (DIRECT/INDIRECT/CAUSAL/CORRELATIONAL)
      - relevance, investigator (agent name), query_id
   → Full provenance chain: ChangeEvent → Hypothesis → SearchQuery (query_id) → SearchResult → Evidence (evidence_id)
   ↓
8. Source_Independence_Analysis
   → Classify sources: INDEPENDENT vs DUPLICATED vs SYNDICATED vs CONTRADICTING
   → Build source_independence_graph
   → Detect content similarity, same author, attribution statements
   → Flag evidence pools with low independence
   ↓
9. Verification_Agent.verify() (MULTI-DIMENSIONAL ASSESSMENT)
   → 8 evaluation criteria:
      1. Source-hypothesis alignment
      2. Product/merchant match
      3. Temporal alignment
      4. Specificity
      5. Direct vs inferred evidence
      6. Source independence
      7. Contradictions detection
      8. Causality vs correlation
   → Support levels: SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS
   → Conservative language: Don't claim "X caused Y" without genuine evidence
   ↓
10. EventAssessment (MULTIPLE HYPOTHESES SUPPORT)
   → Multiple hypotheses can be SUPPORTED simultaneously
   → NO "winner selection" logic
   → Per-hypothesis support levels with evidence IDs
   → Overall confidence based on:
      - Evidence quality, specificity, temporal alignment
      - Source independence (weight independent sources heavily)
      - Contradictions, coverage, missing information
      - NO hypothesis diversity penalty
   → Uncertainty factors explained
   → Independent source count vs duplicated source count
   ↓
11. Repository.save_event_assessment()
   → Clean Repository_Interface abstraction
   → JSON_Repository or CSV_Repository (NO PostgreSQL yet, NO vector DB)
   → Saves to data/assessments/{event_id}_assessment.json
```

**Entry Points:**

1. **Historical Investigation**: `scripts/investigate_event.py --event-id E001`
   - Loads ChangeEvent from Phase 1 data
   - Runs full pipeline
   - Works with MockSearchProvider (testing) or real SearchProvider (production)
   - Outputs EventAssessment with evidence-backed conclusions

2. **Batch Processing**: Future capability to process all 24 events

## Components and Interfaces

### 1. Hypothesis Generator

**Purpose**: Generate multiple non-exclusive hypotheses for each price change event based on observable signals.

**CRITICAL CHANGES FROM PREVIOUS DESIGN:**
- Use `signal_score` NOT `confidence` (to avoid implying calibrated probability)
- Add `requires_external_evidence` flag for hypotheses like INVENTORY_LIQUIDATION
- Show explicit mapping from ChangeEvent signals to hypothesis scores

**Interface**:

```python
class HypothesisGenerator:
    def generate(self, change_event: ChangeEvent) -> List[Hypothesis]:
        """
        Generate hypotheses from change event signals.
        
        Returns 1-8 hypotheses based on signal strength.
        When signals are weak, returns at least 2 hypotheses with equal signal_score.
        """
        pass
```

**Hypothesis Types**:

1. **PROMOTION**: Product on sale or promotional event
   - Signals: `is_sale=True`, `percentage_change < -10%`, `offer` field populated
   - requires_external_evidence: False (can be inferred from ChangeEvent)
   
2. **COMPETITOR_RESPONSE**: Reaction to competitor pricing
   - Signals: `competitor_count > 3`, `competitors_changed_7d > 2`, `price_vs_comp_median` deviation
   - requires_external_evidence: False

3. **INVENTORY_LIQUIDATION**: Clearing excess inventory
   - Signals: Large price drop (`percentage_change < -20%`)
   - requires_external_evidence: **True** (availability field is NOT sufficient - need external confirmation)

4. **PRODUCT_EVENT**: Launch, discontinuation, or lifecycle event
   - Signals: First/last observation in series, extreme price changes
   - requires_external_evidence: True

5. **SEASONAL_EVENT**: Holiday or seasonal pricing
   - Signals: Time-based patterns, `offer` field with seasonal keywords
   - requires_external_evidence: False

6. **MARKET_EVENT**: Broad market or category-level event
   - Signals: Multiple products in same category changing simultaneously
   - requires_external_evidence: True

7. **MANUFACTURER_CHANGE**: MSRP change or manufacturer action
   - Signals: Price change across multiple merchants simultaneously
   - requires_external_evidence: True

8. **DATA_ISSUE**: Data quality problem
   - Signals: Implausible price values, missing data, immediate reversal
   - requires_external_evidence: False

**Signal-to-Hypothesis Mapping**:

```python
HYPOTHESIS_SIGNALS = {
    HypothesisType.PROMOTION: {
        "signals": [
            ("is_sale", lambda v: v == True, 0.8),
            ("percentage_change", lambda v: v < -10, 0.6),
            ("offer", lambda v: v is not None and len(v) > 0, 0.5),
        ],
        "requires_external_evidence": False
    },
    HypothesisType.COMPETITOR_RESPONSE: {
        "signals": [
            ("competitor_count", lambda v: v >= 3, 0.6),
            ("competitors_changed_7d", lambda v: v >= 2, 0.7),
            ("price_vs_comp_median", lambda v: abs(v) > 15, 0.5),
        ],
        "requires_external_evidence": False
    },
    HypothesisType.INVENTORY_LIQUIDATION: {
        "signals": [
            ("percentage_change", lambda v: v < -20, 0.7),
            # NOTE: availability field is NOT used - requires external evidence
        ],
        "requires_external_evidence": True  # Critical: cannot infer from availability alone
    },
    # ... additional mappings
}
```

**Signal Score Computation** (NOT confidence):

```python
def compute_signal_score(signals_matched: List[Tuple[str, float]]) -> float:
    """
    Aggregate signal strengths into overall signal score.
    
    Uses term "signal_score" instead of "confidence" to avoid implying
    calibrated probability. This is a heuristic score based on ChangeEvent attributes.
    
    signal_score = 1 - product(1 - signal_weight for all matched signals)
    Ensures multiple weak signals combine to stronger score.
    """
    if not signals_matched:
        return 0.3  # Default low score when no signals match
    
    prob_all_absent = 1.0
    for _, weight in signals_matched:
        prob_all_absent *= (1 - weight)
    
    return min(1.0 - prob_all_absent, 0.95)  # Cap at 0.95
```

**Example Hypothesis Generation**:

```python
# Input: ChangeEvent with percentage_change=-25%, is_sale=True, competitor_count=5

# Generated Hypotheses:
Hypothesis(
    hypothesis_type=PROMOTION,
    signal_score=0.92,  # High score from is_sale + percentage_change
    requires_external_evidence=False,
    rationale="Large price decrease (-25%) with is_sale flag indicates promotional pricing"
)

Hypothesis(
    hypothesis_type=INVENTORY_LIQUIDATION,
    signal_score=0.70,  # Score from percentage_change only
    requires_external_evidence=True,  # CRITICAL: Need web evidence, can't infer from availability
    rationale="Significant price drop (-25%) may indicate inventory clearance - requires external verification"
)

Hypothesis(
    hypothesis_type=COMPETITOR_RESPONSE,
    signal_score=0.60,  # Score from competitor_count
    requires_external_evidence=False,
    rationale="High competitor count (5) suggests potential competitive response"
)
```

### 2. Investigation Agents

**Base Agent Interface**:

```python
from abc import ABC, abstractmethod

class InvestigationAgent(ABC):
    def __init__(self, search_provider: SearchProvider, config: AgentConfig):
        self.search_provider = search_provider
        self.config = config
    
    @abstractmethod
    def can_investigate(self, hypothesis: Hypothesis) -> bool:
        """Check if this agent can investigate the hypothesis type."""
        pass
    
    @abstractmethod
    def generate_queries(
        self, 
        change_event: ChangeEvent, 
        hypothesis: Hypothesis
    ) -> List[SearchQuery]:
        """
        Generate STRUCTURED SearchQuery objects (not just strings).
        
        Each SearchQuery must include:
        - event_id, hypothesis, query_text, purpose, priority, generated_by
        - product_context (name, brand, category, model)
        - merchant, date_window
        - identifiers (ASIN, UPC, EAN, SKU)
        - query_id (for provenance tracing)
        - execution_metadata (initially empty, filled during execution)
        """
        pass
    
    async def investigate(
        self, 
        change_event: ChangeEvent, 
        hypothesis: Hypothesis
    ) -> List[Evidence]:
        """
        Full investigation flow:
        1. Generate structured queries
        2. Execute searches via SearchProvider
        3. Parse HTML results
        4. Extract evidence with complete provenance
        5. Score relevance
        """
        queries = self.generate_queries(change_event, hypothesis)
        evidence_pool = []
        
        for query in queries:
            # Execute search
            results = await self.search_provider.search(
                query.query_text, 
                num_results=self.config.results_per_query
            )
            
            # Update query execution metadata
            query.execution_metadata.execution_status = "completed"
            query.execution_metadata.executed_at = datetime.utcnow().isoformat()
            query.execution_metadata.search_provider_used = self.search_provider.get_provider_name()
            query.execution_metadata.result_count = len(results)
            
            for result in results:
                # Parse HTML → text
                parsed = self.parse_search_result(result)
                
                # Extract evidence with full provenance
                evidence_list = self.extract_evidence(
                    result, parsed, hypothesis, change_event, query.query_id
                )
                evidence_pool.extend(evidence_list)
        
        return self.filter_by_relevance(evidence_pool)
    
    def parse_search_result(self, search_result: SearchResult) -> ParsedContent:
        """Parse HTML content using SearchResultParser."""
        parser = SearchResultParser()
        if search_result.full_content:
            return parser.parse(search_result.full_content)
        else:
            # Use snippet if full content unavailable
            return ParsedContent(
                extracted_text=search_result.snippet,
                parse_success=True,
                error_messages=[],
                truncated=False
            )
    
    @abstractmethod
    def extract_evidence(
        self, 
        search_result: SearchResult,
        parsed_content: ParsedContent,
        hypothesis: Hypothesis,
        change_event: ChangeEvent,
        query_id: str
    ) -> List[Evidence]:
        """
        Extract relevant passages from parsed content.
        
        CRITICAL: Must populate ALL Evidence provenance fields:
        - evidence_id, event_id, hypothesis
        - source_url, source_domain, source_title, publication_date, retrieved_at
        - claim, evidence_text, evidence_type, relevance, investigator, query_id
        """
        pass
    
    def filter_by_relevance(self, evidence: List[Evidence]) -> List[Evidence]:
        """Filter evidence by minimum relevance threshold."""
        return [
            e for e in evidence 
            if e.relevance_score >= self.config.min_relevance_score
        ]
```

**Specialized Agent Implementations**:

1. **Promotion_Agent**
   - Investigates: PROMOTION, SEASONAL_EVENT
   - Query strategy: 
     - Primary: "{brand} {product} sale promotion {merchant} {date_window}"
     - Secondary: "black friday cyber monday deals {category}"
     - Context: product_name, brand, merchant, date_window
   - Evidence focus: Sale announcements, promotional pricing, discount codes

2. **Competitor_Agent**
   - Investigates: COMPETITOR_RESPONSE
   - Query strategy:
     - Primary: "{category} price war {date_window}"
     - Secondary: "{brand} competitive pricing strategy"
     - Competitor names from ChangeEvent if available
   - Evidence focus: Competitive moves, market share battles, pricing strategy

3. **Product_Event_Agent**
   - Investigates: PRODUCT_EVENT, MANUFACTURER_CHANGE
   - Query strategy:
     - Primary: "{brand} {product} launch discontinued {date_window}"
     - Secondary: "{manufacturer} MSRP change announcement"
     - Use ASIN/UPC/EAN when available for precise targeting
   - Evidence focus: Product lifecycle events, manufacturer announcements

4. **News_Agent**
   - Investigates: MARKET_EVENT
   - Query strategy:
     - Primary: "{category} news {date_window}"
     - Secondary: "electronics market trends {date}"
   - Evidence focus: Industry news, market events, economic factors

5. **Retailer_Event_Agent**
   - Investigates: PROMOTION, SEASONAL_EVENT
   - Query strategy:
     - Primary: "{merchant} sale event {date_window}"
     - Secondary: "{merchant} promotional calendar"
   - Evidence focus: Retailer-specific events, store promotions

6. **Supply_Agent**
   - Investigates: INVENTORY_LIQUIDATION (requires_external_evidence=True)
   - Query strategy:
     - Primary: "{brand} {product} inventory clearance {date_window}"
     - Secondary: "{product} stock shortage supply chain"
   - Evidence focus: Supply chain issues, inventory levels, clearance events

**Structured SearchQuery Example**:

```python
SearchQuery(
    event_id="E001",
    hypothesis=HypothesisType.PROMOTION,
    query_text="Sony WH-1000XM4 sale promotion Amazon June 2023",
    purpose="Find promotional announcements for detected price drop",
    priority=1,  # 1=high, 2=medium, 3=low
    generated_by="Promotion_Agent",
    product_context=ProductContext(
        product_name="Sony WH-1000XM4",
        product_brand="Sony",
        product_category="Electronics > Headphones",
        product_model="WH-1000XM4"
    ),
    merchant="Amazon",
    date_window=DateWindow(
        start_date="2023-06-01",
        end_date="2023-06-30"
    ),
    identifiers=ProductIdentifiers(
        ASIN="B0863TXGM3",
        UPC="4548736109957",
        EAN=None,
        SKU=None
    ),
    query_id="q_e001_promo_001",  # Unique ID for provenance
    execution_metadata=ExecutionMetadata(
        execution_status="pending",  # Will be updated to "completed"
        executed_at=None,
        search_provider_used=None,
        result_count=None
    )
)
```

**Agent Selection and Execution**:

```python
class AgentRegistry:
    """Maps hypothesis types to investigation agents."""
    
    AGENT_MAPPING = {
        HypothesisType.PROMOTION: [Promotion_Agent, Retailer_Event_Agent],
        HypothesisType.COMPETITOR_RESPONSE: [Competitor_Agent],
        HypothesisType.INVENTORY_LIQUIDATION: [Supply_Agent],
        HypothesisType.PRODUCT_EVENT: [Product_Event_Agent],
        HypothesisType.SEASONAL_EVENT: [Promotion_Agent, Retailer_Event_Agent],
        HypothesisType.MARKET_EVENT: [News_Agent],
        HypothesisType.MANUFACTURER_CHANGE: [Product_Event_Agent],
        HypothesisType.DATA_ISSUE: [],  # No web investigation for data issues
    }
    
    def get_agents(self, hypothesis: Hypothesis) -> List[Type[InvestigationAgent]]:
        """Get all applicable agents for a hypothesis."""
        return self.AGENT_MAPPING.get(hypothesis.hypothesis_type, [])
```

### 3. Search Provider Abstraction

**CRITICAL CLARIFICATIONS:**
- **Web Search Providers**: Google, SerpAPI, Tavily, Brave, etc. - real web search APIs
- **NOT Channel3**: Channel3 is a future pricing data source for Phase 1 ingestion, NOT used in Phase 2 investigation
- **API Keys**: Managed via environment variables, NEVER hardcoded
- **MockSearchProvider**: For testing without API calls or API keys
- **Clean Adapter Pattern**: Swap providers without changing investigation logic

**Provider Interface**:

```python
from abc import ABC, abstractmethod
from typing import Optional

class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, num_results: int = 10) -> List[SearchResult]:
        """
        Execute a web search query.
        
        Args:
            query: Search query text
            num_results: Maximum number of results to return
            
        Returns:
            List of SearchResult objects
            
        Raises:
            SearchProviderError: On API failures after retries
        """
        pass
    
    @abstractmethod
    async def get_page_content(self, url: str) -> Optional[str]:
        """
        Retrieve full HTML content from URL.
        
        Args:
            url: Page URL
            
        Returns:
            HTML content or None on failure
        """
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider identifier (e.g., 'mock', 'google', 'serpapi', 'tavily')."""
        pass
```

**Mock Provider for Testing**:

```python
class MockSearchProvider(SearchProvider):
    """
    Testing implementation that returns predetermined results.
    
    NO API calls, NO API keys required, NO network access.
    
    Supports pattern-based result configuration:
    - Query patterns map to result sets
    - Configurable delays for timeout testing
    - Failure injection for error handling testing
    """
    
    def __init__(self, result_config: Optional[Dict[str, List[SearchResult]]] = None):
        self.result_config = result_config or self._default_results()
        self.call_count = 0
        self.query_history = []
    
    async def search(self, query: str, num_results: int = 10) -> List[SearchResult]:
        self.call_count += 1
        self.query_history.append(query)
        
        # Pattern matching: find best match for query
        for pattern, results in self.result_config.items():
            if pattern.lower() in query.lower():
                return results[:num_results]
        
        # Default: return empty results
        return []
    
    async def get_page_content(self, url: str) -> Optional[str]:
        # Return mock HTML content based on URL pattern
        if "sale" in url:
            return "<html><body><h1>Summer Sale</h1><p>Save 50% off all electronics through June 30th</p></body></html>"
        return "<html><body>Generic content</body></html>"
    
    def get_provider_name(self) -> str:
        return "mock"
    
    def _default_results(self) -> Dict[str, List[SearchResult]]:
        """Default result set for common query patterns."""
        return {
            "sale": [
                SearchResult(
                    url="https://example.com/sale-announcement",
                    title="Summer Sale - 50% Off Electronics",
                    snippet="Major electronics sale with deep discounts on headphones, laptops, and tablets...",
                    source_domain="example.com",
                    retrieved_at=datetime.utcnow().isoformat(),
                    search_provider="mock"
                )
            ],
            "competitor": [
                SearchResult(
                    url="https://industry-news.com/price-war",
                    title="Electronics Price War Intensifies",
                    snippet="Retailers slashing prices to compete for market share in headphones category...",
                    source_domain="industry-news.com",
                    retrieved_at=datetime.utcnow().isoformat(),
                    search_provider="mock"
                )
            ],
            # Additional default patterns...
        }
```

**Real Provider Example (SerpAPI)**:

```python
class SerpAPIProvider(SearchProvider):
    """
    Production implementation using SerpAPI.
    
    API Key Management:
    - Read from environment variable: SERPAPI_API_KEY
    - NEVER hardcode API keys
    - Fail fast if API key not available
    """
    
    def __init__(self, api_key: Optional[str] = None, config: Optional[SearchConfig] = None):
        # Read from environment if not provided
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "SerpAPI API key required. Set SERPAPI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        self.config = config or SearchConfig()
        self.client = SerpAPIClient(self.api_key)
        self.rate_limiter = RateLimiter(requests_per_minute=self.config.rate_limit)
    
    async def search(self, query: str, num_results: int = 10) -> List[SearchResult]:
        """
        Execute search via SerpAPI.
        
        Implements:
        - Rate limiting
        - Retry logic with exponential backoff
        - Error handling
        """
        await self.rate_limiter.acquire()
        
        try:
            response = await self.client.search(
                q=query,
                num=num_results,
                engine="google"
            )
            
            results = []
            for item in response.get("organic_results", []):
                results.append(SearchResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    source_domain=self._extract_domain(item.get("link", "")),
                    retrieved_at=datetime.utcnow().isoformat(),
                    search_provider="serpapi"
                ))
            
            return results
            
        except SerpAPIException as e:
            logger.error(f"SerpAPI search failed: {e}")
            raise SearchProviderError(f"Search failed: {e}")
    
    async def get_page_content(self, url: str) -> Optional[str]:
        """
        Retrieve full page content.
        
        Uses httpx with timeout and retry logic.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.warning(f"Failed to retrieve {url}: {e}")
            return None
    
    def get_provider_name(self) -> str:
        return "serpapi"
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        return urlparse(url).netloc
```

**Real Provider Example (Google Custom Search)**:

```python
class GoogleSearchProvider(SearchProvider):
    """
    Production implementation using Google Custom Search API.
    
    API Key Management:
    - Requires: GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID
    - Read from environment variables
    - NEVER hardcode credentials
    """
    
    def __init__(self, api_key: Optional[str] = None, search_engine_id: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        self.search_engine_id = search_engine_id or os.environ.get("GOOGLE_SEARCH_ENGINE_ID")
        
        if not self.api_key or not self.search_engine_id:
            raise ValueError(
                "Google Custom Search requires GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID "
                "environment variables."
            )
        
        self.service = build("customsearch", "v1", developerKey=self.api_key)
    
    async def search(self, query: str, num_results: int = 10) -> List[SearchResult]:
        try:
            response = self.service.cse().list(
                q=query,
                cx=self.search_engine_id,
                num=num_results
            ).execute()
            
            results = []
            for item in response.get("items", []):
                results.append(SearchResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    source_domain=self._extract_domain(item.get("link", "")),
                    retrieved_at=datetime.utcnow().isoformat(),
                    search_provider="google"
                ))
            
            return results
        except Exception as e:
            logger.error(f"Google search failed: {e}")
            raise SearchProviderError(f"Search failed: {e}")
    
    async def get_page_content(self, url: str) -> Optional[str]:
        # Similar implementation to SerpAPIProvider
        pass
    
    def get_provider_name(self) -> str:
        return "google"
```

**Provider Selection at Runtime**:

```python
def create_search_provider(provider_name: str = "mock") -> SearchProvider:
    """
    Factory function to create search provider.
    
    Args:
        provider_name: "mock", "serpapi", "google", "tavily"
    
    Returns:
        SearchProvider instance
    
    Raises:
        ValueError: If provider not supported or missing credentials
    """
    if provider_name == "mock":
        return MockSearchProvider()
    elif provider_name == "serpapi":
        return SerpAPIProvider()  # Reads from SERPAPI_API_KEY env var
    elif provider_name == "google":
        return GoogleSearchProvider()  # Reads from env vars
    elif provider_name == "tavily":
        return TavilyProvider()  # Reads from TAVILY_API_KEY env var
    else:
        raise ValueError(f"Unsupported search provider: {provider_name}")
```

**Configuration Example**:

```python
# config/investigation_config.py

class InvestigationConfig:
    def __init__(self):
        # Search provider selection
        self.search_provider_name = os.environ.get("SEARCH_PROVIDER", "mock")
        
        # Provider-specific settings
        self.serpapi_api_key = os.environ.get("SERPAPI_API_KEY")  # Optional
        self.google_api_key = os.environ.get("GOOGLE_API_KEY")  # Optional
        self.tavily_api_key = os.environ.get("TAVILY_API_KEY")  # Optional
        
        # Rate limiting
        self.rate_limit_requests_per_minute = 60
        
        # Agent settings
        self.results_per_query = 10
        self.max_retries = 3
```

### 4. Evidence Extraction and Scoring

**Evidence Extractor**:

```python
class EvidenceExtractor:
    """
    Extracts relevant passages from search results.
    
    Strategy:
    1. Parse HTML/text content
    2. Segment into passages (paragraphs, sentences)
    3. Score each passage for relevance to hypothesis
    4. Extract top-scoring passages as Evidence objects
    """
    
    def __init__(self, parser: SearchResultParser, scorer: RelevanceScorer):
        self.parser = parser
        self.scorer = scorer
    
    def extract(
        self, 
        search_result: SearchResult, 
        hypothesis: Hypothesis,
        change_event: ChangeEvent
    ) -> List[Evidence]:
        """
        Extract evidence from a search result.
        
        Returns Evidence objects with relevance scores >= threshold.
        """
        # Parse content
        if search_result.full_content:
            parsed = self.parser.parse(search_result.full_content)
        else:
            # Use snippet if full content unavailable
            parsed = ParsedContent(
                extracted_text=search_result.snippet,
                parse_success=True,
                error_messages=[],
                truncated=False
            )
        
        if not parsed.parse_success:
            logger.warning(f"Failed to parse {search_result.url}: {parsed.error_messages}")
            return []
        
        # Segment into passages
        passages = self._segment_text(parsed.extracted_text)
        
        # Score and filter
        evidence_list = []
        for passage in passages:
            score = self.scorer.compute_relevance(
                passage, 
                hypothesis, 
                change_event
            )
            
            if score >= self.scorer.min_relevance_threshold:
                evidence_list.append(Evidence(
                    evidence_id=self._generate_evidence_id(search_result.url, passage),
                    passage_text=passage,
                    source_url=search_result.url,
                    relevance_score=score,
                    hypothesis_type=hypothesis.hypothesis_type,
                    retrieved_at=search_result.retrieved_at,
                    extraction_method="keyword_semantic"
                ))
        
        return evidence_list
    
    def _segment_text(self, text: str) -> List[str]:
        """
        Segment text into passages.
        
        Strategy:
        - Split on paragraph boundaries
        - Further split long paragraphs into sentences
        - Merge short adjacent segments
        - Target passage length: 100-500 characters
        """
        paragraphs = text.split('\n\n')
        passages = []
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(para) <= 500:
                passages.append(para)
            else:
                # Split long paragraphs into sentences
                sentences = self._split_sentences(para)
                current_passage = []
                current_length = 0
                
                for sent in sentences:
                    if current_length + len(sent) > 500 and current_passage:
                        passages.append(' '.join(current_passage))
                        current_passage = [sent]
                        current_length = len(sent)
                    else:
                        current_passage.append(sent)
                        current_length += len(sent)
                
                if current_passage:
                    passages.append(' '.join(current_passage))
        
        return passages
    
    def _split_sentences(self, text: str) -> List[str]:
        """Basic sentence splitting (production: use spaCy/NLTK)."""
        import re
        return re.split(r'[.!?]+\s+', text)
    
    def _generate_evidence_id(self, url: str, passage: str) -> str:
        """Generate deterministic evidence ID."""
        raw = f"{url}|{passage[:100]}"
        return "evd_" + hashlib.sha256(raw.encode()).hexdigest()[:16]
```

**Relevance Scorer**:

```python
class RelevanceScorer:
    """
    Scores passage relevance to hypothesis and change event.
    
    Scoring factors:
    1. Keyword overlap (product, brand, merchant names)
    2. Hypothesis-specific keywords (sale, promotion, competitor, etc.)
    3. Temporal proximity mentions (dates near event)
    4. Numeric values (prices, percentages)
    5. Semantic similarity (optional: using embeddings)
    """
    
    def __init__(self, min_relevance_threshold: float = 0.3):
        self.min_relevance_threshold = min_relevance_threshold
    
    def compute_relevance(
        self, 
        passage: str, 
        hypothesis: Hypothesis,
        change_event: ChangeEvent
    ) -> float:
        """
        Compute relevance score [0.0, 1.0].
        
        Weighted combination:
        - Entity match: 0.4
        - Hypothesis keywords: 0.3
        - Temporal signals: 0.2
        - Numeric signals: 0.1
        """
        passage_lower = passage.lower()
        
        # Entity matching
        entity_score = self._entity_match_score(passage_lower, change_event)
        
        # Hypothesis-specific keywords
        keyword_score = self._keyword_match_score(passage_lower, hypothesis)
        
        # Temporal proximity
        temporal_score = self._temporal_score(passage, change_event)
        
        # Numeric signals (prices, percentages)
        numeric_score = self._numeric_score(passage, change_event)
        
        # Weighted combination
        relevance = (
            0.4 * entity_score +
            0.3 * keyword_score +
            0.2 * temporal_score +
            0.1 * numeric_score
        )
        
        return min(relevance, 1.0)
    
    def _entity_match_score(self, passage: str, change_event: ChangeEvent) -> float:
        """Score based on product/brand/merchant mentions."""
        score = 0.0
        
        # Product name match (highest weight)
        if change_event.product_name.lower() in passage:
            score += 0.5
        
        # Brand match
        if change_event.brand.lower() in passage:
            score += 0.3
        
        # Merchant match
        if change_event.merchant.lower() in passage:
            score += 0.2
        
        return min(score, 1.0)
    
    def _keyword_match_score(self, passage: str, hypothesis: Hypothesis) -> float:
        """Score based on hypothesis-specific keywords."""
        keyword_sets = {
            HypothesisType.PROMOTION: [
                "sale", "discount", "promotion", "deal", "offer", "coupon"
            ],
            HypothesisType.COMPETITOR_RESPONSE: [
                "competitor", "compete", "match", "undercut", "price war"
            ],
            HypothesisType.INVENTORY_LIQUIDATION: [
                "clearance", "liquidation", "stock", "inventory", "overstocked"
            ],
            # ... additional keyword sets
        }
        
        keywords = keyword_sets.get(hypothesis.hypothesis_type, [])
        matches = sum(1 for kw in keywords if kw in passage)
        
        return min(matches / len(keywords) if keywords else 0.0, 1.0)
    
    def _temporal_score(self, passage: str, change_event: ChangeEvent) -> float:
        """Score based on temporal proximity mentions."""
        # Extract dates from passage (basic implementation)
        # Production: use dateutil.parser or regex patterns
        import re
        date_patterns = re.findall(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', passage)
        
        if date_patterns:
            # Check if any date is within 7 days of change_event.observed_at
            # Simplified: just return 1.0 if dates found
            return 1.0
        
        return 0.0
    
    def _numeric_score(self, passage: str, change_event: ChangeEvent) -> float:
        """Score based on numeric values (prices, percentages)."""
        import re
        
        # Find price-like patterns
        price_patterns = re.findall(r'\$\d+(?:\.\d{2})?', passage)
        
        # Find percentage patterns
        pct_patterns = re.findall(r'\d+(?:\.\d+)?%', passage)
        
        score = 0.0
        if price_patterns:
            score += 0.5
        if pct_patterns:
            score += 0.5
        
        return min(score, 1.0)
```

**HTML/Text Parser**:

```python
class SearchResultParser:
    """
    Parses HTML and text content from search results.
    
    Handles:
    - HTML tag removal (preserving structure)
    - Script/style/nav removal
    - Character encoding
    - Malformed HTML
    - Anti-scraping detection
    - Content truncation
    """
    
    def __init__(self, max_content_size: int = 100_000):
        self.max_content_size = max_content_size
    
    def parse(self, content: str) -> ParsedContent:
        """
        Parse HTML or text content.
        
        Returns ParsedContent with extracted text and metadata.
        """
        error_messages = []
        truncated = False
        
        # Detect anti-scraping
        if self._is_anti_scraping(content):
            return ParsedContent(
                extracted_text="",
                parse_success=False,
                error_messages=["Anti-scraping pattern detected (CAPTCHA or rate limit)"],
                truncated=False
            )
        
        # Truncate if too large
        if len(content) > self.max_content_size:
            content = content[:self.max_content_size]
            truncated = True
            error_messages.append(f"Content truncated to {self.max_content_size} bytes")
        
        # Parse HTML
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove unwanted elements
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                tag.decompose()
            
            # Extract text with paragraph boundaries
            text_parts = []
            for elem in soup.find_all(['p', 'div', 'article', 'section']):
                text = elem.get_text(separator=' ', strip=True)
                if text:
                    text_parts.append(text)
            
            extracted_text = '\n\n'.join(text_parts)
            
            # Handle encoding
            extracted_text = self._normalize_encoding(extracted_text)
            
            return ParsedContent(
                extracted_text=extracted_text,
                parse_success=True,
                error_messages=error_messages,
                truncated=truncated
            )
            
        except Exception as e:
            error_messages.append(f"Parse error: {str(e)}")
            
            # Fallback: basic text extraction
            try:
                import re
                text = re.sub(r'<[^>]+>', '', content)
                text = self._normalize_encoding(text)
                
                return ParsedContent(
                    extracted_text=text,
                    parse_success=True,
                    error_messages=error_messages + ["Fell back to basic text extraction"],
                    truncated=truncated
                )
            except Exception as e2:
                return ParsedContent(
                    extracted_text="",
                    parse_success=False,
                    error_messages=error_messages + [f"Fallback failed: {str(e2)}"],
                    truncated=truncated
                )
    
    def _is_anti_scraping(self, content: str) -> bool:
        """Detect common anti-scraping patterns."""
        content_lower = content.lower()
        patterns = [
            "captcha",
            "verify you are human",
            "rate limit exceeded",
            "access denied",
            "blocked"
        ]
        return any(pattern in content_lower for pattern in patterns)
    
    def _normalize_encoding(self, text: str) -> str:
        """Normalize character encoding to UTF-8."""
        # Handle common encoding issues
        text = text.encode('utf-8', errors='ignore').decode('utf-8')
        return text
    
    def pretty_print(self, parsed: ParsedContent) -> str:
        """Format ParsedContent for display."""
        lines = []
        lines.append(f"Parse Success: {parsed.parse_success}")
        
        if parsed.error_messages:
            lines.append(f"Errors: {', '.join(parsed.error_messages)}")
        
        if parsed.truncated:
            lines.append("Content was truncated")
        
        lines.append(f"\nExtracted Text ({len(parsed.extracted_text)} chars):")
        lines.append("-" * 60)
        lines.append(parsed.extracted_text[:500])
        if len(parsed.extracted_text) > 500:
            lines.append("... (truncated for display)")
        
        return '\n'.join(lines)
```

### 4.5. Source Independence Detection

**Purpose**: Distinguish independent sources from duplicated/syndicated content to avoid false confidence from counting the same article multiple times.

**CRITICAL REQUIREMENT**: The system must detect when multiple Evidence objects contain duplicated or syndicated content from the same original article, preventing the false impression of independent confirmation.

**SourceIndependenceAnalyzer**:

```python
from enum import Enum
from typing import List, Dict, Set, Tuple

class SourceIndependenceClass(Enum):
    INDEPENDENT = "independent"  # Unique original content
    DUPLICATED = "duplicated"    # Exact copy from another source
    SYNDICATED = "syndicated"    # Republished with attribution
    CONTRADICTING = "contradicting"  # Conflicting claims about same event

class SourceIndependenceAnalyzer:
    """
    Analyzes evidence pools to detect independent vs duplicated/syndicated sources.
    
    Detection Methods:
    1. Content Similarity: Detect identical or near-identical passages
    2. Attribution Analysis: Identify "Originally published at", "Source:", "Via:"
    3. Domain Analysis: Same source_domain = likely same source
    4. Author Analysis: Same author across different domains
    5. Publication Date: Identical dates suggest syndication
    6. Source Title: Identical titles across domains
    """
    
    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold
    
    def analyze_independence(
        self, 
        evidence_pool: List[Evidence]
    ) -> SourceIndependenceResult:
        """
        Analyze source independence for an evidence pool.
        
        Returns:
        - source_independence_graph: Relationships between sources
        - independence_classifications: Per-evidence classification
        - independent_source_count: Number of truly independent sources
        - duplicated_source_count: Number of duplicated/syndicated sources
        """
        # Build similarity matrix
        similarity_matrix = self._compute_similarity_matrix(evidence_pool)
        
        # Detect attribution statements
        attribution_map = self._detect_attributions(evidence_pool)
        
        # Detect domain clustering
        domain_clusters = self._cluster_by_domain(evidence_pool)
        
        # Build independence graph
        graph = self._build_independence_graph(
            evidence_pool, 
            similarity_matrix, 
            attribution_map, 
            domain_clusters
        )
        
        # Classify each evidence source
        classifications = self._classify_sources(graph, evidence_pool)
        
        # Count independent vs duplicated
        independent_count = sum(
            1 for c in classifications.values() 
            if c == SourceIndependenceClass.INDEPENDENT
        )
        duplicated_count = len(evidence_pool) - independent_count
        
        return SourceIndependenceResult(
            source_independence_graph=graph,
            independence_classifications=classifications,
            independent_source_count=independent_count,
            duplicated_source_count=duplicated_count
        )
    
    def _compute_similarity_matrix(
        self, 
        evidence_pool: List[Evidence]
    ) -> Dict[Tuple[str, str], float]:
        """
        Compute pairwise content similarity between all evidence.
        
        Uses:
        - Character n-gram overlap (for exact/near-exact matches)
        - Sentence-level comparison
        - Threshold: 0.85 or higher indicates likely duplication
        """
        similarity_matrix = {}
        
        for i, ev1 in enumerate(evidence_pool):
            for j, ev2 in enumerate(evidence_pool):
                if i >= j:
                    continue
                
                sim = self._compute_text_similarity(
                    ev1.evidence_text, 
                    ev2.evidence_text
                )
                similarity_matrix[(ev1.evidence_id, ev2.evidence_id)] = sim
        
        return similarity_matrix
    
    def _compute_text_similarity(self, text1: str, text2: str) -> float:
        """
        Compute text similarity score [0.0, 1.0].
        
        Method: Character 3-gram Jaccard similarity
        (Fast and effective for detecting near-duplicates)
        """
        def get_ngrams(text: str, n: int = 3) -> Set[str]:
            text = text.lower().replace(" ", "")
            return set(text[i:i+n] for i in range(len(text) - n + 1))
        
        ngrams1 = get_ngrams(text1)
        ngrams2 = get_ngrams(text2)
        
        if not ngrams1 or not ngrams2:
            return 0.0
        
        intersection = ngrams1 & ngrams2
        union = ngrams1 | ngrams2
        
        return len(intersection) / len(union) if union else 0.0
    
    def _detect_attributions(
        self, 
        evidence_pool: List[Evidence]
    ) -> Dict[str, Optional[str]]:
        """
        Detect attribution statements in evidence text.
        
        Patterns:
        - "Originally published at [source]"
        - "Source: [source]"
        - "Via [source]"
        - "Republished from [source]"
        - "[source] reports that"
        """
        attribution_patterns = [
            r"originally published (?:at|in|by)\s+([^\n\.]+)",
            r"source:\s*([^\n\.]+)",
            r"via\s+([^\n\.]+)",
            r"republished from\s+([^\n\.]+)",
            r"([^\s]+\.[com|org|net]+)\s+reports? that",
        ]
        
        attribution_map = {}
        
        for evidence in evidence_pool:
            text_lower = evidence.evidence_text.lower()
            attributed_source = None
            
            for pattern in attribution_patterns:
                import re
                match = re.search(pattern, text_lower)
                if match:
                    attributed_source = match.group(1).strip()
                    break
            
            attribution_map[evidence.evidence_id] = attributed_source
        
        return attribution_map
    
    def _cluster_by_domain(
        self, 
        evidence_pool: List[Evidence]
    ) -> Dict[str, List[str]]:
        """
        Group evidence by source_domain.
        
        Multiple evidence from same domain likely share original source.
        """
        domain_clusters = {}
        
        for evidence in evidence_pool:
            domain = evidence.source_domain
            if domain not in domain_clusters:
                domain_clusters[domain] = []
            domain_clusters[domain].append(evidence.evidence_id)
        
        return domain_clusters
    
    def _build_independence_graph(
        self,
        evidence_pool: List[Evidence],
        similarity_matrix: Dict[Tuple[str, str], float],
        attribution_map: Dict[str, Optional[str]],
        domain_clusters: Dict[str, List[str]]
    ) -> Dict[str, Set[str]]:
        """
        Build graph of evidence relationships.
        
        Edges represent:
        - High similarity (>= threshold)
        - Attribution relationship
        - Same domain
        """
        graph = {ev.evidence_id: set() for ev in evidence_pool}
        
        # Add similarity edges
        for (ev1_id, ev2_id), sim in similarity_matrix.items():
            if sim >= self.similarity_threshold:
                graph[ev1_id].add(ev2_id)
                graph[ev2_id].add(ev1_id)
        
        # Add attribution edges
        for ev_id, attributed_source in attribution_map.items():
            if attributed_source:
                # Find evidence from attributed source domain
                for evidence in evidence_pool:
                    if attributed_source in evidence.source_domain:
                        graph[ev_id].add(evidence.evidence_id)
        
        # Add domain clustering edges (weak signal, only for same domain with similar content)
        for domain, ev_ids in domain_clusters.items():
            if len(ev_ids) > 1:
                # Only link if similar content
                for i, ev1_id in enumerate(ev_ids):
                    for ev2_id in ev_ids[i+1:]:
                        if (ev1_id, ev2_id) in similarity_matrix:
                            if similarity_matrix[(ev1_id, ev2_id)] > 0.5:
                                graph[ev1_id].add(ev2_id)
                                graph[ev2_id].add(ev1_id)
        
        return graph
    
    def _classify_sources(
        self,
        graph: Dict[str, Set[str]],
        evidence_pool: List[Evidence]
    ) -> Dict[str, SourceIndependenceClass]:
        """
        Classify each evidence source.
        
        Logic:
        - INDEPENDENT: No edges in graph (unique content)
        - DUPLICATED: Has edges (similar content to other sources)
        - SYNDICATED: Has attribution statement
        - CONTRADICTING: Detected elsewhere (not in this method)
        """
        classifications = {}
        
        # Build evidence map
        ev_map = {ev.evidence_id: ev for ev in evidence_pool}
        
        for ev_id, neighbors in graph.items():
            if not neighbors:
                # No relationships = independent
                classifications[ev_id] = SourceIndependenceClass.INDEPENDENT
            else:
                # Has relationships = duplicated/syndicated
                # Check if this is the "original" (earliest publication date)
                evidence = ev_map[ev_id]
                
                # Simplified: mark as duplicated
                # Production: compare publication dates to identify original
                classifications[ev_id] = SourceIndependenceClass.DUPLICATED
        
        return classifications

@dataclass
class SourceIndependenceResult:
    source_independence_graph: Dict[str, Set[str]]
    independence_classifications: Dict[str, SourceIndependenceClass]
    independent_source_count: int
    duplicated_source_count: int
    
    def get_independent_evidence_ids(self) -> List[str]:
        """Return evidence IDs classified as INDEPENDENT."""
        return [
            ev_id for ev_id, classification in self.independence_classifications.items()
            if classification == SourceIndependenceClass.INDEPENDENT
        ]
```

**Integration with Verification**:

The source independence analysis feeds directly into the Verification Agent's multi-dimensional assessment. Independent sources receive higher weight in confidence calculations, while duplicated/syndicated sources are downweighted to avoid false confidence.

### 5. Verification Agent (Multi-Dimensional Assessment)

**CRITICAL CHANGES FROM PREVIOUS DESIGN:**
- **8 evaluation criteria** (not just quality scoring)
- **5 support levels**: SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS
- **Conservative language**: Don't claim "X caused Y" without genuine evidence of causality
- **Source independence integration**: Weight independent sources heavily
- **Multiple hypotheses support**: NO forced "winner selection"

**Verification Agent**:

```python
from enum import Enum

class SupportLevel(Enum):
    SUPPORTS = "supports"  # Strong causal evidence
    PARTIALLY_SUPPORTS = "partially_supports"  # Some supporting evidence
    CONSISTENT_WITH = "consistent_with"  # Temporal alignment, no causality
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # Too little data
    CONTRADICTS = "contradicts"  # Evidence against hypothesis

class VerificationAgent:
    """
    Independent verification of evidence quality using multi-dimensional assessment.
    
    8 Evaluation Criteria:
    1. Source-Hypothesis Alignment: Does the source discuss the hypothesis topic?
    2. Product/Merchant Match: Does the evidence mention specific product/merchant?
    3. Temporal Alignment: Is the evidence temporally proximate to the event?
    4. Specificity: Does the evidence provide concrete details or vague claims?
    5. Direct vs Inferred: Is this direct evidence or indirect inference?
    6. Source Independence: Is this an independent source or duplicated content?
    7. Contradictions: Does this evidence contradict other evidence?
    8. Causality vs Correlation: Does the evidence claim causation or just correlation?
    
    Conservative Language Rules:
    - Don't claim "X caused Y" unless causality is genuinely established
    - Temporal alignment alone = CONSISTENT_WITH, not SUPPORTS
    - Require corroboration from independent sources for SUPPORTS
    - Distinguish direct evidence from category-level inference
    """
    
    def __init__(self, config: VerificationConfig):
        self.config = config
        self.independence_analyzer = SourceIndependenceAnalyzer()
    
    def verify(
        self, 
        evidence_pool: List[Evidence], 
        hypotheses: List[Hypothesis],
        change_event: ChangeEvent
    ) -> VerificationOutput:
        """
        Verify evidence quality and determine support levels.
        
        Returns:
        - Per-evidence verification results
        - Per-hypothesis support assessments
        - Source independence analysis
        - Overall quality metrics
        """
        # Analyze source independence FIRST
        independence_result = self.independence_analyzer.analyze_independence(evidence_pool)
        
        # Verify each evidence piece
        evidence_verifications = []
        for evidence in evidence_pool:
            verification = self._verify_single_evidence(
                evidence, 
                change_event,
                independence_result
            )
            evidence_verifications.append(verification)
        
        # Assess support for each hypothesis
        hypothesis_assessments = {}
        for hypothesis in hypotheses:
            assessment = self._assess_hypothesis_support(
                hypothesis,
                evidence_pool,
                evidence_verifications,
                independence_result
            )
            hypothesis_assessments[hypothesis.hypothesis_type.value] = assessment
        
        return VerificationOutput(
            evidence_verifications=evidence_verifications,
            hypothesis_assessments=hypothesis_assessments,
            source_independence_result=independence_result
        )
    
    def _verify_single_evidence(
        self,
        evidence: Evidence,
        change_event: ChangeEvent,
        independence_result: SourceIndependenceResult
    ) -> EvidenceVerification:
        """
        Verify a single evidence piece across all 8 criteria.
        """
        # Criterion 1: Source-Hypothesis Alignment
        hypothesis_alignment = self._assess_hypothesis_alignment(evidence)
        
        # Criterion 2: Product/Merchant Match
        product_match = self._assess_product_match(evidence, change_event)
        
        # Criterion 3: Temporal Alignment
        temporal_alignment = self._assess_temporal_alignment(evidence, change_event)
        
        # Criterion 4: Specificity
        specificity = self._assess_specificity(evidence)
        
        # Criterion 5: Direct vs Inferred Evidence
        evidence_directness = self._assess_directness(evidence, change_event)
        
        # Criterion 6: Source Independence
        source_independence = independence_result.independence_classifications.get(
            evidence.evidence_id,
            SourceIndependenceClass.INDEPENDENT
        )
        
        # Criterion 7: Contradictions (checked against other evidence)
        # Will be filled in during hypothesis assessment
        contradictions = []
        
        # Criterion 8: Causality vs Correlation
        causality_classification = self._classify_causality(evidence)
        
        # Compute overall quality score
        quality_score = self._compute_quality_score(
            hypothesis_alignment,
            product_match,
            temporal_alignment,
            specificity,
            evidence_directness,
            source_independence,
            causality_classification
        )
        
        return EvidenceVerification(
            evidence_id=evidence.evidence_id,
            hypothesis_alignment=hypothesis_alignment,
            product_match=product_match,
            temporal_alignment=temporal_alignment,
            specificity=specificity,
            evidence_directness=evidence_directness,
            source_independence=source_independence,
            contradictions=contradictions,
            causality_classification=causality_classification,
            quality_score=quality_score,
            verification_notes=self._generate_verification_notes(
                hypothesis_alignment, product_match, temporal_alignment,
                specificity, evidence_directness, source_independence,
                causality_classification
            )
        )
    
    def _assess_hypothesis_alignment(self, evidence: Evidence) -> float:
        """
        Criterion 1: Does the source discuss the hypothesis topic?
        
        Returns score [0.0, 1.0]
        """
        # Map hypothesis type to required keywords
        hypothesis_keywords = {
            HypothesisType.PROMOTION: ["sale", "discount", "promotion", "deal", "offer"],
            HypothesisType.COMPETITOR_RESPONSE: ["competitor", "compete", "price war", "match"],
            HypothesisType.INVENTORY_LIQUIDATION: ["clearance", "liquidation", "stock", "inventory"],
            HypothesisType.PRODUCT_EVENT: ["launch", "discontinue", "new product", "end of life"],
            HypothesisType.SEASONAL_EVENT: ["holiday", "seasonal", "black friday", "cyber monday"],
            HypothesisType.MARKET_EVENT: ["market", "industry", "trend", "economic"],
            HypothesisType.MANUFACTURER_CHANGE: ["MSRP", "manufacturer", "price change"],
            HypothesisType.DATA_ISSUE: ["error", "incorrect", "data"],
        }
        
        keywords = hypothesis_keywords.get(evidence.hypothesis_type, [])
        text_lower = evidence.evidence_text.lower()
        
        matches = sum(1 for kw in keywords if kw in text_lower)
        return min(matches / len(keywords), 1.0) if keywords else 0.5
    
    def _assess_product_match(self, evidence: Evidence, change_event: ChangeEvent) -> float:
        """
        Criterion 2: Does evidence mention specific product/merchant?
        
        Scoring:
        - 1.0: Mentions product name AND merchant
        - 0.7: Mentions product name OR merchant
        - 0.4: Mentions brand or category
        - 0.0: No mention
        """
        text_lower = evidence.evidence_text.lower()
        product_lower = change_event.product_name.lower()
        merchant_lower = change_event.merchant.lower()
        brand_lower = change_event.brand.lower() if hasattr(change_event, 'brand') else ""
        
        has_product = product_lower in text_lower
        has_merchant = merchant_lower in text_lower
        has_brand = brand_lower in text_lower if brand_lower else False
        
        if has_product and has_merchant:
            return 1.0
        elif has_product or has_merchant:
            return 0.7
        elif has_brand:
            return 0.4
        else:
            return 0.0
    
    def _assess_temporal_alignment(self, evidence: Evidence, change_event: ChangeEvent) -> float:
        """
        Criterion 3: Is evidence temporally proximate to event?
        
        Checks:
        - publication_date within 30 days of event = 1.0
        - publication_date within 90 days = 0.7
        - Contains temporal keywords = 0.5
        - No temporal info = 0.3
        """
        # Simplified implementation
        # Production: parse dates and compute delta
        text_lower = evidence.evidence_text.lower()
        
        temporal_keywords = ["today", "yesterday", "this week", "recently", "now", "just announced"]
        if any(kw in text_lower for kw in temporal_keywords):
            return 0.8
        
        import re
        if re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', evidence.evidence_text):
            return 0.6
        
        return 0.3
    
    def _assess_specificity(self, evidence: Evidence) -> float:
        """
        Criterion 4: Does evidence provide concrete details?
        
        Indicators:
        - Quantitative data (prices, percentages, numbers)
        - Named entities (specific people, companies, locations)
        - Dates and times
        - Specific claims vs vague statements
        """
        text = evidence.evidence_text
        score = 0.0
        
        # Check for prices
        import re
        if re.search(r'\$\d+', text):
            score += 0.3
        
        # Check for percentages
        if re.search(r'\d+%', text):
            score += 0.3
        
        # Check for dates
        if re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', text):
            score += 0.2
        
        # Check for specific numbers
        if re.search(r'\b\d+\b', text):
            score += 0.2
        
        return min(score, 1.0)
    
    def _assess_directness(self, evidence: Evidence, change_event: ChangeEvent) -> str:
        """
        Criterion 5: Direct vs Inferred Evidence
        
        Returns: "DIRECT", "INDIRECT", "INFERRED"
        """
        text_lower = evidence.evidence_text.lower()
        product_lower = change_event.product_name.lower()
        merchant_lower = change_event.merchant.lower()
        
        # Direct: mentions specific product AND merchant
        if product_lower in text_lower and merchant_lower in text_lower:
            return "DIRECT"
        
        # Indirect: mentions product OR merchant OR category
        if product_lower in text_lower or merchant_lower in text_lower:
            return "INDIRECT"
        
        # Inferred: category/market level only
        return "INFERRED"
    
    def _classify_causality(self, evidence: Evidence) -> str:
        """
        Criterion 8: Causality vs Correlation
        
        Returns: "CAUSAL", "CORRELATIONAL", "INSUFFICIENT"
        """
        text_lower = evidence.evidence_text.lower()
        
        # Causal indicators
        causal_keywords = [
            "because", "due to", "caused by", "resulted from", "led to",
            "triggered by", "driven by", "as a result of", "resulting in"
        ]
        if any(kw in text_lower for kw in causal_keywords):
            return "CAUSAL"
        
        # Correlational indicators
        correlational_keywords = [
            "coincides with", "during", "at the same time", "while",
            "alongside", "concurrent", "around the time"
        ]
        if any(kw in text_lower for kw in correlational_keywords):
            return "CORRELATIONAL"
        
        # Check for sufficient detail
        if len(evidence.evidence_text) < 50:
            return "INSUFFICIENT"
        
        # Default: correlational (observational without causal language)
        return "CORRELATIONAL"
    
    def _compute_quality_score(
        self,
        hypothesis_alignment: float,
        product_match: float,
        temporal_alignment: float,
        specificity: float,
        evidence_directness: str,
        source_independence: SourceIndependenceClass,
        causality_classification: str
    ) -> float:
        """
        Compute overall quality score [0.0, 1.0].
        
        Weighted combination of all criteria.
        """
        # Base score from quantitative criteria
        base_score = (
            0.15 * hypothesis_alignment +
            0.20 * product_match +
            0.15 * temporal_alignment +
            0.15 * specificity
        )
        
        # Directness bonus
        directness_bonus = {
            "DIRECT": 0.15,
            "INDIRECT": 0.10,
            "INFERRED": 0.05
        }.get(evidence_directness, 0.05)
        base_score += directness_bonus
        
        # Source independence bonus (CRITICAL)
        independence_bonus = {
            SourceIndependenceClass.INDEPENDENT: 0.15,
            SourceIndependenceClass.SYNDICATED: 0.05,
            SourceIndependenceClass.DUPLICATED: 0.02,
            SourceIndependenceClass.CONTRADICTING: 0.00
        }.get(source_independence, 0.10)
        base_score += independence_bonus
        
        # Causality bonus
        causality_bonus = {
            "CAUSAL": 0.10,
            "CORRELATIONAL": 0.05,
            "INSUFFICIENT": 0.00
        }.get(causality_classification, 0.03)
        base_score += causality_bonus
        
        return min(base_score, 1.0)
    
    def _assess_hypothesis_support(
        self,
        hypothesis: Hypothesis,
        evidence_pool: List[Evidence],
        evidence_verifications: List[EvidenceVerification],
        independence_result: SourceIndependenceResult
    ) -> HypothesisSupportAssessment:
        """
        Assess overall support level for a hypothesis.
        
        Support Levels (CONSERVATIVE):
        - SUPPORTS: Strong causal evidence from independent sources
        - PARTIALLY_SUPPORTS: Some supporting evidence, may be correlational
        - CONSISTENT_WITH: Temporal alignment only, no causality
        - INSUFFICIENT_EVIDENCE: Too little data to assess
        - CONTRADICTS: Evidence against the hypothesis
        """
        # Filter evidence for this hypothesis
        hypothesis_evidence = [
            (ev, ver) for ev, ver in zip(evidence_pool, evidence_verifications)
            if ev.hypothesis_type == hypothesis.hypothesis_type
        ]
        
        if not hypothesis_evidence:
            return HypothesisSupportAssessment(
                hypothesis_type=hypothesis.hypothesis_type,
                support_level=SupportLevel.INSUFFICIENT_EVIDENCE,
                supporting_evidence_ids=[],
                quality_metrics={},
                explanation="No evidence found for this hypothesis."
            )
        
        # Compute metrics
        evidence_count = len(hypothesis_evidence)
        avg_quality = sum(ver.quality_score for _, ver in hypothesis_evidence) / evidence_count
        
        # Count independent sources
        independent_count = sum(
            1 for ev, ver in hypothesis_evidence
            if ver.source_independence == SourceIndependenceClass.INDEPENDENT
        )
        
        # Count causal evidence
        causal_count = sum(
            1 for _, ver in hypothesis_evidence
            if ver.causality_classification == "CAUSAL"
        )
        
        # Determine support level (CONSERVATIVE RULES)
        support_level = self._determine_support_level(
            evidence_count,
            independent_count,
            causal_count,
            avg_quality
        )
        
        return HypothesisSupportAssessment(
            hypothesis_type=hypothesis.hypothesis_type,
            support_level=support_level,
            supporting_evidence_ids=[ev.evidence_id for ev, _ in hypothesis_evidence],
            quality_metrics={
                "evidence_count": evidence_count,
                "avg_quality_score": avg_quality,
                "independent_source_count": independent_count,
                "causal_evidence_count": causal_count
            },
            explanation=self._generate_support_explanation(
                support_level, evidence_count, independent_count, causal_count, avg_quality
            )
        )
    
    def _determine_support_level(
        self,
        evidence_count: int,
        independent_count: int,
        causal_count: int,
        avg_quality: float
    ) -> SupportLevel:
        """
        Determine support level using CONSERVATIVE rules.
        
        SUPPORTS requires:
        - At least 2 independent sources
        - At least 1 causal evidence
        - Avg quality >= 0.6
        
        PARTIALLY_SUPPORTS requires:
        - At least 2 evidence pieces
        - Avg quality >= 0.4
        
        CONSISTENT_WITH:
        - Some evidence with temporal alignment
        - No causal claims
        """
        if independent_count >= 2 and causal_count >= 1 and avg_quality >= 0.6:
            return SupportLevel.SUPPORTS
        elif evidence_count >= 2 and avg_quality >= 0.4:
            if causal_count >= 1:
                return SupportLevel.PARTIALLY_SUPPORTS
            else:
                return SupportLevel.CONSISTENT_WITH
        elif evidence_count >= 1:
            return SupportLevel.CONSISTENT_WITH
        else:
            return SupportLevel.INSUFFICIENT_EVIDENCE
    
    def _generate_verification_notes(
        self,
        hypothesis_alignment: float,
        product_match: float,
        temporal_alignment: float,
        specificity: float,
        evidence_directness: str,
        source_independence: SourceIndependenceClass,
        causality_classification: str
    ) -> str:
        """Generate human-readable verification notes."""
        notes = []
        
        if product_match >= 0.7:
            notes.append("Strong product/merchant match")
        elif product_match < 0.4:
            notes.append("Weak product/merchant match")
        
        if causality_classification == "CAUSAL":
            notes.append("Contains causal language")
        elif causality_classification == "CORRELATIONAL":
            notes.append("Correlational observation only")
        else:
            notes.append("Insufficient detail for classification")
        
        if source_independence == SourceIndependenceClass.INDEPENDENT:
            notes.append("Independent source")
        elif source_independence == SourceIndependenceClass.DUPLICATED:
            notes.append("Duplicated/syndicated content")
        
        if evidence_directness == "DIRECT":
            notes.append("Direct evidence")
        else:
            notes.append(f"{evidence_directness.capitalize()} evidence")
        
        return "; ".join(notes)
    
    def _generate_support_explanation(
        self,
        support_level: SupportLevel,
        evidence_count: int,
        independent_count: int,
        causal_count: int,
        avg_quality: float
    ) -> str:
        """Generate human-readable explanation of support level."""
        if support_level == SupportLevel.SUPPORTS:
            return (
                f"Strong support with {independent_count} independent sources and "
                f"{causal_count} causal evidence pieces (avg quality: {avg_quality:.2f})"
            )
        elif support_level == SupportLevel.PARTIALLY_SUPPORTS:
            return (
                f"Partial support with {evidence_count} evidence pieces, "
                f"{independent_count} independent (avg quality: {avg_quality:.2f})"
            )
        elif support_level == SupportLevel.CONSISTENT_WITH:
            return (
                f"Consistent with hypothesis but lacks causal evidence "
                f"({evidence_count} pieces, {independent_count} independent)"
            )
        elif support_level == SupportLevel.INSUFFICIENT_EVIDENCE:
            return "Insufficient evidence to assess hypothesis"
        else:
            return "Evidence contradicts hypothesis"
```

**Data Models for Verification**:

```python
@dataclass
class EvidenceVerification:
    evidence_id: str
    hypothesis_alignment: float  # [0.0, 1.0]
    product_match: float  # [0.0, 1.0]
    temporal_alignment: float  # [0.0, 1.0]
    specificity: float  # [0.0, 1.0]
    evidence_directness: str  # "DIRECT" | "INDIRECT" | "INFERRED"
    source_independence: SourceIndependenceClass
    contradictions: List[str]  # Evidence IDs that contradict this
    causality_classification: str  # "CAUSAL" | "CORRELATIONAL" | "INSUFFICIENT"
    quality_score: float  # [0.0, 1.0]
    verification_notes: str

@dataclass
class HypothesisSupportAssessment:
    hypothesis_type: HypothesisType
    support_level: SupportLevel
    supporting_evidence_ids: List[str]
    quality_metrics: Dict[str, float]
    explanation: str

@dataclass
class VerificationOutput:
    evidence_verifications: List[EvidenceVerification]
    hypothesis_assessments: Dict[str, HypothesisSupportAssessment]
    source_independence_result: SourceIndependenceResult
```
    """
    Independent verification of evidence quality and causal claims.
    
    Responsibilities:
    1. Score evidence quality (source authority, specificity, temporal proximity)
    2. Classify claims as CAUSAL, CORRELATIONAL, or INSUFFICIENT
    3. Detect contradictory evidence
    4. Compute overall assessment confidence
    """
    
    def __init__(self, config: VerificationConfig):
        self.config = config
    
    def verify(
        self, 
        evidence_pool: List[Evidence], 
        hypotheses: List[Hypothesis],
        change_event: ChangeEvent
    ) -> List[VerificationResult]:
        """
        Verify evidence quality and consistency.
        
        Returns one VerificationResult per Evidence object.
        """
        results = []
        
        for evidence in evidence_pool:
            quality_score = self._compute_quality_score(evidence, change_event)
            claim_type = self._classify_claim(evidence)
            contradictions = self._find_contradictions(evidence, evidence_pool)
            
            result = VerificationResult(
                evidence_id=evidence.evidence_id,
                quality_score=quality_score,
                claim_type=claim_type,
                contradictions=contradictions,
                verification_notes=self._generate_notes(evidence, quality_score, claim_type)
            )
            results.append(result)
        
        return results
    
    def _compute_quality_score(self, evidence: Evidence, change_event: ChangeEvent) -> float:
        """
        Compute evidence quality score [0.0, 1.0].
        
        Factors:
        - Source authority (domain reputation)
        - Temporal proximity to event
        - Specificity (direct vs indirect evidence)
        - Presence of quantitative data
        """
        score = 0.0
        
        # Source authority
        authority = self._assess_source_authority(evidence.source_url)
        score += 0.3 * authority
        
        # Temporal proximity
        proximity = self._assess_temporal_proximity(evidence, change_event)
        score += 0.3 * proximity
        
        # Specificity
        specificity = self._assess_specificity(evidence, change_event)
        score += 0.2 * specificity
        
        # Quantitative data
        has_numbers = self._has_quantitative_data(evidence.passage_text)
        score += 0.2 * (1.0 if has_numbers else 0.0)
        
        return min(score, 1.0)
    
    def _assess_source_authority(self, url: str) -> float:
        """
        Assess source authority based on domain.
        
        Authority tiers:
        - High (0.8-1.0): Official sources, major news outlets
        - Medium (0.5-0.7): Industry publications, company blogs
        - Low (0.2-0.4): Forums, social media, unknown domains
        """
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        
        # High authority domains
        high_authority = [
            "nytimes.com", "wsj.com", "reuters.com", "bloomberg.com",
            "techcrunch.com", "theverge.com", "wired.com"
        ]
        if any(d in domain for d in high_authority):
            return 0.9
        
        # Medium authority (company domains, .edu)
        if ".edu" in domain or "blog" in domain:
            return 0.6
        
        # Low authority (forums, social media)
        low_authority = ["reddit.com", "twitter.com", "facebook.com", "forum"]
        if any(d in domain for d in low_authority):
            return 0.3
        
        # Default: medium-low
        return 0.5
    
    def _assess_temporal_proximity(self, evidence: Evidence, change_event: ChangeEvent) -> float:
        """
        Assess temporal proximity to change event.
        
        Closer in time = higher score.
        """
        # Simplified: check if evidence mentions dates
        # Production: parse dates and compute time delta
        passage_lower = evidence.passage_text.lower()
        
        temporal_keywords = ["today", "yesterday", "this week", "recently", "now"]
        if any(kw in passage_lower for kw in temporal_keywords):
            return 0.8
        
        # Check for date patterns
        import re
        if re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', evidence.passage_text):
            return 0.6
        
        return 0.3
    
    def _assess_specificity(self, evidence: Evidence, change_event: ChangeEvent) -> float:
        """
        Assess evidence specificity.
        
        Direct evidence (mentions specific product/merchant) > Indirect (category/market level).
        """
        passage_lower = evidence.passage_text.lower()
        
        # Direct: mentions product name AND merchant
        direct = (
            change_event.product_name.lower() in passage_lower and
            change_event.merchant.lower() in passage_lower
        )
        if direct:
            return 1.0
        
        # Semi-direct: mentions product OR merchant
        if (change_event.product_name.lower() in passage_lower or
            change_event.merchant.lower() in passage_lower):
            return 0.7
        
        # Indirect: mentions category/brand only
        if change_event.category.lower() in passage_lower:
            return 0.4
        
        return 0.2
    
    def _has_quantitative_data(self, passage: str) -> bool:
        """Check if passage contains quantitative data."""
        import re
        
        # Look for prices, percentages, numbers
        has_price = bool(re.search(r'\$\d+', passage))
        has_pct = bool(re.search(r'\d+%', passage))
        has_numbers = bool(re.search(r'\b\d+\b', passage))
        
        return has_price or has_pct or has_numbers
    
    def _classify_claim(self, evidence: Evidence) -> ClaimType:
        """
        Classify claim as CAUSAL, CORRELATIONAL, or INSUFFICIENT.
        
        Causal language: "because", "due to", "caused by", "resulted from"
        Correlational: "coincides with", "during", "at the same time"
        """
        passage_lower = evidence.passage_text.lower()
        
        # Causal indicators
        causal_keywords = [
            "because", "due to", "caused by", "resulted from", "led to",
            "triggered by", "driven by", "as a result of"
        ]
        if any(kw in passage_lower for kw in causal_keywords):
            return ClaimType.CAUSAL
        
        # Correlational indicators
        correlational_keywords = [
            "coincides with", "during", "at the same time", "while",
            "alongside", "concurrent"
        ]
        if any(kw in passage_lower for kw in correlational_keywords):
            return ClaimType.CORRELATIONAL
        
        # Check for sufficient detail
        if len(evidence.passage_text) < 50:
            return ClaimType.INSUFFICIENT
        
        # Default: correlational (observational without causal language)
        return ClaimType.CORRELATIONAL
    
    def _find_contradictions(
        self, 
        evidence: Evidence, 
        evidence_pool: List[Evidence]
    ) -> List[str]:
        """
        Detect contradictory evidence.
        
        Contradiction detection:
        - Same hypothesis type
        - Overlapping entities
        - Opposite claims (e.g., "price increase" vs "price decrease")
        """
        contradictions = []
        
        for other in evidence_pool:
            if other.evidence_id == evidence.evidence_id:
                continue
            
            # Same hypothesis type
            if other.hypothesis_type != evidence.hypothesis_type:
                continue
            
            # Check for contradictory language
            if self._are_contradictory(evidence.passage_text, other.passage_text):
                contradictions.append(other.evidence_id)
        
        return contradictions
    
    def _are_contradictory(self, text1: str, text2: str) -> bool:
        """
        Check if two passages are contradictory.
        
        Simple heuristic:
        - Both mention price/sale
        - One says increase, other says decrease
        - One says sale, other says no sale
        """
        t1_lower = text1.lower()
        t2_lower = text2.lower()
        
        # Price direction contradiction
        if ("increase" in t1_lower and "decrease" in t2_lower) or \
           ("decrease" in t1_lower and "increase" in t2_lower):
            return True
        
        # Sale contradiction
        if ("sale" in t1_lower and "no sale" in t2_lower) or \
           ("no sale" in t1_lower and "sale" in t2_lower):
            return True
        
        return False
    
    def _generate_notes(
        self, 
        evidence: Evidence, 
        quality_score: float, 
        claim_type: ClaimType
    ) -> str:
        """Generate human-readable verification notes."""
        notes = []
        
        if quality_score >= 0.7:
            notes.append("High-quality evidence")
        elif quality_score < 0.4:
            notes.append("Low-quality evidence")
        
        if claim_type == ClaimType.CAUSAL:
            notes.append("Contains causal language")
        elif claim_type == ClaimType.CORRELATIONAL:
            notes.append("Correlational observation only")
        else:
            notes.append("Insufficient detail for classification")
        
        return "; ".join(notes)
```

### 6. Orchestrator

**Orchestrator**:

```python
class InvestigationOrchestrator:
    """
    Coordinates the full investigation workflow.
    
    Workflow:
    1. Generate hypotheses
    2. Execute investigation agents (parallel)
    3. Aggregate evidence
    4. Verify evidence
    5. Compute assessment
    6. Serialize results
    """
    
    def __init__(
        self, 
        search_provider: SearchProvider,
        config: InvestigationConfig
    ):
        self.search_provider = search_provider
        self.config = config
        
        # Initialize components
        self.hypothesis_generator = HypothesisGenerator(config.hypothesis_config)
        self.verification_agent = VerificationAgent(config.verification_config)
        self.agent_registry = AgentRegistry()
        
        # Initialize agents
        self.agents = self._initialize_agents()
    
    def _initialize_agents(self) -> Dict[str, InvestigationAgent]:
        """Initialize all investigation agents."""
        agent_config = self.config.agent_config
        
        return {
            "promotion": Promotion_Agent(self.search_provider, agent_config),
            "competitor": Competitor_Agent(self.search_provider, agent_config),
            "product_event": Product_Event_Agent(self.search_provider, agent_config),
            "news": News_Agent(self.search_provider, agent_config),
            "retailer_event": Retailer_Event_Agent(self.search_provider, agent_config),
            "supply": Supply_Agent(self.search_provider, agent_config),
        }
    
    async def investigate_event(self, change_event: ChangeEvent) -> EventAssessment:
        """
        Full investigation pipeline for a single change event.
        
        Returns EventAssessment with hypotheses, evidence, verification, and uncertainty.
        """
        logger.info(f"Starting investigation for event {change_event.event_id}")
        
        # Step 1: Generate hypotheses
        hypotheses = self.hypothesis_generator.generate(change_event)
        logger.info(f"Generated {len(hypotheses)} hypotheses")
        
        # Step 2: Execute investigation agents
        evidence_pool = await self._execute_investigations(change_event, hypotheses)
        logger.info(f"Collected {len(evidence_pool)} pieces of evidence")
        
        # Step 3: Verify evidence
        verification_results = self.verification_agent.verify(
            evidence_pool, 
            hypotheses, 
            change_event
        )
        logger.info(f"Verified {len(verification_results)} evidence items")
        
        # Step 4: Compute assessment
        assessment = self._compute_assessment(
            change_event,
            hypotheses,
            evidence_pool,
            verification_results
        )
        
        logger.info(f"Assessment complete with confidence {assessment.overall_confidence:.2f}")
        return assessment
    
    async def _execute_investigations(
        self, 
        change_event: ChangeEvent, 
        hypotheses: List[Hypothesis]
    ) -> List[Evidence]:
        """
        Execute investigation agents in parallel.
        
        Error handling:
        - Agent failures are logged but don't stop other agents
        - Search failures retry up to max_retries
        - Partial results are aggregated
        """
        import asyncio
        
        tasks = []
        
        for hypothesis in hypotheses:
            # Get applicable agents
            agent_types = self.agent_registry.get_agents(hypothesis)
            
            for agent_type in agent_types:
                agent_name = agent_type.__name__.lower().replace("_agent", "")
                agent = self.agents.get(agent_name)
                
                if agent and agent.can_investigate(hypothesis):
                    # Create investigation task with error handling
                    task = self._safe_investigate(agent, change_event, hypothesis)
                    tasks.append(task)
        
        # Execute all tasks in parallel (up to parallel_agent_limit)
        evidence_lists = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results, filtering out failures
        evidence_pool = []
        for result in evidence_lists:
            if isinstance(result, Exception):
                logger.error(f"Investigation task failed: {result}")
            elif isinstance(result, list):
                evidence_pool.extend(result)
        
        return evidence_pool
    
    async def _safe_investigate(
        self, 
        agent: InvestigationAgent, 
        change_event: ChangeEvent, 
        hypothesis: Hypothesis
    ) -> List[Evidence]:
        """
        Safely execute agent investigation with retry logic.
        """
        for attempt in range(self.config.max_retries):
            try:
                evidence = await agent.investigate(change_event, hypothesis)
                return evidence
            
            except Exception as e:
                logger.warning(
                    f"Agent {agent.__class__.__name__} attempt {attempt + 1} failed: {e}"
                )
                
                if attempt == self.config.max_retries - 1:
                    logger.error(f"Agent {agent.__class__.__name__} exhausted retries")
                    return []
                
                # Exponential backoff
                await asyncio.sleep(2 ** attempt)
        
        return []
    
    def _compute_assessment(
        self,
        change_event: ChangeEvent,
        hypotheses: List[Hypothesis],
        evidence_pool: List[Evidence],
        verification_results: List[VerificationResult]
    ) -> EventAssessment:
        """
        Compute final event assessment with uncertainty quantification.
        """
        # Map verification results to evidence
        verification_map = {
            vr.evidence_id: vr for vr in verification_results
        }
        
        # Compute per-hypothesis evidence support
        hypothesis_support = self._compute_hypothesis_support(
            hypotheses,
            evidence_pool,
            verification_map
        )
        
        # Compute overall confidence
        overall_confidence = self._compute_overall_confidence(
            hypotheses,
            evidence_pool,
            verification_results
        )
        
        # Identify uncertainty factors
        uncertainty_factors = self._identify_uncertainty_factors(
            hypotheses,
            evidence_pool,
            verification_results
        )
        
        # Generate summary
        summary = self._generate_summary(
            change_event,
            hypotheses,
            hypothesis_support,
            overall_confidence
        )
        
        return EventAssessment(
            event_id=change_event.event_id,
            change_event=change_event,
            hypotheses=hypotheses,
            evidence_pool=evidence_pool,
            verification_results=verification_results,
            hypothesis_support=hypothesis_support,
            overall_confidence=overall_confidence,
            uncertainty_factors=uncertainty_factors,
            summary=summary,
            assessment_timestamp=datetime.utcnow().isoformat()
        )
    
    def _compute_hypothesis_support(
        self,
        hypotheses: List[Hypothesis],
        evidence_pool: List[Evidence],
        verification_map: Dict[str, VerificationResult]
    ) -> Dict[str, HypothesisSupport]:
        """
        Compute evidence support for each hypothesis.
        """
        support_map = {}
        
        for hypothesis in hypotheses:
            # Filter evidence for this hypothesis
            hypothesis_evidence = [
                e for e in evidence_pool 
                if e.hypothesis_type == hypothesis.hypothesis_type
            ]
            
            if not hypothesis_evidence:
                support_map[hypothesis.hypothesis_type.value] = HypothesisSupport(
                    hypothesis=hypothesis,
                    evidence_count=0,
                    avg_quality_score=0.0,
                    causal_evidence_count=0,
                    support_level="INSUFFICIENT"
                )
                continue
            
            # Compute metrics
            quality_scores = [
                verification_map[e.evidence_id].quality_score
                for e in hypothesis_evidence
                if e.evidence_id in verification_map
            ]
            
            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
            
            causal_count = sum(
                1 for e in hypothesis_evidence
                if e.evidence_id in verification_map and
                   verification_map[e.evidence_id].claim_type == ClaimType.CAUSAL
            )
            
            # Determine support level
            if len(hypothesis_evidence) >= 3 and avg_quality >= 0.6 and causal_count >= 1:
                support_level = "STRONG"
            elif len(hypothesis_evidence) >= 2 and avg_quality >= 0.4:
                support_level = "MODERATE"
            elif len(hypothesis_evidence) >= 1:
                support_level = "WEAK"
            else:
                support_level = "INSUFFICIENT"
            
            support_map[hypothesis.hypothesis_type.value] = HypothesisSupport(
                hypothesis=hypothesis,
                evidence_count=len(hypothesis_evidence),
                avg_quality_score=avg_quality,
                causal_evidence_count=causal_count,
                support_level=support_level
            )
        
        return support_map
    
    def _compute_overall_confidence(
        self,
        hypotheses: List[Hypothesis],
        evidence_pool: List[Evidence],
        verification_results: List[VerificationResult]
    ) -> float:
        """
        Compute overall assessment confidence [0.0, 1.0].
        
        Factors:
        - Evidence count (more is better)
        - Evidence quality (higher is better)
        - Hypothesis diversity (fewer competing hypotheses is better)
        - Contradictions (more contradictions lowers confidence)
        """
        if not evidence_pool:
            return 0.1
        
        # Evidence count factor
        evidence_factor = min(len(evidence_pool) / 10.0, 1.0)
        
        # Evidence quality factor
        quality_scores = [vr.quality_score for vr in verification_results]
        quality_factor = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        
        # Hypothesis diversity factor (penalize multiple strong hypotheses)
        strong_hypotheses = sum(
            1 for h in hypotheses 
            if h.confidence >= 0.6
        )
        diversity_penalty = 1.0 / max(strong_hypotheses, 1)
        
        # Contradiction factor
        contradiction_count = sum(
            len(vr.contradictions) for vr in verification_results
        )
        contradiction_penalty = max(0.5, 1.0 - (contradiction_count * 0.1))
        
        # Weighted combination
        confidence = (
            0.3 * evidence_factor +
            0.4 * quality_factor +
            0.2 * diversity_penalty +
            0.1 * contradiction_penalty
        )
        
        return min(confidence, 0.95)  # Cap at 0.95 (never 100% certain)
    
    def _identify_uncertainty_factors(
        self,
        hypotheses: List[Hypothesis],
        evidence_pool: List[Evidence],
        verification_results: List[VerificationResult]
    ) -> List[str]:
        """
        Identify sources of uncertainty in assessment.
        """
        factors = []
        
        # Low evidence count
        if len(evidence_pool) < 3:
            factors.append(f"Low evidence count ({len(evidence_pool)} pieces)")
        
        # Multiple competing hypotheses
        strong_hypotheses = [h for h in hypotheses if h.confidence >= 0.6]
        if len(strong_hypotheses) > 1:
            factors.append(f"Multiple competing hypotheses ({len(strong_hypotheses)})")
        
        # Contradictory evidence
        contradiction_count = sum(len(vr.contradictions) for vr in verification_results)
        if contradiction_count > 0:
            factors.append(f"Contradictory evidence detected ({contradiction_count} contradictions)")
        
        # Correlational-only evidence
        causal_count = sum(
            1 for vr in verification_results 
            if vr.claim_type == ClaimType.CAUSAL
        )
        if causal_count == 0 and evidence_pool:
            factors.append("No causal evidence found (correlational only)")
        
        # Low quality evidence
        avg_quality = sum(vr.quality_score for vr in verification_results) / len(verification_results) if verification_results else 0.0
        if avg_quality < 0.5:
            factors.append(f"Low average evidence quality ({avg_quality:.2f})")
        
        return factors
    
    def _generate_summary(
        self,
        change_event: ChangeEvent,
        hypotheses: List[Hypothesis],
        hypothesis_support: Dict[str, HypothesisSupport],
        overall_confidence: float
    ) -> str:
        """
        Generate human-readable assessment summary.
        """
        lines = []
        
        # Event description
        direction = change_event.change_direction
        pct_change = abs(change_event.percentage_change) if change_event.percentage_change else 0
        lines.append(
            f"Price {direction} of {pct_change:.1f}% for {change_event.product_name} "
            f"at {change_event.merchant} on {change_event.observed_at[:10]}"
        )
        
        # Hypothesis summary
        strong_support = [
            (k, v) for k, v in hypothesis_support.items()
            if v.support_level == "STRONG"
        ]
        
        if strong_support:
            lines.append("\nStrong evidence supports:")
            for hyp_type, support in strong_support:
                lines.append(
                    f"  - {hyp_type}: {support.evidence_count} pieces of evidence "
                    f"(quality: {support.avg_quality_score:.2f})"
                )
        else:
            lines.append("\nNo hypothesis has strong evidence support.")
            
            moderate_support = [
                (k, v) for k, v in hypothesis_support.items()
                if v.support_level == "MODERATE"
            ]
            
            if moderate_support:
                lines.append("Moderate evidence supports:")
                for hyp_type, support in moderate_support:
                    lines.append(f"  - {hyp_type}")
        
        # Confidence statement
        if overall_confidence >= 0.7:
            lines.append(f"\nHigh confidence assessment (confidence: {overall_confidence:.2f})")
        elif overall_confidence >= 0.4:
            lines.append(f"\nModerate confidence assessment (confidence: {overall_confidence:.2f})")
        else:
            lines.append(f"\nLow confidence assessment (confidence: {overall_confidence:.2f})")
        
        return '\n'.join(lines)
```

## Data Models

### Core Data Models

All data models support JSON serialization/deserialization and validation.

**PriceObservation** (subset of ChangeEvent):

```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class PriceObservation:
    """Minimal price observation for context."""
    product_id: str
    merchant: str
    price: float
    observed_at: str  # ISO-8601
    change_direction: str  # "increase" | "decrease" | "no_change" | "unknown"
    percentage_change: Optional[float] = None
```

**Hypothesis**:

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import List

class HypothesisType(Enum):
    PROMOTION = "promotion"
    COMPETITOR_RESPONSE = "competitor_response"
    INVENTORY_LIQUIDATION = "inventory_liquidation"
    PRODUCT_EVENT = "product_event"
    SEASONAL_EVENT = "seasonal_event"
    MARKET_EVENT = "market_event"
    MANUFACTURER_CHANGE = "manufacturer_change"
    DATA_ISSUE = "data_issue"

@dataclass
class Hypothesis:
    hypothesis_id: str  # Unique identifier
    hypothesis_type: HypothesisType
    signal_score: float  # [0.0, 1.0] - NOT "confidence" to avoid implying calibrated probability
    rationale: str  # Human-readable explanation
    requires_external_evidence: bool  # True for hypotheses like INVENTORY_LIQUIDATION
    assigned_agents: List[str] = field(default_factory=list)  # Agent names
    signals_matched: List[str] = field(default_factory=list)  # Signal names from ChangeEvent
    
    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_type": self.hypothesis_type.value,
            "signal_score": self.signal_score,
            "rationale": self.rationale,
            "requires_external_evidence": self.requires_external_evidence,
            "assigned_agents": self.assigned_agents,
            "signals_matched": self.signals_matched,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Hypothesis':
        return cls(
            hypothesis_id=data["hypothesis_id"],
            hypothesis_type=HypothesisType(data["hypothesis_type"]),
            signal_score=data["signal_score"],
            rationale=data["rationale"],
            requires_external_evidence=data.get("requires_external_evidence", False),
            assigned_agents=data.get("assigned_agents", []),
            signals_matched=data.get("signals_matched", []),
        )
```

**SearchQuery** (STRUCTURED OBJECT with complete context):

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List

class QueryStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class ProductContext:
    """Product context for query generation."""
    product_name: str
    product_brand: str
    product_category: str
    product_model: Optional[str] = None

@dataclass
class DateWindow:
    """Time range relevant to the event."""
    start_date: str  # ISO-8601 date
    end_date: str  # ISO-8601 date

@dataclass
class ProductIdentifiers:
    """Product identifiers for precise targeting."""
    ASIN: Optional[str] = None
    UPC: Optional[str] = None
    EAN: Optional[str] = None
    SKU: Optional[str] = None

@dataclass
class ExecutionMetadata:
    """Metadata filled during query execution."""
    execution_status: str = "pending"  # "pending" | "completed" | "failed"
    executed_at: Optional[str] = None  # ISO-8601 timestamp
    search_provider_used: Optional[str] = None  # "mock" | "serpapi" | "google" | "tavily"
    result_count: Optional[int] = None
    error_message: Optional[str] = None

@dataclass
class SearchQuery:
    """
    Structured search query with complete context and provenance.
    
    ALL fields are required for traceability and provenance tracking.
    """
    # Core fields
    event_id: str
    hypothesis: HypothesisType
    query_text: str
    purpose: str  # Human-readable purpose of this query
    priority: int  # 1=high, 2=medium, 3=low
    generated_by: str  # Agent name that generated this query
    
    # Product context
    product_context: ProductContext
    merchant: str
    date_window: DateWindow
    
    # Product identifiers (optional but valuable)
    identifiers: ProductIdentifiers
    
    # Provenance
    query_id: str  # Unique ID for tracing: Evidence.query_id links back to this
    
    # Execution metadata (filled during execution)
    execution_metadata: ExecutionMetadata
    
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "hypothesis": self.hypothesis.value,
            "query_text": self.query_text,
            "purpose": self.purpose,
            "priority": self.priority,
            "generated_by": self.generated_by,
            "product_context": {
                "product_name": self.product_context.product_name,
                "product_brand": self.product_context.product_brand,
                "product_category": self.product_context.product_category,
                "product_model": self.product_context.product_model,
            },
            "merchant": self.merchant,
            "date_window": {
                "start_date": self.date_window.start_date,
                "end_date": self.date_window.end_date,
            },
            "identifiers": {
                "ASIN": self.identifiers.ASIN,
                "UPC": self.identifiers.UPC,
                "EAN": self.identifiers.EAN,
                "SKU": self.identifiers.SKU,
            },
            "query_id": self.query_id,
            "execution_metadata": {
                "execution_status": self.execution_metadata.execution_status,
                "executed_at": self.execution_metadata.executed_at,
                "search_provider_used": self.execution_metadata.search_provider_used,
                "result_count": self.execution_metadata.result_count,
                "error_message": self.execution_metadata.error_message,
            }
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SearchQuery':
        return cls(
            event_id=data["event_id"],
            hypothesis=HypothesisType(data["hypothesis"]),
            query_text=data["query_text"],
            purpose=data["purpose"],
            priority=data["priority"],
            generated_by=data["generated_by"],
            product_context=ProductContext(**data["product_context"]),
            merchant=data["merchant"],
            date_window=DateWindow(**data["date_window"]),
            identifiers=ProductIdentifiers(**data["identifiers"]),
            query_id=data["query_id"],
            execution_metadata=ExecutionMetadata(**data["execution_metadata"]),
        )
```

**SearchResult**:

```python
@dataclass
class SearchResult:
    """Result from web search provider."""
    url: str
    title: str
    snippet: str
    source_domain: str  # Extracted from URL
    full_content: Optional[str] = None  # Full HTML if retrieved
    retrieved_at: str = ""  # ISO-8601 timestamp
    search_provider: str = "mock"  # "mock" | "serpapi" | "google" | "tavily"
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source_domain": self.source_domain,
            "full_content": self.full_content,
            "retrieved_at": self.retrieved_at,
            "search_provider": self.search_provider,
        }
```

**Evidence** (COMPLETE PROVENANCE):

```python
from enum import Enum

class EvidenceType(Enum):
    DIRECT = "direct"  # Mentions specific product/merchant
    INDIRECT = "indirect"  # Category/market level
    CAUSAL = "causal"  # Contains causal language
    CORRELATIONAL = "correlational"  # Temporal alignment only

@dataclass
class Evidence:
    """
    Evidence extracted from search results with COMPLETE provenance chain.
    
    ALL provenance fields are required for traceability.
    """
    # Identity
    evidence_id: str  # Unique identifier for this evidence
    
    # Provenance chain
    event_id: str  # Links to ChangeEvent
    hypothesis: HypothesisType  # Hypothesis this evidence supports
    query_id: str  # Links to SearchQuery that found this evidence
    
    # Source metadata (COMPLETE)
    source_url: str
    source_domain: str
    source_title: str
    publication_date: Optional[str]  # ISO-8601 date, if available
    retrieved_at: str  # ISO-8601 timestamp when evidence was retrieved
    
    # Content
    claim: str  # Short summary of the claim/finding
    evidence_text: str  # Full passage text
    
    # Classification
    evidence_type: EvidenceType
    relevance_score: float  # [0.0, 1.0]
    
    # Investigator
    investigator: str  # Agent name that extracted this evidence
    
    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "event_id": self.event_id,
            "hypothesis": self.hypothesis.value,
            "query_id": self.query_id,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "source_title": self.source_title,
            "publication_date": self.publication_date,
            "retrieved_at": self.retrieved_at,
            "claim": self.claim,
            "evidence_text": self.evidence_text,
            "evidence_type": self.evidence_type.value,
            "relevance_score": self.relevance_score,
            "investigator": self.investigator,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Evidence':
        return cls(
            evidence_id=data["evidence_id"],
            event_id=data["event_id"],
            hypothesis=HypothesisType(data["hypothesis"]),
            query_id=data["query_id"],
            source_url=data["source_url"],
            source_domain=data["source_domain"],
            source_title=data["source_title"],
            publication_date=data.get("publication_date"),
            retrieved_at=data["retrieved_at"],
            claim=data["claim"],
            evidence_text=data["evidence_text"],
            evidence_type=EvidenceType(data["evidence_type"]),
            relevance_score=data["relevance_score"],
            investigator=data["investigator"],
        )
```

**EventAssessment** (MULTIPLE HYPOTHESES SUPPORT):

```python
@dataclass
class EventAssessment:
    """
    Final assessment for a ChangeEvent.
    
    CRITICAL: Multiple hypotheses can be SUPPORTED simultaneously.
    NO "winner selection" logic.
    """
    event_id: str
    change_event: ChangeEvent  # Full ChangeEvent from Phase 1
    hypotheses: List[Hypothesis]
    evidence_pool: List[Evidence]
    verification_output: VerificationOutput  # From Verification Agent
    
    # Per-hypothesis support levels (from Verification Agent)
    hypothesis_support: Dict[str, HypothesisSupportAssessment]
    
    # Overall metrics
    overall_confidence: float  # [0.0, 1.0]
    uncertainty_factors: List[str]  # Explanations of uncertainty
    
    # Source independence metrics
    independent_source_count: int
    duplicated_source_count: int
    
    # Metadata
    assessment_timestamp: str  # ISO-8601
    
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "change_event": self.change_event.to_dict() if hasattr(self.change_event, 'to_dict') else self.change_event,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence_pool": [e.to_dict() for e in self.evidence_pool],
            "verification_output": {
                "evidence_verifications": [
                    vars(ev) for ev in self.verification_output.evidence_verifications
                ],
                "hypothesis_assessments": {
                    k: vars(v) for k, v in self.verification_output.hypothesis_assessments.items()
                },
                "source_independence_result": {
                    "independent_count": self.verification_output.source_independence_result.independent_source_count,
                    "duplicated_count": self.verification_output.source_independence_result.duplicated_source_count,
                }
            },
            "hypothesis_support": {
                k: vars(v) for k, v in self.hypothesis_support.items()
            },
            "overall_confidence": self.overall_confidence,
            "uncertainty_factors": self.uncertainty_factors,
            "independent_source_count": self.independent_source_count,
            "duplicated_source_count": self.duplicated_source_count,
            "assessment_timestamp": self.assessment_timestamp,
        }
```
            "executed_at": self.executed_at,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SearchQuery':
        return cls(
            query_id=data["query_id"],
            query_text=data["query_text"],
            agent_type=data["agent_type"],
            hypothesis_type=HypothesisType(data["hypothesis_type"]),
            execution_status=QueryStatus(data.get("execution_status", "pending")),
            executed_at=data.get("executed_at"),
            error_message=data.get("error_message"),
        )
```

**SearchResult**:

```python
@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    full_content: Optional[str] = None
    retrieved_at: str = ""  # ISO-8601
    search_provider: str = "unknown"
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "full_content": self.full_content,
            "retrieved_at": self.retrieved_at,
            "search_provider": self.search_provider,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SearchResult':
        return cls(
            url=data["url"],
            title=data["title"],
            snippet=data["snippet"],
            full_content=data.get("full_content"),
            retrieved_at=data.get("retrieved_at", ""),
            search_provider=data.get("search_provider", "unknown"),
        )
```

**Evidence**:

```python
@dataclass
class Evidence:
    evidence_id: str
    passage_text: str
    source_url: str
    relevance_score: float  # [0.0, 1.0]
    hypothesis_type: HypothesisType
    retrieved_at: str  # ISO-8601
    extraction_method: str = "keyword_semantic"
    
    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "passage_text": self.passage_text,
            "source_url": self.source_url,
            "relevance_score": self.relevance_score,
            "hypothesis_type": self.hypothesis_type.value,
            "retrieved_at": self.retrieved_at,
            "extraction_method": self.extraction_method,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Evidence':
        return cls(
            evidence_id=data["evidence_id"],
            passage_text=data["passage_text"],
            source_url=data["source_url"],
            relevance_score=data["relevance_score"],
            hypothesis_type=HypothesisType(data["hypothesis_type"]),
            retrieved_at=data["retrieved_at"],
            extraction_method=data.get("extraction_method", "keyword_semantic"),
        )
```

**VerificationResult**:

```python
class ClaimType(Enum):
    CAUSAL = "causal"
    CORRELATIONAL = "correlational"
    INSUFFICIENT = "insufficient"

@dataclass
class VerificationResult:
    evidence_id: str
    quality_score: float  # [0.0, 1.0]
    claim_type: ClaimType
    contradictions: List[str] = field(default_factory=list)  # Evidence IDs
    verification_notes: str = ""
    
    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "quality_score": self.quality_score,
            "claim_type": self.claim_type.value,
            "contradictions": self.contradictions,
            "verification_notes": self.verification_notes,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'VerificationResult':
        return cls(
            evidence_id=data["evidence_id"],
            quality_score=data["quality_score"],
            claim_type=ClaimType(data["claim_type"]),
            contradictions=data.get("contradictions", []),
            verification_notes=data.get("verification_notes", ""),
        )
```

**HypothesisSupport**:

```python
@dataclass
class HypothesisSupport:
    """Evidence support summary for a hypothesis."""
    hypothesis: Hypothesis
    evidence_count: int
    avg_quality_score: float
    causal_evidence_count: int
    support_level: str  # "STRONG" | "MODERATE" | "WEAK" | "INSUFFICIENT"
    
    def to_dict(self) -> dict:
        return {
            "hypothesis": self.hypothesis.to_dict(),
            "evidence_count": self.evidence_count,
            "avg_quality_score": self.avg_quality_score,
            "causal_evidence_count": self.causal_evidence_count,
            "support_level": self.support_level,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'HypothesisSupport':
        return cls(
            hypothesis=Hypothesis.from_dict(data["hypothesis"]),
            evidence_count=data["evidence_count"],
            avg_quality_score=data["avg_quality_score"],
            causal_evidence_count=data["causal_evidence_count"],
            support_level=data["support_level"],
        )
```

**EventAssessment** (Final Output):

```python
@dataclass
class EventAssessment:
    """Complete investigation assessment for a change event."""
    event_id: str
    change_event: ChangeEvent  # Full Phase 1 event
    hypotheses: List[Hypothesis]
    evidence_pool: List[Evidence]
    verification_results: List[VerificationResult]
    hypothesis_support: Dict[str, HypothesisSupport]
    overall_confidence: float  # [0.0, 1.0]
    uncertainty_factors: List[str]
    summary: str
    assessment_timestamp: str  # ISO-8601
    
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "change_event": self.change_event.to_dict(),
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence_pool": [e.to_dict() for e in self.evidence_pool],
            "verification_results": [vr.to_dict() for vr in self.verification_results],
            "hypothesis_support": {
                k: v.to_dict() for k, v in self.hypothesis_support.items()
            },
            "overall_confidence": self.overall_confidence,
            "uncertainty_factors": self.uncertainty_factors,
            "summary": self.summary,
            "assessment_timestamp": self.assessment_timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'EventAssessment':
        return cls(
            event_id=data["event_id"],
            change_event=ChangeEvent(**data["change_event"]),
            hypotheses=[Hypothesis.from_dict(h) for h in data["hypotheses"]],
            evidence_pool=[Evidence.from_dict(e) for e in data["evidence_pool"]],
            verification_results=[
                VerificationResult.from_dict(vr) 
                for vr in data["verification_results"]
            ],
            hypothesis_support={
                k: HypothesisSupport.from_dict(v)
                for k, v in data["hypothesis_support"].items()
            },
            overall_confidence=data["overall_confidence"],
            uncertainty_factors=data["uncertainty_factors"],
            summary=data["summary"],
            assessment_timestamp=data["assessment_timestamp"],
        )
```

**ParsedContent**:

```python
@dataclass
class ParsedContent:
    """Result of HTML/text parsing."""
    extracted_text: str
    parse_success: bool
    error_messages: List[str] = field(default_factory=list)
    truncated: bool = False
    
    def to_dict(self) -> dict:
        return {
            "extracted_text": self.extracted_text,
            "parse_success": self.parse_success,
            "error_messages": self.error_messages,
            "truncated": self.truncated,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ParsedContent':
        return cls(
            extracted_text=data["extracted_text"],
            parse_success=data["parse_success"],
            error_messages=data.get("error_messages", []),
            truncated=data.get("truncated", False),
        )
```

## Repository Interface and Data Access Layer

**Purpose**: Provide clean abstraction for data storage to avoid tight coupling to specific formats.

**CRITICAL REQUIREMENTS:**
- NO PostgreSQL yet, NO vector database
- Support JSON and CSV implementations
- Allow switching storage without changing investigation logic

**Repository_Interface**:

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class RepositoryInterface(ABC):
    """
    Abstract interface for data access operations.
    
    Implementations: JSON_Repository, CSV_Repository
    Future: PostgreSQL_Repository (not in this phase)
    """
    
    @abstractmethod
    def save_event_assessment(self, assessment: EventAssessment) -> None:
        """Save complete EventAssessment."""
        pass
    
    @abstractmethod
    def load_event_assessment(self, event_id: str) -> Optional[EventAssessment]:
        """Load EventAssessment by event_id."""
        pass
    
    @abstractmethod
    def list_assessments(self) -> List[str]:
        """List all event_ids with saved assessments."""
        pass
    
    @abstractmethod
    def save_evidence(self, evidence: Evidence) -> None:
        """Save individual Evidence object."""
        pass
    
    @abstractmethod
    def load_evidence_by_event(self, event_id: str) -> List[Evidence]:
        """Load all Evidence for a given event_id."""
        pass
```

**JSON_Repository Implementation**:

```python
import json
import os
from pathlib import Path
from typing import List, Optional

class JSONRepository(RepositoryInterface):
    """
    JSON-based storage implementation.
    
    Storage structure:
    - data/assessments/{event_id}_assessment.json
    - data/evidence/{event_id}_evidence.json
    """
    
    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.assessments_dir = self.base_dir / "assessments"
        self.evidence_dir = self.base_dir / "evidence"
        
        # Create directories if they don't exist
        self.assessments_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
    
    def save_event_assessment(self, assessment: EventAssessment) -> None:
        """Save EventAssessment to JSON file."""
        filepath = self.assessments_dir / f"{assessment.event_id}_assessment.json"
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(assessment.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"Saved assessment to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save assessment {assessment.event_id}: {e}")
            raise
    
    def load_event_assessment(self, event_id: str) -> Optional[EventAssessment]:
        """Load EventAssessment from JSON file."""
        filepath = self.assessments_dir / f"{event_id}_assessment.json"
        
        if not filepath.exists():
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return EventAssessment.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load assessment {event_id}: {e}")
            return None
    
    def list_assessments(self) -> List[str]:
        """List all event_ids with saved assessments."""
        assessment_files = self.assessments_dir.glob("*_assessment.json")
        return [f.stem.replace("_assessment", "") for f in assessment_files]
    
    def save_evidence(self, evidence: Evidence) -> None:
        """Save Evidence to JSON file (appends to event's evidence file)."""
        filepath = self.evidence_dir / f"{evidence.event_id}_evidence.json"
        
        # Load existing evidence
        existing_evidence = []
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    existing_evidence = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load existing evidence: {e}")
        
        # Append new evidence
        existing_evidence.append(evidence.to_dict())
        
        # Save back
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(existing_evidence, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save evidence: {e}")
            raise
    
    def load_evidence_by_event(self, event_id: str) -> List[Evidence]:
        """Load all Evidence for a given event_id."""
        filepath = self.evidence_dir / f"{event_id}_evidence.json"
        
        if not filepath.exists():
            return []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return [Evidence.from_dict(ev) for ev in data]
        except Exception as e:
            logger.error(f"Failed to load evidence for {event_id}: {e}")
            return []
```

**CSV_Repository Implementation**:

```python
import csv
from pathlib import Path
from typing import List, Optional

class CSVRepository(RepositoryInterface):
    """
    CSV-based storage for tabular exports.
    
    Useful for:
    - Exporting assessment summaries
    - Analysis in Excel/pandas
    - Batch reporting
    """
    
    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.assessments_file = self.base_dir / "assessments_summary.csv"
        self.evidence_file = self.base_dir / "evidence_export.csv"
    
    def save_event_assessment(self, assessment: EventAssessment) -> None:
        """Append assessment summary to CSV."""
        # Simplified summary row
        row = {
            "event_id": assessment.event_id,
            "product_name": assessment.change_event.product_name,
            "merchant": assessment.change_event.merchant,
            "percentage_change": assessment.change_event.percentage_change,
            "num_hypotheses": len(assessment.hypotheses),
            "num_evidence": len(assessment.evidence_pool),
            "overall_confidence": assessment.overall_confidence,
            "independent_sources": assessment.independent_source_count,
            "duplicated_sources": assessment.duplicated_source_count,
            "assessment_timestamp": assessment.assessment_timestamp,
        }
        
        # Append to CSV
        file_exists = self.assessments_file.exists()
        with open(self.assessments_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    
    def load_event_assessment(self, event_id: str) -> Optional[EventAssessment]:
        """Not implemented for CSV (use JSON for full object loading)."""
        raise NotImplementedError("Use JSONRepository for full object loading")
    
    def list_assessments(self) -> List[str]:
        """List event_ids from CSV."""
        if not self.assessments_file.exists():
            return []
        
        event_ids = []
        with open(self.assessments_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                event_ids.append(row["event_id"])
        return event_ids
    
    def save_evidence(self, evidence: Evidence) -> None:
        """Append evidence to CSV."""
        row = {
            "evidence_id": evidence.evidence_id,
            "event_id": evidence.event_id,
            "hypothesis": evidence.hypothesis.value,
            "source_url": evidence.source_url,
            "source_domain": evidence.source_domain,
            "relevance_score": evidence.relevance_score,
            "evidence_type": evidence.evidence_type.value,
            "investigator": evidence.investigator,
        }
        
        file_exists = self.evidence_file.exists()
        with open(self.evidence_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    
    def load_evidence_by_event(self, event_id: str) -> List[Evidence]:
        """Not implemented for CSV (use JSON for full object loading)."""
        raise NotImplementedError("Use JSONRepository for full object loading")
```

## Historical Investigation Entry Point

**Purpose**: Enable investigation of historical events from Phase 1 via command-line script.

**Script**: `scripts/investigate_event.py`

**Usage**:
```bash
# With MockSearchProvider (no API keys needed, for testing)
python scripts/investigate_event.py --event-id E001

# With real SearchProvider (requires API keys)
export SEARCH_PROVIDER=serpapi
export SERPAPI_API_KEY=your_key_here
python scripts/investigate_event.py --event-id E001

# With Google Custom Search
export SEARCH_PROVIDER=google
export GOOGLE_API_KEY=your_key
export GOOGLE_SEARCH_ENGINE_ID=your_engine_id
python scripts/investigate_event.py --event-id E001
```

**Implementation**:

```python
#!/usr/bin/env python3
"""
Historical Event Investigation Script

Investigates a single ChangeEvent from Phase 1 using the complete
Phase 2 investigation pipeline.

Works with:
- MockSearchProvider (default, no API keys)
- Real SearchProvider (SerpAPI, Google, Tavily with API keys)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.events.event_generator import load_change_events
from src.investigation.orchestrator import InvestigationOrchestrator
from src.investigation.hypothesis_generator import HypothesisGenerator
from src.search.provider_factory import create_search_provider
from src.investigation.repository import JSONRepository
from src.config.investigation_config import InvestigationConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Investigate a historical price change event"
    )
    parser.add_argument(
        "--event-id",
        required=True,
        help="Event ID to investigate (e.g., E001)"
    )
    parser.add_argument(
        "--search-provider",
        default=os.environ.get("SEARCH_PROVIDER", "mock"),
        choices=["mock", "serpapi", "google", "tavily"],
        help="Search provider to use (default: mock)"
    )
    parser.add_argument(
        "--output-dir",
        default="data/assessments",
        help="Output directory for assessment results"
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    
    logger.info("=" * 60)
    logger.info("SignalWatch Phase 2 - Historical Event Investigation")
    logger.info("=" * 60)
    logger.info(f"Event ID: {args.event_id}")
    logger.info(f"Search Provider: {args.search_provider}")
    logger.info(f"Output Directory: {args.output_dir}")
    logger.info("")
    
    # Step 1: Load ChangeEvent from Phase 1
    logger.info("[Step 1/6] Loading ChangeEvent from Phase 1 data...")
    change_events = load_change_events("data/events/change_events.json")
    change_event = next((e for e in change_events if e.event_id == args.event_id), None)
    
    if not change_event:
        logger.error(f"Event {args.event_id} not found in Phase 1 data")
        sys.exit(1)
    
    logger.info(f"  Loaded: {change_event.product_name} at {change_event.merchant}")
    logger.info(f"  Price change: {change_event.percentage_change:.1f}%")
    logger.info("")
    
    # Step 2: Initialize components
    logger.info("[Step 2/6] Initializing investigation components...")
    config = InvestigationConfig()
    search_provider = create_search_provider(args.search_provider)
    repository = JSONRepository(base_dir=args.output_dir)
    orchestrator = InvestigationOrchestrator(search_provider, config)
    logger.info(f"  Search provider: {search_provider.get_provider_name()}")
    logger.info("")
    
    # Step 3: Generate hypotheses
    logger.info("[Step 3/6] Generating hypotheses...")
    hypothesis_generator = HypothesisGenerator(config.hypothesis_config)
    hypotheses = hypothesis_generator.generate(change_event)
    logger.info(f"  Generated {len(hypotheses)} hypotheses:")
    for h in hypotheses:
        logger.info(f"    - {h.hypothesis_type.value} (signal_score: {h.signal_score:.2f})")
    logger.info("")
    
    # Step 4: Execute investigation
    logger.info("[Step 4/6] Executing investigation agents...")
    assessment = await orchestrator.investigate_event(change_event)
    logger.info(f"  Collected {len(assessment.evidence_pool)} pieces of evidence")
    logger.info(f"  Independent sources: {assessment.independent_source_count}")
    logger.info(f"  Duplicated sources: {assessment.duplicated_source_count}")
    logger.info("")
    
    # Step 5: Display verification results
    logger.info("[Step 5/6] Verification results:")
    for hyp_type, support_assessment in assessment.hypothesis_support.items():
        logger.info(f"  {hyp_type}:")
        logger.info(f"    Support level: {support_assessment.support_level.value}")
        logger.info(f"    {support_assessment.explanation}")
    logger.info(f"\n  Overall confidence: {assessment.overall_confidence:.2f}")
    if assessment.uncertainty_factors:
        logger.info("  Uncertainty factors:")
        for factor in assessment.uncertainty_factors:
            logger.info(f"    - {factor}")
    logger.info("")
    
    # Step 6: Save results
    logger.info("[Step 6/6] Saving assessment...")
    repository.save_event_assessment(assessment)
    output_file = Path(args.output_dir) / f"{args.event_id}_assessment.json"
    logger.info(f"  Saved to: {output_file}")
    logger.info("")
    
    logger.info("=" * 60)
    logger.info("Investigation complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

**Key Features**:

1. **Loads historical ChangeEvents** from Phase 1 `data/events/change_events.json`
2. **Works with MockSearchProvider** (no API keys) for testing
3. **Works with real SearchProviders** (SerpAPI, Google, Tavily) when API keys configured
4. **Runs complete pipeline**: Hypothesis → Investigation → Search → Extraction → Verification
5. **Outputs EventAssessment** with evidence-backed conclusions
6. **Progress logging** shows each pipeline stage completion
7. **Clean error handling** with descriptive messages

## Error Handling

### Error Handling Strategy

**Principle**: Fail gracefully, preserve partial results, continue investigation.

**Error Categories**:

1. **Search Provider Errors**
   - Retry up to `max_retries` (default: 3)
   - Exponential backoff: 2^attempt seconds
   - Log failure and continue with other queries
   - Mark query as FAILED with error message

2. **Evidence Extraction Errors**
   - Log parsing failures
   - Return empty evidence list for failed extraction
   - Continue with successfully extracted evidence

3. **Agent Execution Errors**
   - Catch and log all agent exceptions
   - Continue with other agents
   - Record agent failure in assessment metadata

4. **Verification Errors**
   - Log verification failures
   - Assign default low-quality scores to unverified evidence
   - Include "verification incomplete" in uncertainty factors

5. **Serialization Errors**
   - Validate all data models before serialization
   - Raise descriptive errors with field name and validation issue
   - Prevent writing corrupted JSON

**Error Logging**:

```python
import logging

logger = logging.getLogger("signalwatch.investigation")

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Example error handling in orchestrator
try:
    evidence = await agent.investigate(change_event, hypothesis)
except SearchProviderError as e:
    logger.error(
        f"Search provider failure for agent {agent.__class__.__name__}: {e}",
        extra={
            "event_id": change_event.event_id,
            "hypothesis_type": hypothesis.hypothesis_type.value,
            "agent": agent.__class__.__name__,
        }
    )
    evidence = []
except Exception as e:
    logger.exception(
        f"Unexpected error in agent {agent.__class__.__name__}",
        extra={
            "event_id": change_event.event_id,
            "hypothesis_type": hypothesis.hypothesis_type.value,
        }
    )
    evidence = []
```

## Testing Strategy

### Testing Approach

SignalWatch Phase 2 requires comprehensive testing without external dependencies. The testing strategy uses **mock-based unit tests** for all search-related functionality, **integration tests** (marked as optional) for real API validation, and **property-based tests** for serialization correctness.

### Unit Testing with Mocks

**Test Structure**:

```
tests/
├── test_investigation_hypothesis.py          # Hypothesis generation
├── test_investigation_agents.py              # Individual agents
├── test_investigation_search_providers.py    # Mock providers
├── test_investigation_evidence.py            # Evidence extraction
├── test_investigation_verification.py        # Verification agent
├── test_investigation_orchestrator.py        # Full workflow
├── test_investigation_models.py              # Data model serialization
├── test_investigation_parser.py              # HTML parsing
└── fixtures/
    ├── mock_change_events.json               # Sample events
    ├── mock_search_results.json              # Sample results
    └── mock_html_pages/                      # Sample HTML files
```

**Key Testing Principles**:

1. **No API Keys Required**: All tests use `MockSearchProvider`
2. **Fast Execution**: Complete test suite runs < 60 seconds
3. **Deterministic**: Same inputs produce same outputs
4. **Comprehensive Coverage**: Test all error paths and edge cases

**Example Unit Tests**:

```python
# test_investigation_hypothesis.py

import pytest
from src.investigation.hypothesis_generator import HypothesisGenerator
from src.events.event_generator import ChangeEvent

def test_promotion_hypothesis_generated_when_is_sale_true():
    """Test that PROMOTION hypothesis is generated when is_sale=True."""
    generator = HypothesisGenerator()
    
    event = ChangeEvent(
        event_id="test_evt_001",
        product_id="prod_123",
        product_name="Sony Headphones",
        brand="Sony",
        merchant="BestBuy",
        is_sale=True,
        percentage_change=-15.0,
        # ... other required fields
    )
    
    hypotheses = generator.generate(event)
    
    # Assert PROMOTION hypothesis is present
    promotion_hyps = [h for h in hypotheses if h.hypothesis_type == HypothesisType.PROMOTION]
    assert len(promotion_hyps) > 0
    assert promotion_hyps[0].confidence >= 0.6


def test_multiple_hypotheses_when_signals_weak():
    """Test that multiple hypotheses are generated when signals are weak."""
    generator = HypothesisGenerator()
    
    event = ChangeEvent(
        event_id="test_evt_002",
        product_id="prod_456",
        product_name="Generic Product",
        brand="Unknown",
        merchant="RandomStore",
        is_sale=False,
        percentage_change=-5.0,
        competitor_count=1,
        # ... weak signals
    )
    
    hypotheses = generator.generate(event)
    
    # Should generate at least 2 hypotheses with similar confidence
    assert len(hypotheses) >= 2
    confidences = [h.confidence for h in hypotheses]
    assert max(confidences) - min(confidences) < 0.2  # Similar confidence


# test_investigation_agents.py

import pytest
from src.investigation.agents.promotion_agent import Promotion_Agent
from src.search.mock_provider import MockSearchProvider

@pytest.fixture
def mock_search_provider():
    """Fixture providing configured mock search provider."""
    result_config = {
        "sale": [
            SearchResult(
                url="https://example.com/sale",
                title="Summer Sale - 50% Off",
                snippet="Major electronics sale...",
                retrieved_at="2024-01-15T10:00:00Z",
                search_provider="mock"
            )
        ]
    }
    return MockSearchProvider(result_config)


@pytest.mark.asyncio
async def test_promotion_agent_generates_sale_queries(mock_search_provider):
    """Test that Promotion_Agent generates appropriate sale-focused queries."""
    agent = Promotion_Agent(mock_search_provider, AgentConfig())
    
    event = ChangeEvent(
        product_name="Sony WH-1000XM4",
        brand="Sony",
        merchant="BestBuy",
        # ...
    )
    
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        hypothesis_type=HypothesisType.PROMOTION,
        confidence=0.7,
        rationale="is_sale=True signal"
    )
    
    queries = agent.generate_queries(event, hypothesis)
    
    # Assert queries contain expected keywords
    assert len(queries) > 0
    query_texts = [q.query_text.lower() for q in queries]
    assert any("sale" in qt for qt in query_texts)
    assert any("sony" in qt and "wh-1000xm4" in qt for qt in query_texts)


@pytest.mark.asyncio
async def test_promotion_agent_extracts_evidence(mock_search_provider):
    """Test that Promotion_Agent extracts relevant evidence from results."""
    agent = Promotion_Agent(mock_search_provider, AgentConfig())
    
    event = ChangeEvent(
        product_name="Sony WH-1000XM4",
        brand="Sony",
        merchant="BestBuy",
        # ...
    )
    
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        hypothesis_type=HypothesisType.PROMOTION,
        confidence=0.7,
        rationale="is_sale=True signal"
    )
    
    evidence = await agent.investigate(event, hypothesis)
    
    # Assert evidence was extracted
    assert len(evidence) > 0
    assert all(e.hypothesis_type == HypothesisType.PROMOTION for e in evidence)
    assert all(e.relevance_score > 0 for e in evidence)


# test_investigation_verification.py

def test_verification_classifies_causal_claims():
    """Test that causal language is detected."""
    verifier = VerificationAgent(VerificationConfig())
    
    evidence = Evidence(
        evidence_id="evd_001",
        passage_text="The price drop was caused by a major promotional event.",
        source_url="https://example.com/article",
        relevance_score=0.8,
        hypothesis_type=HypothesisType.PROMOTION,
        retrieved_at="2024-01-15T10:00:00Z"
    )
    
    claim_type = verifier._classify_claim(evidence)
    
    assert claim_type == ClaimType.CAUSAL


def test_verification_detects_contradictions():
    """Test that contradictory evidence is detected."""
    verifier = VerificationAgent(VerificationConfig())
    
    evidence_pool = [
        Evidence(
            evidence_id="evd_001",
            passage_text="Price increased by 20% due to supply shortage.",
            # ...
        ),
        Evidence(
            evidence_id="evd_002",
            passage_text="Price decreased by 15% during the sale event.",
            # ...
        ),
    ]
    
    contradictions = verifier._find_contradictions(evidence_pool[0], evidence_pool)
    
    assert "evd_002" in contradictions


# test_investigation_models.py (Property-Based Testing)

from hypothesis import given, strategies as st
import json

@given(st.floats(min_value=0.0, max_value=1.0))
def test_hypothesis_confidence_serialization_roundtrip(confidence):
    """Property: Hypothesis serialization round-trip preserves confidence."""
    hypothesis = Hypothesis(
        hypothesis_id="hyp_test",
        hypothesis_type=HypothesisType.PROMOTION,
        confidence=confidence,
        rationale="Test rationale"
    )
    
    # Serialize
    serialized = json.dumps(hypothesis.to_dict())
    
    # Deserialize
    deserialized = Hypothesis.from_dict(json.loads(serialized))
    
    # Assert round-trip preservation
    assert deserialized.confidence == pytest.approx(confidence)
    assert deserialized.hypothesis_type == hypothesis.hypothesis_type


def test_event_assessment_serialization_roundtrip():
    """Property: EventAssessment serialization round-trip preserves all fields."""
    # Create complete EventAssessment
    assessment = EventAssessment(
        event_id="evt_001",
        change_event=create_mock_change_event(),
        hypotheses=[create_mock_hypothesis()],
        evidence_pool=[create_mock_evidence()],
        verification_results=[create_mock_verification_result()],
        hypothesis_support={},
        overall_confidence=0.75,
        uncertainty_factors=["Low evidence count"],
        summary="Test summary",
        assessment_timestamp="2024-01-15T10:00:00Z"
    )
    
    # Serialize to JSON
    json_str = json.dumps(assessment.to_dict())
    
    # Deserialize
    deserialized = EventAssessment.from_dict(json.loads(json_str))
    
    # Assert all fields preserved
    assert deserialized.event_id == assessment.event_id
    assert deserialized.overall_confidence == assessment.overall_confidence
    assert len(deserialized.hypotheses) == len(assessment.hypotheses)
    assert len(deserialized.evidence_pool) == len(assessment.evidence_pool)
```

### Integration Tests (Optional, Require API Keys)

```python
# test_integration_real_search.py

import pytest
from src.search.serpapi_provider import SerpAPIProvider

@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("SERPAPI_KEY"), reason="Requires SERPAPI_KEY")
@pytest.mark.asyncio
async def test_serpapi_provider_real_search():
    """Integration test with real SerpAPI (requires API key)."""
    provider = SerpAPIProvider(api_key=os.getenv("SERPAPI_KEY"))
    
    results = await provider.search("Sony WH-1000XM4 sale", num_results=5)
    
    assert len(results) > 0
    assert all(r.url for r in results)
    assert all(r.title for r in results)
```

### Test Execution

```bash
# Run all unit tests (fast, no API keys)
pytest tests/ -v --ignore=tests/test_integration_*

# Run with coverage
pytest tests/ --cov=src/investigation --cov-report=html

# Run integration tests (requires API keys)
pytest tests/test_integration_*.py -v --markers=integration

# Run property-based tests only
pytest tests/ -k "property" -v
```

## Integration with Existing System

### Integration Strategy

**Non-Destructive Extension**:
- No modifications to Phase 1 source files (`src/data/`, `src/bocpd/`, `src/features/`, `src/events/`)
- No modifications to Phase 1 test files
- New modules in separate directories (`src/investigation/`, `src/search/`, `src/evidence/`, `src/models/`)
- New output directory (`data/assessments/`)

**Data Flow Integration**:

```python
# Integration script: scripts/run_investigation.py

import json
import asyncio
from pathlib import Path

from src.events.event_generator import load_events_json
from src.investigation.orchestrator import InvestigationOrchestrator
from src.search.mock_provider import MockSearchProvider
from src.config.investigation_config import InvestigationConfig

async def main():
    # Load Phase 1 outputs
    events_path = Path("data/events/change_events.json")
    change_events = load_events_json(events_path)
    
    print(f"Loaded {len(change_events)} change events from Phase 1")
    
    # Initialize Phase 2 system
    config = InvestigationConfig()
    search_provider = MockSearchProvider()  # Or real provider with API key
    orchestrator = InvestigationOrchestrator(search_provider, config)
    
    # Process each event
    assessments = []
    
    for event_dict in change_events:
        # Convert dict to ChangeEvent object
        event = ChangeEvent(**event_dict)
        
        print(f"Investigating event {event.event_id}...")
        
        # Run investigation
        assessment = await orchestrator.investigate_event(event)
        assessments.append(assessment)
    
    # Save results
    output_path = Path("data/assessments/event_assessments.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(
            [a.to_dict() for a in assessments],
            f,
            indent=2,
            default=str
        )
    
    print(f"Saved {len(assessments)} assessments to {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Backward Compatibility Verification**:

```bash
# Run Phase 1 tests to ensure no regression
pytest tests/test_bocpd_*.py tests/test_data_*.py tests/test_features_*.py tests/test_events_*.py -v

# Expected: All 112 tests pass
```

### Configuration Management

**Configuration Files**:

```python
# src/config/investigation_config.py

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class HypothesisConfig:
    """Configuration for hypothesis generation."""
    min_confidence: float = 0.3
    max_hypotheses: int = 8
    default_hypotheses_when_weak: int = 2

@dataclass
class AgentConfig:
    """Configuration for investigation agents."""
    results_per_query: int = 10
    min_relevance_score: float = 0.3
    max_queries_per_hypothesis: int = 5

@dataclass
class SearchConfig:
    """Configuration for search providers."""
    timeout_seconds: int = 30
    rate_limit_delay: float = 1.0  # seconds between requests

@dataclass
class VerificationConfig:
    """Configuration for verification agent."""
    min_quality_threshold: float = 0.4
    contradiction_threshold: float = 0.7

@dataclass
class InvestigationConfig:
    """Master configuration for investigation system."""
    max_retries: int = 3
    parallel_agent_limit: int = 6
    relevance_threshold: float = 0.3
    evidence_minimum: int = 1
    verification_threshold: float = 0.4
    
    hypothesis_config: HypothesisConfig = field(default_factory=HypothesisConfig)
    agent_config: AgentConfig = field(default_factory=AgentConfig)
    search_config: SearchConfig = field(default_factory=SearchConfig)
    verification_config: VerificationConfig = field(default_factory=VerificationConfig)
    
    @classmethod
    def from_json(cls, path: str) -> 'InvestigationConfig':
        """Load configuration from JSON file."""
        import json
        with open(path, 'r') as f:
            data = json.load(f)
        
        return cls(
            max_retries=data.get("max_retries", 3),
            parallel_agent_limit=data.get("parallel_agent_limit", 6),
            relevance_threshold=data.get("relevance_threshold", 0.3),
            evidence_minimum=data.get("evidence_minimum", 1),
            verification_threshold=data.get("verification_threshold", 0.4),
            hypothesis_config=HypothesisConfig(**data.get("hypothesis_config", {})),
            agent_config=AgentConfig(**data.get("agent_config", {})),
            search_config=SearchConfig(**data.get("search_config", {})),
            verification_config=VerificationConfig(**data.get("verification_config", {})),
        )
    
    @classmethod
    def from_env(cls) -> 'InvestigationConfig':
        """Load configuration from environment variables."""
        import os
        
        return cls(
            max_retries=int(os.getenv("INVESTIGATION_MAX_RETRIES", "3")),
            parallel_agent_limit=int(os.getenv("INVESTIGATION_PARALLEL_LIMIT", "6")),
            relevance_threshold=float(os.getenv("INVESTIGATION_RELEVANCE_THRESHOLD", "0.3")),
            # ... additional env vars
        )
```

**Example Configuration Files**:

```json
// config/testing.json
{
  "max_retries": 1,
  "parallel_agent_limit": 2,
  "relevance_threshold": 0.2,
  "hypothesis_config": {
    "min_confidence": 0.2,
    "max_hypotheses": 4
  },
  "agent_config": {
    "results_per_query": 5,
    "min_relevance_score": 0.2
  }
}

// config/production.json
{
  "max_retries": 3,
  "parallel_agent_limit": 6,
  "relevance_threshold": 0.3,
  "hypothesis_config": {
    "min_confidence": 0.3,
    "max_hypotheses": 8
  },
  "agent_config": {
    "results_per_query": 10,
    "min_relevance_score": 0.3
  },
  "search_config": {
    "timeout_seconds": 30,
    "rate_limit_delay": 1.0
  }
}
```

## Future Extensions

### Planned Enhancements

1. **Semantic Search**
   - Add embedding-based relevance scoring
   - Use sentence transformers for passage similarity
   - Improve evidence extraction quality

2. **Machine Learning Integration**
   - Train hypothesis confidence models on labeled data
   - Learn optimal agent selection strategies
   - Improve verification accuracy with supervised learning

3. **Channel3 Integration**
   - Replace MockSearchProvider with Channel3 MCP server
   - Leverage Channel3's specialized search capabilities
   - Access Channel3's retrieval and analysis features

4. **Advanced Verification**
   - Fact-checking against structured data sources
   - Cross-reference with historical price databases
   - Detect temporal inconsistencies

5. **Performance Optimization**
   - Cache search results to reduce API costs
   - Parallelize evidence extraction
   - Optimize hypothesis generation with pre-computed signals

### Extension Points

**Custom Investigation Agents**:

```python
# User-defined agent registration

from src.investigation.agents.base_agent import InvestigationAgent

class CustomDomainAgent(InvestigationAgent):
    """Custom agent for domain-specific investigations."""
    
    def can_investigate(self, hypothesis: Hypothesis) -> bool:
        return hypothesis.hypothesis_type == HypothesisType.CUSTOM_DOMAIN
    
    def generate_queries(self, change_event: ChangeEvent, hypothesis: Hypothesis) -> List[SearchQuery]:
        # Custom query generation logic
        pass
    
    def extract_evidence(self, search_result: SearchResult, hypothesis: Hypothesis) -> List[Evidence]:
        # Custom evidence extraction logic
        pass

# Register custom agent
orchestrator.register_agent("custom_domain", CustomDomainAgent)
```

**Custom Search Providers**:

```python
# User-defined search provider

from src.search.provider_interface import SearchProvider

class CustomSearchProvider(SearchProvider):
    """Custom search provider implementation."""
    
    async def search(self, query: str, num_results: int = 10) -> List[SearchResult]:
        # Custom search implementation
        pass
    
    async def get_page_content(self, url: str) -> Optional[str]:
        # Custom content retrieval
        pass
    
    def get_provider_name(self) -> str:
        return "custom_provider"

# Use custom provider
orchestrator = InvestigationOrchestrator(
    search_provider=CustomSearchProvider(),
    config=config
)
```

---

## Summary

SignalWatch Phase 2 delivers a comprehensive investigation layer that:

1. **Extends Phase 1** without modifying existing code (preserves 112 tests)
2. **Generates multiple hypotheses** from observable signals (8 hypothesis types)
3. **Executes specialized agents** with hypothesis-specific strategies (6 agents)
4. **Abstracts search providers** for testing and flexibility (mock + real providers)
5. **Extracts relevant evidence** with complete traceability (relevance scoring)
6. **Independently verifies** evidence quality and causal claims
7. **Quantifies uncertainty** across all dimensions
8. **Tests comprehensively** without external dependencies (mock-based, <60s)

The design prioritizes **testability**, **extensibility**, and **uncertainty preservation**, ensuring the system produces reliable assessments while acknowledging the inherent ambiguity in causal inference from web evidence.


## Summary of Critical Architecture Clarifications

This section summarizes all critical clarifications and updates to the Phase 2 Investigation Layer design:

### 1. Web Search Architecture (NOT RAG, NOT Channel3)

**CLARIFIED**:
- **Web Search**: Uses Google/SerpAPI/Tavily/etc. via `SearchProvider` interface
- **NOT Channel3**: Channel3 is a future pricing data source for Phase 1 ingestion, NOT used in Phase 2
- **NOT RAG**: No embeddings, no vector database, no semantic retrieval
- **Architecture**: Targeted queries → live web search → HTML parsing → evidence extraction → verification

### 2. Hypothesis Generation Updates

**CHANGED**:
- **Use `signal_score`** instead of `confidence` to avoid implying calibrated probability
- **Add `requires_external_evidence` flag**: `True` for INVENTORY_LIQUIDATION (availability field is NOT sufficient - need external confirmation)
- **Explicit signal mapping**: Show how ChangeEvent attributes map to hypothesis scores

### 3. Structured SearchQuery Objects

**EXPANDED**:
- **Complete context fields**: event_id, hypothesis, query_text, purpose, priority, generated_by
- **Product context**: product_name, brand, category, model
- **Merchant**: merchant identification
- **Date window**: time range relevant to event
- **Identifiers**: ASIN, UPC, EAN, SKU for precise targeting
- **Execution metadata**: execution_status, executed_at, search_provider_used, result_count
- **Provenance**: query_id links to Evidence.query_id for complete traceability

### 4. Evidence with Complete Provenance

**EXPANDED**:
- **ALL provenance fields required**:
  - evidence_id, event_id, hypothesis, query_id
  - source_url, source_domain, source_title, publication_date, retrieved_at
  - claim, evidence_text, evidence_type, relevance, investigator
- **Full chain**: ChangeEvent → Hypothesis → SearchQuery (query_id) → SearchResult → Evidence (evidence_id)

### 5. Source Independence Detection (NEW COMPONENT)

**ADDED**:
- **Purpose**: Distinguish INDEPENDENT vs DUPLICATED/SYNDICATED sources
- **Detection methods**:
  - Content similarity (character n-gram overlap)
  - Attribution analysis ("Originally published at", "Source:")
  - Domain clustering
  - Same author detection
- **Output**: source_independence_graph, classifications, independent_count, duplicated_count
- **Integration**: Feeds into Verification Agent confidence calculations

### 6. Verification Agent (Multi-Dimensional Assessment)

**ENHANCED**:
- **8 evaluation criteria** (not just quality scoring):
  1. Source-hypothesis alignment
  2. Product/merchant match
  3. Temporal alignment
  4. Specificity
  5. Direct vs inferred evidence
  6. Source independence
  7. Contradictions
  8. Causality vs correlation
- **5 support levels**: SUPPORTS, PARTIALLY_SUPPORTS, CONSISTENT_WITH, INSUFFICIENT_EVIDENCE, CONTRADICTS
- **Conservative language**: Don't claim "X caused Y" without genuine evidence
- **SUPPORTS requires**: ≥2 independent sources, ≥1 causal evidence, avg quality ≥0.6

### 7. Multiple Hypothesis Support

**CLARIFIED**:
- **Multiple hypotheses can be SUPPORTED simultaneously** for one ChangeEvent
- **NO "winner selection" logic** - don't force a single answer
- **Per-hypothesis support levels** with evidence IDs
- **Overall confidence** computed WITHOUT hypothesis diversity penalty
- Weight: source independence, specificity, causal strength (NOT hypothesis count)

### 8. Repository Interface Abstraction

**ADDED**:
- **Clean abstraction**: Repository_Interface for data access
- **Implementations**: JSON_Repository (objects), CSV_Repository (exports)
- **NO PostgreSQL yet**, NO vector database
- **Allow switching** storage without changing investigation logic
- **Operations**: save_event_assessment, load_event_assessment, list_assessments, save_evidence, load_evidence_by_event

### 9. Historical Investigation Entry Point

**ADDED**:
- **Script**: `scripts/investigate_event.py --event-id E001`
- **Loads**: ChangeEvent from Phase 1 data (change_events.json)
- **Works with**: MockSearchProvider (testing) or real SearchProvider (production)
- **API Keys**: From environment variables (SERPAPI_API_KEY, GOOGLE_API_KEY, etc.) - NEVER hardcoded
- **Output**: Complete EventAssessment with evidence-backed conclusions
- **Progress logging**: Shows each pipeline stage completion

### 10. Real Web Search Integration

**CLARIFIED**:
- **Adapter pattern**: Clean SearchProvider interface
- **API key management**: Via environment variables, never hardcoded
- **Providers**: MockSearchProvider, SerpAPIProvider, GoogleSearchProvider, TavilyProvider
- **Factory function**: `create_search_provider(name)` for runtime selection
- **Rate limiting**: Built into real provider implementations
- **Retry logic**: Exponential backoff on failures

### Complete Data Flow (Updated)

```
Phase 1 ChangeEvent 
  ↓
Hypothesis_Generator (signal_score, requires_external_evidence flag)
  ↓
Investigation_Agents (generate structured SearchQuery objects)
  ↓
SearchProvider Interface (Mock or Real: Google/SerpAPI/Tavily - NOT Channel3)
  ↓
SearchResultParser (HTML → ParsedContent)
  ↓
Evidence_Extraction (complete provenance: evidence_id, query_id, source metadata)
  ↓
Source_Independence_Analysis (INDEPENDENT vs DUPLICATED vs SYNDICATED)
  ↓
Verification_Agent (8 criteria, 5 support levels, conservative language)
  ↓
EventAssessment (multiple hypotheses SUPPORTED, NO diversity penalty, source independence metrics)
  ↓
Repository_Interface (JSON or CSV, NO PostgreSQL yet)
```

### Integration Points

1. **Entry Point**: `scripts/investigate_event.py --event-id E001`
2. **Phase 1 Input**: `data/events/change_events.json`
3. **Phase 2 Output**: `data/assessments/{event_id}_assessment.json`
4. **No Phase 1 Modifications**: All 112 existing tests continue to pass
5. **Testing**: MockSearchProvider for unit tests (no API keys, <60s)
6. **Production**: Real SearchProvider with API keys from environment

### Key Design Principles

1. **Uncertainty Preservation**: Multiple hypotheses, explicit uncertainty factors
2. **Conservative Verification**: Distinguish causation from correlation
3. **Source Independence**: Detect and discount duplicated content
4. **Complete Provenance**: Full traceability chain for all evidence
5. **Clean Abstractions**: Repository and SearchProvider interfaces
6. **Testability**: Mock-based tests without external dependencies
7. **Extensibility**: Pluggable providers and agents
8. **No RAG**: Live web search, not embeddings or vector retrieval


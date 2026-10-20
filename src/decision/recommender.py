"""
src/decision/recommender.py
============================
Lean, deterministic pricing decision support — no LLM, no RL.

*** MODEL-ASSUMPTION DEMO ***
All economic parameters (cost, demand elasticity, base demand) are
configurable assumptions, not estimates from data. The output shows
what the model recommends under those assumptions and how sensitive
the choice is to them. It is NOT a validated pricing policy.

Components
----------
1. CompetitorResponseEstimator
   Empirical probability of no_response / match / undercut,
   from historical event pairs. LOW_DATA flag when n < 5.

2. ScenarioModel
   cost = cost_ratio * median_price_before_change  (constant per event)
   demand = base_demand * exp(-beta * (our_price - comp_price)/comp_price)
   Actions: hold, match, raise_2pct, undercut_2pct, undercut_5pct.

3. MinimaxRegretSelector
   Regret = best_in_scenario - action_profit_in_scenario.
   Also reports expected-profit ranking.

4. Sensitivity table: chosen action for beta in {2,5,8} x cost_ratio in {0.7,0.8,0.9}.

5. DecisionRecommendation dataclass.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ACTIONS = ["hold", "match", "raise_2pct", "undercut_2pct", "undercut_5pct"]
SCENARIOS = ["no_response", "match", "undercut"]

DEFAULT_COST_RATIO   = 0.80   # cost = cost_ratio * median_price_before
DEFAULT_BETA         = 5.0    # demand sensitivity (higher = more elastic)
DEFAULT_BASE_DEMAND  = 100.0
MIN_EVENTS_FOR_CONFIDENCE = 5

SENSITIVITY_BETAS       = [2.0, 5.0, 8.0]
SENSITIVITY_COST_RATIOS = [0.7, 0.8, 0.9]


# ---------------------------------------------------------------------------
# 1. Competitor response estimator
# ---------------------------------------------------------------------------

class CompetitorResponseEstimator:
    """
    Estimates competitor response probabilities from historical events.
    Observational, not causal.
    """

    def __init__(self, repo, response_days: int = 7) -> None:
        self.repo = repo
        self.response_days = response_days

    def estimate(self, product_id: str) -> Dict[str, Any]:
        all_events = []
        for status in ["NEW", "INVESTIGATING", "INVESTIGATED", "FAILED"]:
            rows = self.repo.get_events_by_status(status)
            for row in rows:
                ev = row.get("event") or row
                if isinstance(ev, dict) and ev.get("product_id") == product_id:
                    all_events.append(ev)

        if not all_events:
            return self._uniform_prior("no events for this product")

        no_resp = matched = undercut = 0
        for focal in all_events:
            focal_merchant = focal.get("merchant", "")
            focal_ts_str = focal.get("observed_at", "")
            focal_pct = focal.get("percentage_change") or 0
            try:
                focal_ts = datetime.fromisoformat(focal_ts_str)
            except Exception:
                continue
            window_end = focal_ts + timedelta(days=self.response_days)
            responses = [
                other for other in all_events
                if other.get("merchant") != focal_merchant
                and focal_ts < datetime.fromisoformat(other.get("observed_at","1970-01-01")) <= window_end
            ]
            if not responses:
                no_resp += 1
            else:
                any_undercut = any_match = False
                for r in responses:
                    r_pct = r.get("percentage_change") or 0
                    if focal_pct < 0 and r_pct < 0:
                        if abs(r_pct) > abs(focal_pct) * 1.01:
                            any_undercut = True
                        elif abs(r_pct) > abs(focal_pct) * 0.98:
                            any_match = True
                if any_undercut:
                    undercut += 1
                elif any_match:
                    matched += 1
                else:
                    no_resp += 1

        total = no_resp + matched + undercut
        if total == 0:
            return self._uniform_prior("no processable events")

        if total < MIN_EVENTS_FOR_CONFIDENCE:
            result = self._uniform_prior("fewer than " + str(MIN_EVENTS_FOR_CONFIDENCE) + " events")
            result["sample_size"] = total
            result["confidence"] = "LOW_DATA"
            return result
        return {
            "no_response": round(no_resp / total, 3),
            "match":       round(matched / total, 3),
            "undercut":    round(undercut / total, 3),
            "sample_size": total,
            "confidence":  "OK",
            "response_days": self.response_days,
        }

    def _uniform_prior(self, reason: str) -> Dict[str, Any]:
        return {
            "no_response": 1/3, "match": 1/3, "undercut": 1/3,
            "sample_size": 0, "confidence": "LOW_DATA",
            "reason": reason, "response_days": self.response_days,
        }


# ---------------------------------------------------------------------------
# 2. Scenario model
# ---------------------------------------------------------------------------

class ScenarioModel:
    """
    Profit per (action, competitor_scenario).

    cost  = cost_ratio * median_price_before_change   [constant per event]
    demand = base_demand * exp(-beta * (our_price - comp_price) / comp_price)

    Parameters
    ----------
    our_price        : float  Our current price (pre-event, what we were charging).
    competitor_price : float  The price the competitor changed TO.
    median_price_before : float  Median market price BEFORE the event.
    cost_ratio       : float  Cost fraction of median_price_before (default 0.80).
    beta             : float  Demand sensitivity (default 5). Higher = more elastic.
    base_demand      : float  Baseline demand at price parity (default 100).
    """

    def __init__(
        self,
        our_price: float,
        competitor_price: float,
        median_price_before: float,
        cost_ratio: float = DEFAULT_COST_RATIO,
        beta: float = DEFAULT_BETA,
        base_demand: float = DEFAULT_BASE_DEMAND,
    ) -> None:
        self.our_price = our_price
        self.competitor_price = competitor_price
        self.median_price_before = median_price_before
        self.cost_ratio = cost_ratio
        self.beta = beta
        self.base_demand = base_demand
        # Cost is CONSTANT for the event — does not vary by action or scenario.
        self.cost = cost_ratio * median_price_before

    def compute_profit_table(self) -> Dict[str, Dict[str, float]]:
        table: Dict[str, Dict[str, float]] = {}
        for action in ACTIONS:
            our_new = self._action_price(action)
            table[action] = {}
            for scenario in SCENARIOS:
                comp_final = self._competitor_final_price(our_new, scenario)
                demand = self._demand(our_new, comp_final)
                profit = (our_new - self.cost) * demand
                table[action][scenario] = round(profit, 4)
        return table

    def _action_price(self, action: str) -> float:
        if action == "hold":           return self.our_price
        if action == "match":          return self.competitor_price
        if action == "raise_2pct":     return self.our_price * 1.02
        if action == "undercut_2pct":  return self.competitor_price * 0.98
        if action == "undercut_5pct":  return self.competitor_price * 0.95
        return self.our_price

    def _competitor_final_price(self, our_price: float, scenario: str) -> float:
        if scenario == "no_response": return self.competitor_price
        if scenario == "match":       return our_price
        if scenario == "undercut":    return our_price * 0.98
        return self.competitor_price

    def _demand(self, our_price: float, comp_price: float) -> float:
        """
        demand = base_demand * exp(-beta * (our_price - comp_price) / comp_price)
        When our_price == comp_price: demand = base_demand (parity)
        When our_price < comp_price:  demand > base_demand (cheaper wins)
        When our_price > comp_price:  demand < base_demand (dearer loses)
        """
        if comp_price <= 0:
            return self.base_demand
        x = (our_price - comp_price) / comp_price
        return self.base_demand * math.exp(-self.beta * x)

    @property
    def assumptions(self) -> List[str]:
        return [
            f"our_price = {self.our_price:.2f}  (pre-event price; NOT our actual listing price)",
            f"competitor_price = {self.competitor_price:.2f}  (the observed market price after change)",
            f"median_price_before = {self.median_price_before:.2f}  (median market price before the event)",
            f"cost = {self.cost:.2f}  = cost_ratio ({self.cost_ratio}) x median_price_before — CONSTANT for this event",
            f"beta = {self.beta}  (demand sensitivity; default 5 — ASSUMPTION, not estimated from data)",
            f"base_demand = {self.base_demand}  (relative units at price parity; not actual sales volume)",
            "Demand = base_demand * exp(-beta * (our_price - comp_price) / comp_price)",
            "Actions: hold, match, raise_2pct, undercut_2pct, undercut_5pct",
            "Competitor scenarios: no_response (stays at comp_price), match (mirrors our price), undercut (2% below ours)",
            "*** MODEL-ASSUMPTION DEMO: cost, beta, and base_demand are not estimated from data. ***",
        ]


# ---------------------------------------------------------------------------
# 3. Minimax regret selector
# ---------------------------------------------------------------------------

class MinimaxRegretSelector:

    def select(
        self,
        profit_table: Dict[str, Dict[str, float]],
        scenario_probs: Dict[str, float],
    ) -> Tuple[str, Dict[str, Dict[str, float]], List[Tuple[str, float]]]:
        regret_table: Dict[str, Dict[str, float]] = {}
        for action in profit_table:
            regret_table[action] = {}
            for scenario in profit_table[action]:
                best = max(profit_table[a][scenario] for a in profit_table)
                regret_table[action][scenario] = round(best - profit_table[action][scenario], 4)

        max_regrets = {a: max(regret_table[a].values()) for a in regret_table}
        chosen = min(max_regrets, key=max_regrets.__getitem__)

        ep_list = [
            (action, round(sum(
                profit_table[action][s] * scenario_probs.get(s, 1/3)
                for s in profit_table[action]), 4))
            for action in profit_table
        ]
        ep_list.sort(key=lambda x: -x[1])

        return chosen, regret_table, ep_list


# ---------------------------------------------------------------------------
# 4. Sensitivity analysis
# ---------------------------------------------------------------------------

def sensitivity_table(
    our_price: float,
    competitor_price: float,
    median_price_before: float,
    scenario_probs: Dict[str, float],
) -> Dict[str, Dict[str, str]]:
    """
    Returns {str(beta): {str(cost_ratio): chosen_action}}
    for beta in SENSITIVITY_BETAS x cost_ratio in SENSITIVITY_COST_RATIOS.
    """
    selector = MinimaxRegretSelector()
    result: Dict[str, Dict[str, str]] = {}
    for beta in SENSITIVITY_BETAS:
        row: Dict[str, str] = {}
        for cr in SENSITIVITY_COST_RATIOS:
            model = ScenarioModel(
                our_price=our_price,
                competitor_price=competitor_price,
                median_price_before=median_price_before,
                cost_ratio=cr,
                beta=beta,
            )
            pt = model.compute_profit_table()
            chosen, _, _ = selector.select(pt, scenario_probs)
            row[str(cr)] = chosen
        result[str(beta)] = row
    return result


# ---------------------------------------------------------------------------
# 5. DecisionRecommendation
# ---------------------------------------------------------------------------

@dataclass
class DecisionRecommendation:
    event_id: str
    product_id: str
    product_name: str
    merchant: str
    current_price: float
    competitor_price: float
    our_assumed_price: float
    median_price_before: float
    cost: float
    chosen_action: str
    profit_table: Dict[str, Dict[str, float]]
    regret_table: Dict[str, Dict[str, float]]
    expected_profit_ranking: List[Tuple[str, float]]
    scenario_probabilities: Dict[str, Any]
    sensitivity: Dict[str, Dict[str, str]]
    assumptions: List[str]
    investigation_verdicts: List[Dict[str, str]]
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def print_summary(self) -> None:
        print()
        print("=" * 70)
        print("SignalWatch Pricing Recommendation  [MODEL-ASSUMPTION DEMO]")
        print("=" * 70)
        print(f"Event:       {self.event_id}")
        print(f"Product:     {self.product_name[:60]}")
        print(f"Merchant:    {self.merchant}")
        print(f"Pre-event price:    USD {self.our_assumed_price:.2f}  (our assumed price)")
        print(f"Post-event price:   USD {self.competitor_price:.2f}  (competitor/market price)")
        print(f"Median pre-event:   USD {self.median_price_before:.2f}")
        print(f"Cost (constant):    = {self.cost/self.median_price_before*100:.0f}% of median pre-event")
        print()
        print(f">>> Recommended action: {self.chosen_action.upper()} <<<")
        print()

        print("Profit table  (demand = base*exp(-beta*(p-c)/c), base=100):")
        header = f"  {'Action':<18}" + "".join(f"  {s:<15}" for s in SCENARIOS)
        print(header)
        print("  " + "-" * 65)
        for action, scen_profits in self.profit_table.items():
            marker = ">>>" if action == self.chosen_action else "   "
            vals = "".join(f"  {scen_profits.get(s,0):<15.1f}" for s in SCENARIOS)
            print(f"  {marker} {action:<15}{vals}")
        print()

        print("Expected profit ranking:")
        for i, (action, ep) in enumerate(self.expected_profit_ranking, 1):
            marker = "<-- chosen" if action == self.chosen_action else ""
            print(f"  {i}. {action:<18} EP={ep:>8.1f}  {marker}")
        print()

        print("Sensitivity analysis — chosen action by (beta, cost_ratio):")
        cost_ratios = [str(cr) for cr in SENSITIVITY_COST_RATIOS]
        print(f"  {'beta \\ cost_ratio':<22}" + "".join(f"  {cr:<14}" for cr in cost_ratios))
        print("  " + "-" * 60)
        for beta, row in self.sensitivity.items():
            vals = "".join(f"  {row.get(cr,'?'):<14}" for cr in cost_ratios)
            marker = "  *" if beta == "5.0" else "   "
            print(f"  {marker} beta={beta:<15}{vals}")
        print("  (* = default beta)")
        print()

        sp = self.scenario_probabilities
        conf = sp.get("confidence", "?")
        n = sp.get("sample_size", 0)
        print(f"Scenario probs (competitor response, n={n}, {conf}):")
        for k in SCENARIOS:
            print(f"  {k:<18} {sp.get(k,0)*100:.0f}%")
        print()

        print("Investigation verdicts:")
        for v in self.investigation_verdicts:
            print(f"  {v.get('hypothesis','?'):<28} {v.get('support_level','?')}")
        print()

        print("Assumptions:")
        for a in self.assumptions:
            print(f"  {a}")
        print()


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def recommend(
    event_dict: Dict[str, Any],
    assessment_dict: Dict[str, Any],
    repo,
    our_price: Optional[float] = None,
    cost_ratio: float = DEFAULT_COST_RATIO,
    beta: float = DEFAULT_BETA,
) -> DecisionRecommendation:
    """
    Build a DecisionRecommendation.

    Parameters
    ----------
    event_dict       : ChangeEvent as dict
    assessment_dict  : EventAssessment as dict
    repo             : SignalWatchRepository (for competitor response estimation)
    our_price        : Override assumed own price (default = previous_price).
    cost_ratio       : Cost as fraction of median pre-event price (default 0.80).
    beta             : Demand sensitivity parameter (default 5).
    """
    product_id    = event_dict.get("product_id", "")
    product_name  = event_dict.get("product_name", product_id)
    merchant      = event_dict.get("merchant", "")
    current_price = float(event_dict.get("current_price") or 0)
    prev_price    = float(event_dict.get("previous_price") or current_price)
    comp_price    = current_price    # competitor's new price
    if our_price is None:
        our_price = prev_price       # our pre-event price

    # median_price_before = previous_price (best single-event proxy for pre-event median)
    median_price_before = prev_price

    estimator = CompetitorResponseEstimator(repo)
    scenario_probs = estimator.estimate(product_id)

    model = ScenarioModel(
        our_price=our_price,
        competitor_price=comp_price,
        median_price_before=median_price_before,
        cost_ratio=cost_ratio,
        beta=beta,
    )
    profit_table = model.compute_profit_table()

    selector = MinimaxRegretSelector()
    chosen, regret_table, ep_ranking = selector.select(profit_table, scenario_probs)

    sens = sensitivity_table(our_price, comp_price, median_price_before, scenario_probs)

    ha_list = assessment_dict.get("hypothesis_assessments", [])
    verdicts = [
        {"hypothesis": ha.get("hypothesis_type","?"), "support_level": ha.get("support_level","?")}
        for ha in ha_list
    ]

    return DecisionRecommendation(
        event_id=event_dict.get("event_id", ""),
        product_id=product_id,
        product_name=product_name,
        merchant=merchant,
        current_price=current_price,
        competitor_price=comp_price,
        our_assumed_price=our_price,
        median_price_before=median_price_before,
        cost=model.cost,
        chosen_action=chosen,
        profit_table=profit_table,
        regret_table=regret_table,
        expected_profit_ranking=ep_ranking,
        scenario_probabilities=scenario_probs,
        sensitivity=sens,
        assumptions=model.assumptions,
        investigation_verdicts=verdicts,
    )

"""
src/bocpd/incremental.py
=========================
Incremental BOCPD: processes one observation at a time, saving and
restoring detector state between observations.

The batch BOCPDDetector in detector.py is NOT modified.  This module
adds serialization helpers and an IncrementalDetector that:

  1. Restores a previously saved BOCPDDetector state from a dict.
  2. Computes log_price_diff from the stored last_price and the new price.
  3. Processes exactly one observation.
  4. Returns the BOCPDStep result + the state snapshot to persist.

Equivalence guarantee
---------------------
For a given series, feeding observations one at a time to IncrementalDetector
(with state saved and restored between every step) produces cp_probability
values that match the batch replay within floating-point tolerance.

This is verified by the batch-equivalence test in tests/bocpd/test_incremental.py.

Out-of-order and duplicate handling
-------------------------------------
Out-of-order: if the new observation's timestamp is <= last_observed_at,
  skip it and return None (never corrupt state).
Duplicate:    same timestamp — skip and return None.
First observation: no last_price available; seed last_price and return None
  (cannot compute log_price_diff for the first point).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from src.bocpd.config import BOCPDConfig
from src.bocpd.detector import BOCPDDetector, BOCPDStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State serialization helpers
# ---------------------------------------------------------------------------

def serialize_detector_state(detector: BOCPDDetector) -> Dict[str, Any]:
    """
    Capture the minimal detector state needed to resume incrementally.

    The _steps list is intentionally excluded: it is not needed to
    continue a series, and storing it would make the state unbounded.
    """
    return {
        "mu":                   detector._model.mu.tolist(),
        "kappa":                detector._model.kappa.tolist(),
        "alpha":                detector._model.alpha.tolist(),
        "beta":                 detector._model.beta.tolist(),
        "run_length_posterior": detector._run_length_posterior.tolist(),
        "t":                    detector._t,
    }


def restore_detector_state(state: Dict[str, Any], config: BOCPDConfig) -> BOCPDDetector:
    """
    Reconstruct a BOCPDDetector from a serialized state dict.

    The restored detector will produce identical output to a detector
    that processed the same observations in sequence from scratch.
    """
    detector = BOCPDDetector(config)
    detector._model.mu    = np.array(state["mu"],    dtype=np.float64)
    detector._model.kappa = np.array(state["kappa"], dtype=np.float64)
    detector._model.alpha = np.array(state["alpha"], dtype=np.float64)
    detector._model.beta  = np.array(state["beta"],  dtype=np.float64)
    detector._run_length_posterior = np.array(
        state["run_length_posterior"], dtype=np.float64
    )
    detector._t = int(state["t"])
    # _steps is not restored — not needed for incremental operation
    return detector


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------

@dataclass
class IncrementalStepResult:
    """Result of processing one observation through IncrementalDetector."""
    step: BOCPDStep
    new_state: Dict[str, Any]       # state to persist after this observation
    last_price: float               # the current price (to persist as last_price)
    last_observed_at: str           # the current timestamp
    observation_count: int          # updated total count


# ---------------------------------------------------------------------------
# Incremental detector
# ---------------------------------------------------------------------------

class IncrementalDetector:
    """
    Processes one observation at a time, restoring and saving state
    from/to a dict (suitable for SQLite storage).

    Parameters
    ----------
    config : BOCPDConfig, optional
        BOCPD configuration.  Defaults are unchanged from the batch path.
    """

    def __init__(self, config: Optional[BOCPDConfig] = None) -> None:
        self.config = config or BOCPDConfig()

    def process(
        self,
        new_price: float,
        observed_at: str,
        stored_state: Optional[Dict[str, Any]],
        last_price: Optional[float],
        last_observed_at: Optional[str],
        observation_count: int = 0,
    ) -> Optional[IncrementalStepResult]:
        """
        Process one new observation.

        Parameters
        ----------
        new_price : float
            The current price.
        observed_at : str
            ISO-8601 UTC timestamp of this observation.
        stored_state : dict or None
            Previously serialized detector state, or None if first observation.
        last_price : float or None
            The price at the previous observation, or None if first.
        last_observed_at : str or None
            Timestamp of the previous observation, or None if first.
        observation_count : int
            How many observations have been processed before this one.

        Returns
        -------
        IncrementalStepResult or None
            None for:
              - first observation (seeds last_price, no signal yet)
              - duplicate timestamp
              - out-of-order timestamp (older than last_observed_at)
        """
        # ------------------------------------------------------------------
        # Guard: first observation — seed last_price, no signal to compute
        # ------------------------------------------------------------------
        if last_price is None or last_observed_at is None:
            new_state = self._fresh_state(new_price)
            logger.debug(
                "IncrementalDetector: first observation at %s — seeding state",
                observed_at,
            )
            # Return a result with NaN cp_probability (warm-up, no event)
            detector = BOCPDDetector(self.config)
            step = detector.process_observation(float("nan"), pd.Timestamp(observed_at))
            new_state = serialize_detector_state(detector)
            return IncrementalStepResult(
                step=step,
                new_state=new_state,
                last_price=new_price,
                last_observed_at=observed_at,
                observation_count=observation_count + 1,
            )

        # ------------------------------------------------------------------
        # Guard: duplicate or out-of-order
        # ------------------------------------------------------------------
        if observed_at <= last_observed_at:
            logger.warning(
                "IncrementalDetector: skipping out-of-order/duplicate "
                "observation at %s (last was %s)",
                observed_at, last_observed_at,
            )
            return None

        # ------------------------------------------------------------------
        # Compute log_price_diff from stored last_price
        # ------------------------------------------------------------------
        try:
            log_price_diff = math.log(new_price / last_price)
        except (ValueError, ZeroDivisionError):
            logger.warning(
                "IncrementalDetector: cannot compute log_price_diff "
                "for price=%s last_price=%s — skipping",
                new_price, last_price,
            )
            return None

        # ------------------------------------------------------------------
        # Restore detector state and process the new observation
        # ------------------------------------------------------------------
        if stored_state is not None:
            detector = restore_detector_state(stored_state, self.config)
        else:
            # stored_state can be None if we have last_price but no state yet
            # (e.g. very first real signal after seeding)
            detector = BOCPDDetector(self.config)
            detector._t = observation_count

        ts = pd.Timestamp(observed_at)
        step = detector.process_observation(log_price_diff, ts)
        new_state = serialize_detector_state(detector)

        return IncrementalStepResult(
            step=step,
            new_state=new_state,
            last_price=new_price,
            last_observed_at=observed_at,
            observation_count=observation_count + 1,
        )

    def _fresh_state(self, price: float) -> Dict[str, Any]:
        """Minimal state when we have only one price point."""
        detector = BOCPDDetector(self.config)
        return serialize_detector_state(detector)

"""
src/bocpd/config.py
====================
All configurable parameters for the BOCPD detector, the observation model,
and the hazard function.  Every important value lives here — nothing is
hard-coded in the algorithm itself.

Assumptions documented
-----------------------
1.  Observation model: Student-t predictive (Normal-Gamma conjugate prior).
    The Normal-Gamma is the standard conjugate prior for a Gaussian
    likelihood with unknown mean AND unknown variance.  We use the
    Student-t marginal predictive rather than a fixed-variance Gaussian
    because the variance of price log-returns is itself uncertain,
    especially at the start of a new segment.  The Student-t has heavier
    tails than a Gaussian, making the model more robust to occasional
    large-but-not-change-point moves.

2.  Hazard function: constant hazard h = 1/lambda.
    Under a constant hazard the run-length prior is geometric with mean
    lambda.  This means on average a change point is expected every
    lambda observations.  For retail pricing data where prices can stay
    stable for months, lambda ~ 100–250 is a reasonable default.
    This is FULLY CONFIGURABLE.

3.  BOCPD input signal: log_price_diff (log-return).
    Log-returns are closer to i.i.d. Gaussian within a stable pricing
    regime than raw prices or raw differences.  The assumption is that
    within a regime the log-returns are drawn from a stationary
    distribution; a change point marks a transition to a new regime.

4.  Threshold for event detection: the posterior probability that the
    current run length is 0 (i.e. a change point just occurred).
    Configurable via cp_threshold.  Default 0.3 is deliberately
    conservative to avoid flooding the system with spurious events.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NormalGammaConfig:
    """
    Prior hyperparameters for the Normal-Gamma conjugate model.

    The Normal-Gamma(mu0, kappa0, alpha0, beta0) represents our prior
    belief about the mean and precision (1/variance) of the observations
    within a segment.

    Parameters
    ----------
    mu0 : float
        Prior mean of the segment mean.
        For log-price differences centred near zero, 0.0 is appropriate.
    kappa0 : float
        Prior pseudo-count for the mean.  Small values (e.g. 1.0) give
        the data more influence over the posterior mean.
    alpha0 : float
        Shape parameter of the Gamma prior on precision.
        Must be > 0.  Value of 1.0 is a weakly informative prior.
    beta0 : float
        Rate parameter of the Gamma prior on precision.
        beta0 / alpha0 is the prior mean of variance.
        For log-price returns with std ~0.05–0.5, beta0 ~ 0.1 is
        a reasonable weakly informative choice (gives prior mean
        variance of 0.1 when alpha0=1.0).
    """
    mu0: float = 0.0
    kappa0: float = 1.0
    alpha0: float = 1.0
    beta0: float = 0.04


@dataclass
class HazardConfig:
    """
    Configuration for the constant hazard function.

    Parameters
    ----------
    lambda_val : float
        Expected number of observations between change points.
        The constant hazard h = 1 / lambda_val.

        Guidance:
        * lambda_val = 50   → change point expected every 50 observations
        * lambda_val = 100  → every 100 observations (default)
        * lambda_val = 250  → every 250 observations (stable prices)

        Larger values → fewer detected change points (more conservative).
        Smaller values → more detected change points (more sensitive).
    """
    lambda_val: float = 100.0

    @property
    def hazard(self) -> float:
        """Constant hazard probability h = 1 / lambda_val."""
        return 1.0 / self.lambda_val


@dataclass
class BOCPDConfig:
    """
    Master configuration object for the BOCPD detector.

    Parameters
    ----------
    observation_signal : str
        Column name in the features DataFrame to use as BOCPD input.
        Default is 'log_price_diff'.  Must be a numeric column.
    hazard : HazardConfig
        Hazard function configuration.
    model : NormalGammaConfig
        Normal-Gamma prior hyperparameters.
    cp_threshold : float
        Posterior probability P(run_length=0 | data) above which an
        observation is flagged as a potential change point.
        Range: (0, 1).  Default: 0.3.
    min_observations_before_detection : int
        Number of observations to process before any change-point
        probability is returned.  During the warm-up period the
        posterior is too uncertain to be useful.  Default: 3.
    max_run_length : int
        Maximum run length tracked in the posterior.  Capping this
        prevents the posterior matrix from growing unbounded for very
        long series.  Default: 500.
        Setting to 0 means uncapped (use with caution for long series).
    """
    observation_signal: str = "log_price_diff"
    hazard: HazardConfig = field(default_factory=HazardConfig)
    model: NormalGammaConfig = field(default_factory=NormalGammaConfig)
    cp_threshold: float = 0.30
    min_observations_before_detection: int = 3
    max_run_length: int = 500

    def describe(self) -> str:
        lines = [
            "BOCPD Configuration",
            "-" * 40,
            f"  Observation signal   : {self.observation_signal}",
            f"  Hazard lambda        : {self.hazard.lambda_val} obs/change-point",
            f"  Constant hazard h    : {self.hazard.hazard:.6f}",
            f"  NG prior mu0         : {self.model.mu0}",
            f"  NG prior kappa0      : {self.model.kappa0}",
            f"  NG prior alpha0      : {self.model.alpha0}",
            f"  NG prior beta0       : {self.model.beta0}",
            f"  CP threshold         : {self.cp_threshold}",
            f"  Warm-up obs          : {self.min_observations_before_detection}",
            f"  Max run length       : {self.max_run_length}",
        ]
        return "\n".join(lines)

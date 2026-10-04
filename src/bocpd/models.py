"""
src/bocpd/models.py
====================
Observation model for Bayesian Online Change-Point Detection.

The observation model provides:
  1. A conjugate prior that can be updated sequentially.
  2. A predictive probability p(x_t | x_{1:t-1}, run started at r) for
     each possible run length r.

Model implemented: Normal-Gamma (Student-t predictive)
-------------------------------------------------------
Assumption:
  Within a segment, observations x_t are i.i.d. Normal(mu, 1/tau) where
  both mu and tau (precision) are unknown.

Prior:
  (mu, tau) ~ NormalGamma(mu0, kappa0, alpha0, beta0)

  mu | tau  ~ Normal(mu0, 1 / (kappa0 * tau))
  tau       ~ Gamma(alpha0, beta0)

Posterior update (online, sequential):
  After observing x_1, ..., x_n within a segment:

  mu_n    = (kappa0 * mu0 + n * x_bar) / (kappa0 + n)
  kappa_n = kappa0 + n
  alpha_n = alpha0 + n/2
  beta_n  = beta0 + 0.5 * sum((x_i - x_bar)^2)
           + (kappa0 * n * (x_bar - mu0)^2) / (2 * (kappa0 + n))

  where x_bar = mean of x_1..x_n.

Predictive distribution:
  p(x_{n+1} | x_{1:n}) is a Student-t with:
    df      = 2 * alpha_n
    loc     = mu_n
    scale   = sqrt(beta_n * (kappa_n + 1) / (alpha_n * kappa_n))

  This is the standard result for Normal-Gamma conjugate analysis.

Reference:
  Adams & MacKay (2007) "Bayesian Online Changepoint Detection"
  https://arxiv.org/abs/0710.3742
  (Section 2 and Appendix A for Normal-Gamma)

Implementation notes:
  * Each run-length hypothesis r maintains its own NormalGamma sufficient
    statistics (mu_r, kappa_r, alpha_r, beta_r).
  * When a new observation arrives, for each run-length hypothesis r we
    compute p(x | r) using the current Student-t predictive, then update
    the sufficient statistics by incorporating x.
  * The run-length r=0 hypothesis is seeded with the prior hyperparameters.
  * All operations are vectorised over run lengths using NumPy arrays.
"""

from __future__ import annotations

import numpy as np
from scipy import stats  # for Student-t PDF

from .config import NormalGammaConfig


class NormalGammaModel:
    """
    Vectorised Normal-Gamma observation model for BOCPD.

    Maintains a separate set of sufficient statistics for each active
    run-length hypothesis.  The arrays grow by one element each time
    a new observation is processed (one new run-length hypothesis: r=0).

    Attributes
    ----------
    mu : np.ndarray      shape (n_run_lengths,)
    kappa : np.ndarray   shape (n_run_lengths,)
    alpha : np.ndarray   shape (n_run_lengths,)
    beta : np.ndarray    shape (n_run_lengths,)
    """

    def __init__(self, config: NormalGammaConfig) -> None:
        self._cfg = config
        self.reset()

    def reset(self) -> None:
        """Reinitialise with a single run-length hypothesis (r=0, prior)."""
        c = self._cfg
        self.mu = np.array([c.mu0], dtype=np.float64)
        self.kappa = np.array([c.kappa0], dtype=np.float64)
        self.alpha = np.array([c.alpha0], dtype=np.float64)
        self.beta = np.array([c.beta0], dtype=np.float64)

    @property
    def n_hypotheses(self) -> int:
        """Number of active run-length hypotheses."""
        return len(self.mu)

    def predictive_pdf(self, x: float) -> np.ndarray:
        """
        Compute the predictive probability p(x | run started at r) for
        every active run-length hypothesis r.

        The predictive is a Student-t:
          df    = 2 * alpha
          loc   = mu
          scale = sqrt(beta * (kappa + 1) / (alpha * kappa))

        Parameters
        ----------
        x : float
            The new observation.

        Returns
        -------
        np.ndarray  shape (n_hypotheses,)
            Predictive PDF evaluated at x for each run-length hypothesis.
        """
        df = 2.0 * self.alpha
        loc = self.mu
        # Guard against degenerate scale (alpha or kappa → 0)
        scale_sq = (self.beta * (self.kappa + 1.0)) / (
            np.maximum(self.alpha, 1e-12) * np.maximum(self.kappa, 1e-12)
        )
        scale = np.sqrt(np.maximum(scale_sq, 1e-20))

        # scipy.stats.t.pdf is vectorised over loc/scale when df is scalar
        # but we have a vector of df values too.
        # Compute manually for full vectorisation:
        return _student_t_pdf_vectorised(x, df, loc, scale)

    def update(self, x: float) -> None:
        """
        Update the sufficient statistics of every EXISTING run-length
        hypothesis by incorporating the new observation x.

        This is called AFTER predictive_pdf() has been evaluated.
        The new r=0 hypothesis (seeded with the prior) is prepended
        by the caller (the detector), so this method only updates
        the existing hypotheses.

        Normal-Gamma conjugate update:
          kappa_new = kappa + 1
          mu_new    = (kappa * mu + x) / kappa_new
          alpha_new = alpha + 0.5
          beta_new  = beta + (kappa * (x - mu)^2) / (2 * kappa_new)
        """
        delta = x - self.mu
        kappa_new = self.kappa + 1.0
        mu_new = (self.kappa * self.mu + x) / kappa_new
        alpha_new = self.alpha + 0.5
        beta_new = self.beta + (self.kappa * delta ** 2) / (2.0 * kappa_new)

        self.mu = mu_new
        self.kappa = kappa_new
        self.alpha = alpha_new
        self.beta = beta_new

    def prepend_prior(self) -> None:
        """
        Prepend a new run-length-0 hypothesis seeded with the prior.

        Called by the detector each time step to account for the
        possibility that a change point occurred just before this
        observation.
        """
        c = self._cfg
        self.mu = np.concatenate([[c.mu0], self.mu])
        self.kappa = np.concatenate([[c.kappa0], self.kappa])
        self.alpha = np.concatenate([[c.alpha0], self.alpha])
        self.beta = np.concatenate([[c.beta0], self.beta])

    def truncate(self, max_run_length: int) -> None:
        """
        Cap the number of active hypotheses to ``max_run_length``.

        Hypotheses beyond this are dropped (they have negligible weight
        after many observations).  This keeps memory bounded.
        """
        if max_run_length > 0 and len(self.mu) > max_run_length:
            self.mu = self.mu[:max_run_length]
            self.kappa = self.kappa[:max_run_length]
            self.alpha = self.alpha[:max_run_length]
            self.beta = self.beta[:max_run_length]


# ---------------------------------------------------------------------------
# Vectorised Student-t PDF helper
# ---------------------------------------------------------------------------

def _student_t_pdf_vectorised(
    x: float,
    df: np.ndarray,
    loc: np.ndarray,
    scale: np.ndarray,
) -> np.ndarray:
    """
    Evaluate the Student-t PDF at scalar x for arrays of df, loc, scale.

    Uses the log-PDF for numerical stability, then exponentiates.
    """
    z = (x - loc) / np.maximum(scale, 1e-20)

    # log-PDF of Student-t: log Gamma((df+1)/2) - log Gamma(df/2)
    #                        - 0.5*log(pi*df) - 0.5*log(scale^2)
    #                        - ((df+1)/2) * log(1 + z^2/df)
    log_pdf = (
        _log_gamma_half(df + 1.0)
        - _log_gamma_half(df)
        - 0.5 * np.log(np.pi * df)
        - np.log(np.maximum(scale, 1e-20))
        - 0.5 * (df + 1.0) * np.log1p(z ** 2 / np.maximum(df, 1e-12))
    )
    return np.exp(np.clip(log_pdf, -500, 500))


def _log_gamma_half(x: np.ndarray) -> np.ndarray:
    """
    Compute log Gamma(x/2) element-wise using scipy's gammaln.
    More numerically stable than computing Gamma directly.
    """
    from scipy.special import gammaln
    return gammaln(x / 2.0)

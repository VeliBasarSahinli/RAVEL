"""Linear Thompson Sampling (LinTS) — CLAUDE.md uyumlu.

Her eylem için ayrı Bayesyen lineer regresyon parametreleri:
    A_a  ∈ R^{d×d}  precision matrix      (init: I)
    b_a  ∈ R^d      reward-weighted sum   (init: 0)

Posterior:  θ_a ~ N( A_a^{-1} b_a , α · A_a^{-1} )
Karar:       eylem = argmax_a  context^T · θ_sample_a
Güncelleme:  A_a += xx^T,  b_a += r·x      (online Bayesian update)

Inference path Cholesky decomposition ile yapılır (scipy.linalg);
12-boyutlu single-node LinTS için tipik latency <1 ms.
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np
from scipy.linalg import cho_factor, cho_solve

logger = logging.getLogger(__name__)


class LinTS:
    def __init__(self, n_actions: int, context_dim: int, alpha: float = 1.0):
        if n_actions < 1:
            raise ValueError("n_actions must be >= 1")
        if context_dim < 1:
            raise ValueError("context_dim must be >= 1")
        if alpha <= 0:
            raise ValueError("alpha must be > 0")

        self.n_actions = n_actions
        self.context_dim = context_dim
        self.alpha = alpha

        # Per-action precision matrices and reward vectors
        self.A: list[np.ndarray] = [np.eye(context_dim) for _ in range(n_actions)]
        self.b: list[np.ndarray] = [np.zeros(context_dim) for _ in range(n_actions)]

    # ─── Inference ──────────────────────────────────────────────────

    def select_action(self, context: np.ndarray) -> Tuple[int, float]:
        """Thompson Sampling: her eylemden θ örnekle, en yüksek tahmini
        ödülü veren eylemi seç. Confidence skoru = sampled reward'ların
        softmax'ından seçilen eylemin payı.
        """
        if context.shape != (self.context_dim,):
            raise ValueError(
                f"context shape {context.shape} != expected ({self.context_dim},)"
            )

        sampled_rewards = np.empty(self.n_actions)
        for a in range(self.n_actions):
            try:
                # A^{-1} via Cholesky (A is SPD by construction)
                c, low = cho_factor(self.A[a], lower=False)
                A_inv = cho_solve((c, low), np.eye(self.context_dim))
            except np.linalg.LinAlgError:
                A_inv = np.linalg.pinv(self.A[a])

            theta_mean = A_inv @ self.b[a]
            theta_cov = self.alpha * A_inv

            try:
                # Force symmetry to neutralize floating-point drift before sampling
                theta_cov = (theta_cov + theta_cov.T) / 2.0
                theta_sample = np.random.multivariate_normal(theta_mean, theta_cov)
            except np.linalg.LinAlgError:
                # Posterior collapsed numerically — fall back to mean
                theta_sample = theta_mean

            sampled_rewards[a] = float(context @ theta_sample)

        action = int(np.argmax(sampled_rewards))

        # Softmax-normalized confidence over sampled rewards
        shifted = sampled_rewards - np.max(sampled_rewards)
        exp_r = np.exp(shifted)
        probs = exp_r / np.sum(exp_r)
        confidence = float(probs[action])

        return action, confidence

    # ─── Online update ──────────────────────────────────────────────

    def update(self, context: np.ndarray, action: int, reward: float) -> None:
        if context.shape != (self.context_dim,):
            raise ValueError("context shape mismatch")
        if not (0 <= action < self.n_actions):
            raise ValueError(f"action {action} out of range [0, {self.n_actions})")

        # A_a += xx^T;  b_a += r · x
        self.A[action] += np.outer(context, context)
        self.b[action] += float(reward) * context

    # ─── Serialization for MinIO ────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "n_actions": self.n_actions,
            "context_dim": self.context_dim,
            "alpha": self.alpha,
            "A": [a.tolist() for a in self.A],
            "b": [b.tolist() for b in self.b],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LinTS":
        instance = cls(
            n_actions=int(data["n_actions"]),
            context_dim=int(data["context_dim"]),
            alpha=float(data["alpha"]),
        )
        instance.A = [np.array(a, dtype=np.float64) for a in data["A"]]
        instance.b = [np.array(b, dtype=np.float64) for b in data["b"]]
        return instance

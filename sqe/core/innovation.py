"""Deterministic innovation residual estimator."""

from __future__ import annotations

import math
from typing import Optional, Tuple


class InnovationModel:
    """Constant-velocity Kalman residual normalizer.

    The model tracks scalar position and velocity with a fixed process/measurement
    noise model. It is deterministic for identical input sequences.

    Return signature for :meth:`update` is ``(e, S, z, v_hat, eta)``.

    * If ``y is None``: predict-only is applied (when initialized), ``e`` and ``z``
      are ``None``, ``S`` is the predicted innovation variance, and ``eta`` is
      unchanged.
    * If the model is uninitialized and ``y is None``: state remains uninitialized,
      ``S`` is based on prior-free uncertainty ``max(r, s_min)``, ``v_hat`` is 0.
    * If ``dt <= 0``: ``dt`` is clamped to ``0``.
    """

    def __init__(
        self,
        q: float,
        r: float,
        beta: float,
        s_min: float,
        p0_var: float,
        v0_var: float,
    ) -> None:
        if q < 0.0:
            raise ValueError("q must be >= 0")
        if r < 0.0:
            raise ValueError("r must be >= 0")
        if not 0.0 <= beta <= 1.0:
            raise ValueError("beta must be in [0, 1]")
        if s_min <= 0.0:
            raise ValueError("s_min must be > 0")
        if p0_var < 0.0 or v0_var < 0.0:
            raise ValueError("p0_var and v0_var must be >= 0")

        self.q = float(q)
        self.r = float(r)
        self.beta = float(beta)
        self.s_min = float(s_min)
        self.p0_var = float(p0_var)
        self.v0_var = float(v0_var)

        self.reset()

    def reset(self) -> None:
        """Reset internal model state to uninitialized."""
        self.initialized = False
        self.p = 0.0
        self.v = 0.0
        self.P00 = 0.0
        self.P01 = 0.0
        self.P10 = 0.0
        self.P11 = 0.0
        self.eta = 0.0

    def update(
        self,
        y: Optional[float],
        dt: float,
    ) -> Tuple[Optional[float], float, Optional[float], float, float]:
        """Process one measurement and return ``(e, S, z, v_hat, eta)``."""
        dt_eff = dt if dt > 0.0 else 0.0

        if not self.initialized:
            if y is None:
                s_val = self.r if self.r > self.s_min else self.s_min
                return None, s_val, None, 0.0, self.eta

            y_val = float(y)
            self.p = y_val
            self.v = 0.0
            self.P00 = self.p0_var
            self.P01 = 0.0
            self.P10 = 0.0
            self.P11 = self.v0_var
            self.initialized = True

            s_raw = self.P00 + self.r
            s_val = s_raw if s_raw > self.s_min else self.s_min
            e_val = 0.0
            z_val = 0.0
            self.eta = (1.0 - self.beta) * self.eta + self.beta * (z_val * z_val)
            return e_val, s_val, z_val, self.v, self.eta

        # Predict state
        p_pred = self.p + dt_eff * self.v
        v_pred = self.v

        # Predict covariance: A P A^T + Q with A=[[1,dt],[0,1]]
        a00 = self.P00 + dt_eff * self.P10
        a01 = self.P01 + dt_eff * self.P11
        a10 = self.P10
        a11 = self.P11

        P00_pred = a00 + dt_eff * a01
        P01_pred = a01
        P10_pred = a10 + dt_eff * a11
        P11_pred = a11

        q00 = self.q * (dt_eff * dt_eff * dt_eff / 3.0)
        q01 = self.q * (dt_eff * dt_eff / 2.0)
        q11 = self.q * dt_eff

        P00_pred += q00
        P01_pred += q01
        P10_pred += q01
        P11_pred += q11

        s_raw = P00_pred + self.r
        S = s_raw if s_raw > self.s_min else self.s_min

        if y is None:
            self.p = p_pred
            self.v = v_pred
            self.P00 = P00_pred
            self.P01 = P01_pred
            self.P10 = P10_pred
            self.P11 = P11_pred
            return None, S, None, self.v, self.eta

        y_val = float(y)
        e = y_val - p_pred
        z = e / math.sqrt(S)

        k0 = P00_pred / S
        k1 = P10_pred / S

        self.p = p_pred + k0 * e
        self.v = v_pred + k1 * e

        # P = (I - K H) P, H=[1,0]
        self.P00 = (1.0 - k0) * P00_pred
        self.P01 = (1.0 - k0) * P01_pred
        self.P10 = P10_pred - k1 * P00_pred
        self.P11 = P11_pred - k1 * P01_pred

        self.eta = (1.0 - self.beta) * self.eta + self.beta * (z * z)

        return e, S, z, self.v, self.eta

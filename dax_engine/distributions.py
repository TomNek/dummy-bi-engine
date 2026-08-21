"""Pure-Python statistical distribution functions matching DAX/Excel semantics.

Implemented using only the Python ``math`` standard library (no scipy required).
Registered as DuckDB Python UDFs by dax_engine.duckdb_udfs.
"""
from __future__ import annotations

import math
from typing import Optional

# ── Normal distribution ──────────────────────────────────────────────

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


def norm_pdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * _SQRT2PI)


def norm_cdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    z = (x - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / _SQRT2))


def norm_inv(p: float, mu: float = 0.0, sigma: float = 1.0) -> Optional[float]:
    """Inverse normal distribution (Peter Acklam's rational approximation)."""
    if p <= 0 or p >= 1:
        return None
    z = _standard_norm_inv(p)
    return mu + sigma * z


def _standard_norm_inv(p: float) -> float:
    """Standard normal inverse CDF (quantile function).

    Peter Acklam's algorithm, max absolute error < 1.15e-9.
    """
    # Coefficients
    a = (-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00)

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)


# ── Gamma / Beta helpers ────────────────────────────────────────────

def _log_gamma(x: float) -> float:
    return math.lgamma(x)


def _regularized_gamma_p(a: float, x: float) -> float:
    """Lower regularized incomplete gamma function P(a, x).

    Uses series expansion for x < a+1, continued fraction otherwise.
    """
    if x < 0:
        return 0.0
    if x == 0:
        return 0.0
    if x < a + 1:
        return _gamma_series(a, x)
    else:
        return 1.0 - _gamma_cf(a, x)


def _gamma_series(a: float, x: float) -> float:
    """Series expansion for P(a, x)."""
    lg = _log_gamma(a)
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(300):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * 1e-15:
            break
    return total * math.exp(-x + a * math.log(x) - lg)


def _gamma_cf(a: float, x: float) -> float:
    """Continued fraction for Q(a, x) = 1 - P(a, x)."""
    lg = _log_gamma(a)
    b_cf = x + 1.0 - a
    c = 1e30
    d = 1.0 / b_cf if b_cf != 0 else 1e30
    h = d
    for i in range(1, 300):
        an = -float(i) * (float(i) - a)
        b_cf += 2.0
        d = an * d + b_cf
        if abs(d) < 1e-30:
            d = 1e-30
        c = b_cf + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - lg) * h


def _regularized_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b).

    Uses continued fraction (Lentz's algorithm).
    """
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    # Use symmetry for better convergence
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularized_beta(1.0 - x, b, a)

    lg = _log_gamma(a + b) - _log_gamma(a) - _log_gamma(b)
    front = math.exp(lg + a * math.log(x) + b * math.log(1.0 - x)) / a

    # Lentz's continued fraction
    f = 1.0
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    f = d

    for m in range(1, 300):
        # Even step
        m2 = 2 * m
        num = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        f *= d * c

        # Odd step
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + num * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        f *= delta
        if abs(delta - 1.0) < 1e-15:
            break

    return front * f


# ── Chi-squared distribution ────────────────────────────────────────

def chisq_cdf(x: float, df: float) -> float:
    """Chi-squared CDF."""
    if x <= 0:
        return 0.0
    return _regularized_gamma_p(float(df) / 2.0, float(x) / 2.0)


def chisq_inv(p: float, df: float) -> Optional[float]:
    """Chi-squared inverse CDF (Newton-Raphson)."""
    if p <= 0 or p >= 1 or df <= 0:
        return None
    # Initial guess from normal approximation
    z = _standard_norm_inv(p)
    x = max(df * (1.0 - 2.0 / (9.0 * df) + z * math.sqrt(2.0 / (9.0 * df))) ** 3, 0.01)
    for _ in range(200):
        cdf_val = chisq_cdf(x, df)
        pdf_val = _chisq_pdf(x, df)
        if pdf_val < 1e-15:
            break
        diff = cdf_val - p
        if abs(diff) < 1e-12:
            return x
        x -= diff / pdf_val
        x = max(x, 1e-10)
    return x


def _chisq_pdf(x: float, df: float) -> float:
    if x <= 0:
        return 0.0
    k = float(df) / 2.0
    return math.exp((k - 1) * math.log(x / 2.0) - x / 2.0 - _log_gamma(k)) / 2.0


# ── Student's t-distribution ────────────────────────────────────────

def t_cdf(x: float, df: float) -> float:
    """Student's t-distribution CDF."""
    df = float(df)
    t = float(x)
    if df <= 0:
        return 0.0
    xt = df / (df + t * t)
    # I_x(df/2, 1/2) via regularized beta
    ibeta = _regularized_beta(xt, df / 2.0, 0.5)
    if t >= 0:
        return 1.0 - 0.5 * ibeta
    else:
        return 0.5 * ibeta


def t_inv(p: float, df: float) -> Optional[float]:
    """Student's t inverse CDF (Newton-Raphson)."""
    if p <= 0 or p >= 1 or df <= 0:
        return None
    # Initial guess from normal approx
    x = _standard_norm_inv(p)
    for _ in range(200):
        cdf_val = t_cdf(x, df)
        pdf_val = _t_pdf(x, df)
        if pdf_val < 1e-15:
            break
        diff = cdf_val - p
        if abs(diff) < 1e-12:
            return x
        x -= diff / pdf_val
    return x


def _t_pdf(x: float, df: float) -> float:
    """Student's t PDF."""
    df = float(df)
    lg = _log_gamma((df + 1) / 2.0) - _log_gamma(df / 2.0)
    return math.exp(lg) / math.sqrt(df * math.pi) * \
           (1.0 + x * x / df) ** (-(df + 1) / 2.0)


# ── Beta distribution ───────────────────────────────────────────────

def beta_cdf(x: float, alpha: float, beta_param: float,
             a: float = 0.0, b: float = 1.0) -> float:
    """Beta distribution CDF."""
    if b <= a:
        return 0.0
    z = (float(x) - a) / (b - a)
    z = max(0.0, min(1.0, z))
    return _regularized_beta(z, float(alpha), float(beta_param))


def beta_inv(p: float, alpha: float, beta_param: float,
             a: float = 0.0, b: float = 1.0) -> Optional[float]:
    """Beta distribution inverse CDF (Newton-Raphson)."""
    if p <= 0 or p >= 1 or alpha <= 0 or beta_param <= 0:
        return None
    a_val, b_val = float(a), float(b)
    # Initial guess
    x = float(p)
    for _ in range(200):
        cdf_val = _regularized_beta(x, float(alpha), float(beta_param))
        pdf_val = _beta_pdf(x, float(alpha), float(beta_param))
        if pdf_val < 1e-15:
            break
        diff = cdf_val - p
        if abs(diff) < 1e-12:
            return a_val + x * (b_val - a_val)
        x -= diff / pdf_val
        x = max(1e-10, min(1 - 1e-10, x))
    return a_val + x * (b_val - a_val)


def _beta_pdf(x: float, alpha: float, beta_param: float) -> float:
    if x <= 0 or x >= 1:
        return 0.0
    lg = _log_gamma(alpha + beta_param) - _log_gamma(alpha) - _log_gamma(beta_param)
    return math.exp(lg + (alpha - 1) * math.log(x) + (beta_param - 1) * math.log(1 - x))


# ── Poisson distribution ────────────────────────────────────────────

def poisson_cdf(x: float, mean: float) -> float:
    """Poisson CDF = P(X <= x)."""
    if mean <= 0:
        return 1.0
    k = int(x)
    if k < 0:
        return 0.0
    # P(X <= k) = 1 - P(a=k+1, x=mean)  via regularized gamma
    return 1.0 - _regularized_gamma_p(float(k + 1), float(mean))


def poisson_pmf(x: float, mean: float) -> float:
    """Poisson PMF."""
    k = int(x)
    if k < 0 or mean <= 0:
        return 0.0
    return math.exp(-mean + k * math.log(mean) - _log_gamma(k + 1))


# ── Exponential distribution ────────────────────────────────────────

def expon_cdf(x: float, lam: float) -> float:
    """Exponential CDF."""
    if x < 0 or lam <= 0:
        return 0.0
    return 1.0 - math.exp(-lam * x)


def expon_pdf(x: float, lam: float) -> float:
    if x < 0 or lam <= 0:
        return 0.0
    return lam * math.exp(-lam * x)


# ── Confidence intervals ────────────────────────────────────────────

def confidence_norm(alpha: float, std_dev: float, size: float) -> Optional[float]:
    """Normal confidence interval half-width."""
    if any(v is None for v in (alpha, std_dev, size)):
        return None
    if alpha <= 0 or alpha >= 1 or std_dev <= 0 or size <= 0:
        return None
    z = _standard_norm_inv(1.0 - float(alpha) / 2.0)
    return z * float(std_dev) / math.sqrt(float(size))


def confidence_t(alpha: float, std_dev: float, size: float) -> Optional[float]:
    """T-distribution confidence interval half-width."""
    if any(v is None for v in (alpha, std_dev, size)):
        return None
    if alpha <= 0 or alpha >= 1 or std_dev <= 0 or size <= 1:
        return None
    df = float(size) - 1.0
    t_val = t_inv(1.0 - float(alpha) / 2.0, df)
    if t_val is None:
        return None
    return t_val * float(std_dev) / math.sqrt(float(size))


# ── Public dispatch functions (for UDF registration) ─────────────────

def dax_norm_dist(x, mu, sigma, cumulative) -> Optional[float]:
    if any(v is None for v in (x, mu, sigma, cumulative)):
        return None
    x, mu, sigma = float(x), float(mu), float(sigma)
    cum = _to_bool(cumulative)
    if cum:
        return norm_cdf(x, mu, sigma)
    return norm_pdf(x, mu, sigma)


def dax_norm_s_dist(z, cumulative) -> Optional[float]:
    if any(v is None for v in (z, cumulative)):
        return None
    cum = _to_bool(cumulative)
    if cum:
        return norm_cdf(float(z))
    return norm_pdf(float(z))


def dax_norm_inv(p, mu, sigma) -> Optional[float]:
    if any(v is None for v in (p, mu, sigma)):
        return None
    return norm_inv(float(p), float(mu), float(sigma))


def dax_norm_s_inv(p) -> Optional[float]:
    if p is None:
        return None
    return norm_inv(float(p))


def dax_t_dist(x, df, cumulative) -> Optional[float]:
    if any(v is None for v in (x, df, cumulative)):
        return None
    cum = _to_bool(cumulative)
    if cum:
        return t_cdf(float(x), float(df))
    return _t_pdf(float(x), float(df))


def dax_t_dist_2t(x, df) -> Optional[float]:
    if any(v is None for v in (x, df)):
        return None
    return 2.0 * (1.0 - t_cdf(abs(float(x)), float(df)))


def dax_t_dist_rt(x, df) -> Optional[float]:
    if any(v is None for v in (x, df)):
        return None
    return 1.0 - t_cdf(float(x), float(df))


def dax_t_inv(p, df) -> Optional[float]:
    if any(v is None for v in (p, df)):
        return None
    return t_inv(float(p), float(df))


def dax_t_inv_2t(p, df) -> Optional[float]:
    if any(v is None for v in (p, df)):
        return None
    return t_inv(1.0 - float(p) / 2.0, float(df))


def dax_chisq_dist(x, df, cumulative) -> Optional[float]:
    if any(v is None for v in (x, df, cumulative)):
        return None
    cum = _to_bool(cumulative)
    if cum:
        return chisq_cdf(float(x), float(df))
    return _chisq_pdf(float(x), float(df))


def dax_chisq_dist_rt(x, df) -> Optional[float]:
    if any(v is None for v in (x, df)):
        return None
    return 1.0 - chisq_cdf(float(x), float(df))


def dax_chisq_inv(p, df) -> Optional[float]:
    if any(v is None for v in (p, df)):
        return None
    return chisq_inv(float(p), float(df))


def dax_chisq_inv_rt(p, df) -> Optional[float]:
    if any(v is None for v in (p, df)):
        return None
    return chisq_inv(1.0 - float(p), float(df))


def dax_beta_dist(x, alpha, beta_param, cumulative, *args) -> Optional[float]:
    if any(v is None for v in (x, alpha, beta_param, cumulative)):
        return None
    a_bound = float(args[0]) if len(args) > 0 and args[0] is not None else 0.0
    b_bound = float(args[1]) if len(args) > 1 and args[1] is not None else 1.0
    cum = _to_bool(cumulative)
    if cum:
        return beta_cdf(float(x), float(alpha), float(beta_param), a_bound, b_bound)
    # PDF for beta distribution with bounds
    if b_bound <= a_bound:
        return 0.0
    z = (float(x) - a_bound) / (b_bound - a_bound)
    return _beta_pdf(z, float(alpha), float(beta_param)) / (b_bound - a_bound)


def dax_beta_inv(p, alpha, beta_param, *args) -> Optional[float]:
    if any(v is None for v in (p, alpha, beta_param)):
        return None
    a_bound = float(args[0]) if len(args) > 0 and args[0] is not None else 0.0
    b_bound = float(args[1]) if len(args) > 1 and args[1] is not None else 1.0
    return beta_inv(float(p), float(alpha), float(beta_param), a_bound, b_bound)


def dax_poisson_dist(x, mean, cumulative) -> Optional[float]:
    if any(v is None for v in (x, mean, cumulative)):
        return None
    cum = _to_bool(cumulative)
    if cum:
        return poisson_cdf(float(x), float(mean))
    return poisson_pmf(float(x), float(mean))


def dax_expon_dist(x, lam, cumulative) -> Optional[float]:
    if any(v is None for v in (x, lam, cumulative)):
        return None
    cum = _to_bool(cumulative)
    if cum:
        return expon_cdf(float(x), float(lam))
    return expon_pdf(float(x), float(lam))


def dax_confidence_norm(alpha, std_dev, size) -> Optional[float]:
    return confidence_norm(alpha, std_dev, size)


def dax_confidence_t(alpha, std_dev, size) -> Optional[float]:
    return confidence_t(alpha, std_dev, size)


# ── Helpers ──────────────────────────────────────────────────────────

def _to_bool(val) -> bool:
    """Convert DAX TRUE/FALSE/1/0 to Python bool."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).upper().strip()
    return s in ("TRUE", "1", "YES")

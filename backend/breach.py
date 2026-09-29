"""Breach outflow hydrograph.

A parametric, time-progressive trapezoidal breach (the approach used by
NWS DAMBRK / HEC-RAS) coupled to a reservoir mass balance that uses the
official 2021 elevation-capacity curve of Machhu-2 (CWC/NHP survey).

    dV/dt = Q_in(t) - Q_breach(t)            (reservoir continuity)
    Q_breach = Cw*b*H^1.5 + Cs*z*H^2.5       (broad-crested weir, trapezoid)
    H = WSE - z_breach(t)

The breach bottom lowers linearly from the dam crest to the final bottom
elevation and the bottom width grows linearly to B over formation time tf.
Froehlich (2008) regressions give recommended B and tf.
"""
import numpy as np
from config import DAM

G = 9.81
CW = 1.70   # broad-crested weir coefficient (SI) for breach bottom width
CS = 1.35   # side-slope weir coefficient (SI)

_eac = np.array(DAM["eac_2021"])
ELEV, VOL = _eac[:, 0], _eac[:, 1] * 1e6  # m, m^3


def vol_at(h):
    return float(np.interp(h, ELEV, VOL, right=VOL[-1] + (h - ELEV[-1]) * 35.3e6))


def wse_at(v):
    if v > VOL[-1]:
        return ELEV[-1] + (v - VOL[-1]) / 35.3e6
    return float(np.interp(v, VOL, ELEV))


def froehlich_2008(wse, bottom, mode="overtopping"):
    """Recommended average breach width (m) and formation time (h)."""
    vw = vol_at(wse)
    hb = DAM["top_of_dam_m"] - bottom
    ko = 1.3 if mode == "overtopping" else 1.0
    b_avg = 0.27 * ko * vw ** 0.32 * hb ** 0.04
    tf = 63.2 * np.sqrt(vw / (G * hb ** 2)) / 3600.0
    # Froehlich (1995) peak outflow check
    hw = wse - bottom
    qp = 0.607 * vw ** 0.295 * hw ** 1.24
    return dict(b_avg=round(b_avg, 1), tf_h=round(tf, 2), qp_1995=round(qp),
                volume_mcm=round(vw / 1e6, 2), hb=round(hb, 2))


def hydrograph(wse0=57.3, breach_width=150.0, breach_bottom=42.0, tf_h=1.0,
               side_slope=1.0, inflow_peak=0.0, inflow_tp_h=6.0, t_end_h=12.0,
               dt=10.0):
    """Return times (s) and downstream discharge (m^3/s), plus diagnostics.

    inflow_peak > 0 gives a flood-induced failure: a triangular inflow
    hydrograph (peak at inflow_tp_h, base 3*tp) enters the reservoir; the
    spillway is assumed to pass the inflow downstream (gates fully open),
    so downstream flow = breach outflow + inflow. Breach starts at t=0.
    """
    crest = DAM["top_of_dam_m"]
    tf = max(tf_h * 3600.0, dt)
    n = int(t_end_h * 3600 / dt) + 1
    t = np.arange(n) * dt
    qb = np.zeros(n); qin = np.zeros(n); wse = np.zeros(n)
    v = vol_at(wse0); h = wse0
    for i, ti in enumerate(t):
        frac = min(ti / tf, 1.0)
        zb = crest - (crest - breach_bottom) * frac
        b = breach_width * frac
        head = max(h - zb, 0.0)
        q = CW * b * head ** 1.5 + CS * side_slope * head ** 2.5 if breach_width > 0 else 0.0
        if inflow_peak > 0:
            tp = inflow_tp_h * 3600
            qi = inflow_peak * (ti / tp if ti <= tp else max(0.0, (3 * tp - ti) / (2 * tp)))
        else:
            qi = 0.0
        q = min(q, v / dt)  # cannot release more than stored
        v = max(v - q * dt, 0.0)
        h = wse_at(v)
        qb[i], qin[i], wse[i] = q, qi, h
    qdown = qb + qin
    released = float(np.trapezoid(qb, t))
    return dict(t=t, q=qdown, q_breach=qb, q_in=qin, wse=wse,
                peak_q=float(qdown.max()), t_peak_h=float(t[qdown.argmax()] / 3600),
                released_mcm=released / 1e6, v0_mcm=vol_at(wse0) / 1e6,
                final_wse=float(wse[-1]))


if __name__ == "__main__":
    print("Froehlich 2008 @FRL:", froehlich_2008(57.3, 42.0))
    for B in (100, 250, 500, 1100):
        r = hydrograph(breach_width=B, tf_h=1.0)
        print(f"B={B:5d} m  Qpeak={r['peak_q']:8.0f} m3/s at {r['t_peak_h']:.2f} h  "
              f"released={r['released_mcm']:.1f}/{r['v0_mcm']:.1f} Mm3  final WSE={r['final_wse']:.2f}")

"""Pre-defined dam-break scenarios for Machhu-2 (all inputs are assumptions,
stated explicitly; outputs come from the model)."""

SCENARIOS = [
    dict(id="S0_release", label="Release - controlled gate release, Aug-2024 type (no breach)",
         wse0=57.30, breach_width=0, breach_bottom=42.0, tf_h=1.0, inflow_peak=3400.0,
         inflow_tp_h=6.0, manning=0.06, t_end_h=10.0,
         basis="No dam failure. Spillway release hydrograph peaking at 3,400 m3/s (~1.2 lakh cusecs "
               "reported released from Machhu dam on 28 Aug 2024). Validate against Sentinel-1 flood map "
               "from the GEE module."),
    dict(id="S1_moderate", label="Moderate - piping failure at FRL (sunny day)",
         wse0=57.30, breach_width=140, breach_bottom=42.0, tf_h=2.5, inflow_peak=0.0,
         manning=0.06, t_end_h=10.0,
         basis="Reservoir at FRL 57.30 m (GWRD). Breach width 140 m and formation time "
               "2.5 h from Froehlich (2008) regressions for 92 Mm3 / 21.7 m breach height. "
               "No flood inflow."),
    dict(id="S2_severe", label="Severe - overtopping failure at HFL during a flood",
         wse0=59.20, breach_width=400, breach_bottom=42.0, tf_h=1.0, inflow_peak=8000.0,
         inflow_tp_h=4.0, manning=0.06, t_end_h=10.0,
         basis="Reservoir at HFL 59.20 m (NHP report). Breach ~3x Froehlich average "
               "(upper range of regression scatter), 1 h formation. Flood inflow 8,000 m3/s "
               "peak passed through spillway (assumed)."),
    dict(id="S3_extreme", label="Extreme - 1979-type analogue (wide embankment breach)",
         wse0=59.20, breach_width=1100, breach_bottom=45.0, tf_h=0.75, inflow_peak=16300.0,
         inflow_tp_h=3.0, manning=0.06, t_end_h=10.0,
         basis="Breach width 1,100 m ~ 762 m + 365 m embankment lengths lost in 1979; inflow "
               "peak 16,300 m3/s ~ observed 1979 flow. Applied to the present-day reservoir; "
               "an analogue, not a hindcast of 1979 terrain."),
]
BY_ID = {s["id"]: s for s in SCENARIOS}

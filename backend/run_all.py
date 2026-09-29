"""Batch: run the 3 pre-defined scenarios (hi-res) + a Monte-Carlo style
uncertainty ensemble, then build the probability-of-inundation map."""
import json
import sys
import numpy as np
from scipy.stats import qmc

from config import OUTPUTS, WET_THRESHOLD
from scenarios import SCENARIOS
from simulation import run, read_asc
from impact import analyse, Grid, DEPTH_RAMP
from breach import froehlich_2008


def scenarios(res):
    for s in SCENARIOS:
        rdir, info = run(s, res=res, name=s["id"])
        m = analyse(rdir, res, s["id"], s["label"])
        print(f"[{s['id']}] {res} m runtime {info['runtime_s']} s  area {m['flood']['area_km2']} km2  "
              f"bldg {m['buildings']['total']}", flush=True)


def ensemble(n=16, res=60, seed=7):
    """Latin-hypercube sample of uncertain breach & friction parameters."""
    f = froehlich_2008(57.3, 42.0)
    sampler = qmc.LatinHypercube(d=4, seed=seed)
    u = sampler.random(n)
    # ranges: breach width 0.5-2.5 x Froehlich avg; tf 0.5-3 h; Manning 0.04-0.08; WSE 55.5-59.2
    B = f["b_avg"] * (0.5 + 2.0 * u[:, 0])
    tf = 0.5 + 2.5 * u[:, 1]
    nman = 0.04 + 0.04 * u[:, 2]
    wse = 55.5 + 3.7 * u[:, 3]
    grid = Grid(res)
    count = np.zeros(grid.shape)
    members = []
    for i in range(n):
        s = dict(id=f"E{i:02d}", wse0=round(float(wse[i]), 2), breach_width=round(float(B[i])),
                 breach_bottom=42.0, tf_h=round(float(tf[i]), 2), manning=round(float(nman[i]), 3),
                 inflow_peak=0.0, t_end_h=10.0, saveint_s=36000)
        rdir, info = run(s, res=res, name=f"ens_{i:02d}")
        d, _ = read_asc(rdir / "out" / "res.max"); d[grid.mask] = 0
        wet = d > WET_THRESHOLD
        count += wet
        members.append(dict(**s, peak_q=info["peak_q"], area_km2=round(float(wet.sum() * res * res / 1e6), 2)))
        print(f"[ens {i}] B={s['breach_width']} tf={s['tf_h']} n={s['manning']} wse={s['wse0']} "
              f"Qp={info['peak_q']} area={members[-1]['area_km2']}", flush=True)
    prob = count / n
    out = OUTPUTS / "uncertainty"; out.mkdir(parents=True, exist_ok=True)
    grid.save_tif(np.where(prob > 0, prob, np.nan), out / "inundation_probability.tif")
    ramp_in = np.where(prob > 0, prob, 0)
    rgba = np.zeros(prob.shape + (4,), np.uint8)
    cols = np.array([(254, 240, 217), (253, 204, 138), (252, 141, 89), (227, 74, 51), (179, 0, 0)])
    k = np.clip((ramp_in * 5).astype(int), 0, 4)
    rgba[..., :3] = cols[k]; rgba[..., 3] = np.where(prob > 0, 210, 0)
    bounds = grid.web_png(rgba, out / "probability.png")
    cell = res * res / 1e6
    bxy = np.load(OUTPUTS.parent / "data" / "exposure" / "buildings_xy.npy")
    r, c, ok = grid.rc(bxy[:, 0], bxy[:, 1])
    bp = np.zeros(len(bxy)); bp[ok] = prob[r[ok], c[ok]]
    pop = np.load(OUTPUTS.parent / "data" / "exposure" / f"pop_{res}m.npy")
    summ = dict(n=n, res=res, froehlich=f, members=members, bounds=bounds, png="probability.png",
                area_any_km2=round(float((prob > 0).sum() * cell), 2),
                area_p50_km2=round(float((prob >= 0.5).sum() * cell), 2),
                area_p90_km2=round(float((prob >= 0.9).sum() * cell), 2),
                buildings_p50=int((bp >= 0.5).sum()), buildings_any=int((bp > 0).sum()),
                buildings_p90=int((bp >= 0.9).sum()),
                people_p50=int(pop[prob >= 0.5].sum()), people_any=int(pop[prob > 0].sum()),
                ranges=dict(breach_width=[round(B.min()), round(B.max())],
                            tf_h=[round(tf.min(), 2), round(tf.max(), 2)],
                            manning=[round(nman.min(), 3), round(nman.max(), 3)],
                            wse0=[round(wse.min(), 2), round(wse.max(), 2)]))
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=float))
    print("[ensemble] done", json.dumps({k: v for k, v in summ.items() if k != "members"}), flush=True)


if __name__ == "__main__":
    what = sys.argv[1:] or ["scenarios", "ensemble"]
    if "scenarios60" in what:
        scenarios(60)
    if "scenarios" in what:
        scenarios(30)
    if "ensemble" in what:
        ensemble()

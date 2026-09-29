"""FloodShield SPH module - 2D weakly-compressible Smoothed Particle Hydrodynamics.

Why: PS SIH26161 names Smoothed Particle Hydrodynamics. SPH is used here for the
*near-field* breach physics (violent, free-surface, vertical-plane flow) where
depth-averaged shallow-water models are least accurate; LISFLOOD-FP handles the
*far-field* 20 km valley routing, where SPH would be computationally prohibitive.

Solver: WCSPH (Monaghan 1994) - Wendland C2 kernel, Tait equation of state,
Monaghan artificial viscosity, delta-SPH density diffusion (Molteni & Colagrossi 2009),
dynamic boundary particles, symplectic Euler time integration.

Runs:
  python sph.py validate   -> Martin & Moyce (1952) collapsing water column benchmark
  python sph.py machhu     -> vertical section through the Machhu-2 breach (first seconds)
"""
import json
import sys
import time
import numpy as np
from scipy.spatial import cKDTree

G = 9.81
RHO0 = 1000.0


class SPH:
    def __init__(self, fluid_xy, bound_xy, dx, h_ref, c0=None, alpha=0.05, delta=0.1):
        self.nf = len(fluid_xy)
        self.x = np.vstack([fluid_xy, bound_xy]).astype(float)
        self.v = np.zeros_like(self.x)
        self.is_f = np.r_[np.ones(self.nf, bool), np.zeros(len(bound_xy), bool)]
        self.dx = dx
        self.h = 1.3 * dx
        self.m = RHO0 * dx * dx
        self.c0 = c0 or 10.0 * np.sqrt(G * h_ref)
        self.B = self.c0 ** 2 * RHO0 / 7.0
        self.alpha, self.delta = alpha, delta
        # hydrostatic initial density for fluid (reduces startup shock)
        ymax = fluid_xy[:, 1].max() + dx / 2
        self.rho = np.full(len(self.x), RHO0)
        p_h = RHO0 * G * (ymax - fluid_xy[:, 1])
        self.rho[:self.nf] = RHO0 * (1 + p_h / self.B) ** (1 / 7)
        self.ad = 7.0 / (4 * np.pi * self.h ** 2)
        self.t = 0.0

    def pressure(self):
        return self.B * ((self.rho / RHO0) ** 7 - 1.0)

    def step(self, dt):
        x, v, rho, h = self.x, self.v, self.rho, self.h
        tree = cKDTree(x)
        pairs = tree.query_pairs(2 * h, output_type="ndarray")
        i, j = pairs[:, 0], pairs[:, 1]
        keep = self.is_f[i] | self.is_f[j]
        i, j = i[keep], j[keep]
        rij = x[i] - x[j]
        r = np.sqrt((rij ** 2).sum(1)) + 1e-12
        q = r / h
        # Wendland C2 gradient: dW/dr = ad * (-5 q (1-q/2)^3) / h
        dwdr = self.ad * (-5.0 * q * (1 - 0.5 * q) ** 3) / h
        gw = (dwdr / r)[:, None] * rij                  # grad_i W_ij
        vij = v[i] - v[j]
        p = np.maximum(self.pressure(), 0.0)  # clip tensile pressure at the free surface
        # continuity + delta-SPH density diffusion (Molteni & Colagrossi 2009)
        vdotg = (vij * gw).sum(1)
        drho = np.zeros(len(x))
        phi = (self.delta * h * self.c0 * 2 * (rho[j] - rho[i]) * (-(rij * gw).sum(1))
               / (r ** 2 + 0.01 * h ** 2))
        np.add.at(drho, i, self.m * vdotg + phi * self.m / rho[j])
        np.add.at(drho, j, self.m * vdotg - phi * self.m / rho[i])
        # momentum with artificial viscosity
        vr = (vij * rij).sum(1)
        mu = h * vr / (r ** 2 + 0.01 * h ** 2)
        rho_bar = 0.5 * (rho[i] + rho[j])
        pi_ij = np.where(vr < 0, -self.alpha * self.c0 * mu / rho_bar, 0.0)
        coef = (p[i] / rho[i] ** 2 + p[j] / rho[j] ** 2 + pi_ij)[:, None] * gw
        acc = np.zeros_like(x)
        np.add.at(acc, i, -self.m * coef)
        np.add.at(acc, j, self.m * coef)
        acc[:, 1] -= G
        f = self.is_f
        # symplectic Euler: velocities first, then positions
        v[f] += acc[f] * dt
        x[f] += v[f] * dt
        rho += drho * dt
        rho[~f] = np.maximum(rho[~f], RHO0)
        self.t += dt

    def dt_cfl(self):
        vmax = np.sqrt((self.v[self.is_f] ** 2).sum(1)).max()
        return 0.2 * self.h / (self.c0 + vmax)


def box_walls(x0, x1, y0, y1, dx, layers=3, left=True, right=True):
    pts = []
    for k in range(layers):
        off = (k + 0.5) * dx
        xs = np.arange(x0 - layers * dx + dx / 2, x1 + layers * dx, dx)
        pts += [(xx, y0 - off) for xx in xs]
        ys = np.arange(y0 + dx / 2, y1, dx)
        if left:
            pts += [(x0 - off, yy) for yy in ys]
        if right:
            pts += [(x1 + off, yy) for yy in ys]
    return np.array(pts)


# Martin & Moyce (1952), Phil. Trans. R. Soc. A 244, Table 1 (square column, n^2 = 1,
# a = 2.25 in, mean of repeat runs; digitised from the scanned table). T = t (g/a)^0.5, Z = x/a
MARTIN_MOYCE = [(1.22, 0.62), (1.44, 0.80), (1.67, 0.97), (1.89, 1.14), (2.11, 1.29),
                (2.33, 1.45), (2.56, 1.61), (2.78, 1.76), (3.00, 1.94), (3.22, 2.07),
                (3.44, 2.24), (3.67, 2.40), (3.89, 2.54)]


def validate(a=0.1, nx=40, t_end_T=2.8, out_dir=None):
    dx = a / nx
    xs = np.arange(dx / 2, a, dx)
    fluid = np.array([(xx, yy) for xx in xs for yy in xs])
    L = 5.0 * a
    walls = box_walls(0, L, 0, 1.5 * a, dx)
    s = SPH(fluid, walls, dx, a, alpha=0.05)
    T_scale = np.sqrt(a / G)
    front, frames = [], []
    t_end = t_end_T * T_scale
    snap_every = t_end / 6
    next_snap = 0.0
    t0 = time.time()
    while s.t < t_end:
        s.step(s.dt_cfl())
        fx = s.x[:s.nf]
        near_bed = fx[:, 1] < 3 * dx
        front.append((s.t / T_scale, np.percentile(fx[near_bed, 0], 99.8) / a if near_bed.any() else 1.0))
        if s.t >= next_snap:
            spd = np.sqrt((s.v[:s.nf] ** 2).sum(1))
            frames.append(dict(T=round(s.t / T_scale, 2), x=(fx[:, 0] / a).round(3).tolist(),
                               y=(fx[:, 1] / a).round(3).tolist(), speed=(spd / np.sqrt(G * a)).round(2).tolist()))
            next_snap += snap_every
    front = np.array(front)
    # Martin & Moyce normalised T so that T = 0.80 at Z = 1.44 (table footnote) to remove the
    # gate-opening delay; apply the same shift to the SPH time axis.
    t144 = float(np.interp(1.44, front[:, 1], front[:, 0]))
    front[:, 0] += 0.80 - t144
    Zs = np.interp([t for _, t in MARTIN_MOYCE], front[:, 0], front[:, 1])
    Ze = np.array([z for z, _ in MARTIN_MOYCE])
    rmse = float(np.sqrt(np.mean((Zs - Ze) ** 2)))
    res = dict(particles=int(s.nf), boundary=int(len(walls)), dx=dx, steps=len(front),
               runtime_s=round(time.time() - t0, 1), rmse_Z=round(rmse, 3), time_shift_T=round(0.80 - t144, 3),
               mean_abs_pct=round(float(np.mean(np.abs(Zs - Ze) / Ze) * 100), 1),
               sph=[[round(t, 3), round(z, 3)] for t, z in front[::10]],
               experiment=MARTIN_MOYCE, frames=frames)
    return res


def machhu_section(dx=1.0, t_end=20.0):
    """Vertical 2D section along the breach axis: reservoir at FRL (57.30 m) behind the
    breached section, bed at breach bottom 42 m, downstream bed from the DEM profile.
    Instantaneous full-depth removal of the breach section (worst case)."""
    bed = 42.0
    H = 57.30 - bed                       # 15.3 m of water
    Lr = 120.0                            # reservoir length represented (near field)
    Ld = 260.0                            # downstream reach length
    xs = np.arange(-Lr + dx / 2, 0, dx)
    ys = np.arange(dx / 2, H, dx)
    fluid = np.array([(xx, yy) for xx in xs for yy in ys])
    walls = box_walls(-Lr, Ld, 0, H + 10, dx, left=True, right=False)
    s = SPH(fluid, walls, dx, H, alpha=0.08)
    front, frames = [], []
    snap_every, next_snap = t_end / 8, 0.0
    t0 = time.time()
    while s.t < t_end:
        s.step(s.dt_cfl())
        fx = s.x[:s.nf]
        inside = fx[:, 0] < Ld
        s.x[:s.nf][~inside] = [Ld + 50, -50]   # particles leaving the domain are parked
        s.v[:s.nf][~inside] = 0
        fr = np.percentile(fx[inside & (fx[:, 1] < 2 * dx) & (fx[:, 1] > -1), 0], 99.8)
        front.append((s.t, fr))
        if s.t >= next_snap:
            spd = np.sqrt((s.v[:s.nf] ** 2).sum(1))
            frames.append(dict(t=round(s.t, 1), x=fx[inside, 0].round(2).tolist(),
                               y=fx[inside, 1].round(2).tolist(), speed=spd[inside].round(2).tolist()))
            next_snap += snap_every
    front = np.array(front)
    # unit discharge through the breach section x=0 from the particle field at end
    ritter_front = 2 * np.sqrt(G * H)
    ritter_q = (8 / 27) * np.sqrt(G) * H ** 1.5   # Ritter (1892) unit discharge at the dam site
    sel = (front[:, 0] >= 2.0) & (front[:, 0] <= 10.0)   # before the front leaves the domain
    sph_speed = float(np.polyfit(front[sel, 0], front[sel, 1], 1)[0])
    return dict(H=H, particles=int(s.nf), dx=dx, runtime_s=round(time.time() - t0, 1),
                front=[[round(t, 2), round(z, 1)] for t, z in front[::20]],
                sph_front_speed_ms=round(sph_speed, 2), ritter_front_speed_ms=round(ritter_front, 2),
                ritter_unit_q_m2s=round(ritter_q, 1), frames=frames)


if __name__ == "__main__":
    from config import OUTPUTS
    out = OUTPUTS / "sph"; out.mkdir(parents=True, exist_ok=True)
    what = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if what == "validate":
        r = validate()
        (out / "validation.json").write_text(json.dumps(r))
        print({k: v for k, v in r.items() if k not in ("sph", "frames", "experiment")})
    else:
        r = machhu_section()
        (out / "machhu_section.json").write_text(json.dumps(r))
        print({k: v for k, v in r.items() if k not in ("front", "frames")})

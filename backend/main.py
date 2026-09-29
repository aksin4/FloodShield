"""FloodShield API (FastAPI).

Run:  cd backend && uvicorn main:app --host 0.0.0.0 --port 8000
"""
import json
import threading
import time
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import OUTPUTS, DATA, DAM, FRONTEND
from breach import hydrograph, froehlich_2008
from scenarios import SCENARIOS
from simulation import run
from impact import analyse

app = FastAPI(title="FloodShield API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
(OUTPUTS / "scenarios").mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")
app.mount("/exposure", StaticFiles(directory=DATA / "exposure"), name="exposure")

JOBS: dict = {}
LOCK = threading.Lock()


class BreachParams(BaseModel):
    wse0: float = Field(57.3, ge=47.3, le=63.7, description="Reservoir level at breach start (m MSL)")
    breach_width: float = Field(140, ge=0, le=1500)
    breach_bottom: float = Field(42.0, ge=39.7, le=55)
    tf_h: float = Field(2.5, ge=0.1, le=8)
    inflow_peak: float = Field(0, ge=0, le=30000)
    inflow_tp_h: float = Field(4.0, ge=0.5, le=24)
    manning: float = Field(0.06, ge=0.02, le=0.15)
    t_end_h: float = Field(8.0, ge=2, le=12)
    label: str = "Custom scenario"


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/dam")
def dam():
    return dict(dam={k: v for k, v in DAM.items()},
                froehlich_frl=froehlich_2008(DAM["frl_m"], 42.0),
                froehlich_hfl=froehlich_2008(DAM["hfl_m"], 42.0, "overtopping"))


@app.post("/api/breach/preview")
def breach_preview(p: BreachParams):
    h = hydrograph(p.wse0, p.breach_width, p.breach_bottom, p.tf_h, 1.0, p.inflow_peak,
                   p.inflow_tp_h, p.t_end_h)
    k = 18  # every 3 min
    return dict(t_h=(h["t"][::k] / 3600).round(3).tolist(), q=h["q"][::k].round(1).tolist(),
                q_breach=h["q_breach"][::k].round(1).tolist(), wse=h["wse"][::k].round(2).tolist(),
                peak_q=round(h["peak_q"]), t_peak_h=round(h["t_peak_h"], 2),
                released_mcm=round(h["released_mcm"], 2), v0_mcm=round(h["v0_mcm"], 2),
                froehlich=froehlich_2008(p.wse0, p.breach_bottom))


def _light(s):
    return {k: s[k] for k in ("id", "label", "res", "flood", "buildings", "roads", "railway_km", "people")} | {
        "places_n": len(s["places"]), "facilities_n": len(s["facilities"]),
        "peak_q": s["model"]["peak_q"], "scenario": s["model"]["scenario"]}


@app.get("/api/scenarios")
def scenarios():
    out = []
    for sc in SCENARIOS:
        f = OUTPUTS / "scenarios" / sc["id"] / "summary.json"
        item = dict(id=sc["id"], label=sc["label"], basis=sc["basis"], params=sc, ready=f.exists())
        if f.exists():
            item["summary"] = _light(json.loads(f.read_text()))
        out.append(item)
    return out


@app.get("/api/scenario/{sid}")
def scenario(sid: str):
    f = OUTPUTS / "scenarios" / sid / "summary.json"
    if not f.exists():
        raise HTTPException(404, "Scenario not computed yet")
    return json.loads(f.read_text())


@app.get("/api/uncertainty")
def uncertainty():
    f = OUTPUTS / "uncertainty" / "summary.json"
    if not f.exists():
        raise HTTPException(404, "Ensemble not computed yet")
    return json.loads(f.read_text())


@app.get("/api/verification")
def verification():
    f = OUTPUTS / "verification.json"
    if not f.exists():
        raise HTTPException(404, "not computed")
    return json.loads(f.read_text())


@app.get("/api/sph")
def sph():
    out = {}
    for k in ("validation", "machhu_section"):
        f = OUTPUTS / "sph" / f"{k}.json"
        if f.exists():
            out[k] = json.loads(f.read_text())
    return out


@app.get("/api/sar")
def sar():
    f = OUTPUTS / "sar" / "summary.json"
    if not f.exists():
        raise HTTPException(404, "SAR layer not computed")
    return json.loads(f.read_text())


def _worker(jid, p: BreachParams):
    JOBS[jid]["status"] = "queued"
    with LOCK:  # one simulation at a time on this machine
        JOBS[jid].update(status="running", started=time.time())
        try:
            sc = p.model_dump() | dict(id=jid, saveint_s=1800)
            rdir, info = run(sc, res=60, name=jid)
            JOBS[jid]["status"] = "post-processing"
            analyse(rdir, 60, jid, p.label)
            JOBS[jid].update(status="done", runtime_s=info["runtime_s"])
        except Exception as e:  # noqa
            JOBS[jid].update(status="error", error=str(e)[:500])


@app.post("/api/simulate")
def simulate(p: BreachParams):
    jid = "C" + uuid.uuid4().hex[:7]
    JOBS[jid] = dict(id=jid, status="queued", created=time.time(), params=p.model_dump())
    threading.Thread(target=_worker, args=(jid, p), daemon=True).start()
    return JOBS[jid]


@app.get("/api/job/{jid}")
def job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "unknown job")
    j = dict(JOBS[jid])
    if j.get("started") and j["status"] == "running":
        j["elapsed_s"] = round(time.time() - j["started"], 1)
    return j


if FRONTEND.exists():  # serve the dashboard at / (after API routes so they take priority)
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")

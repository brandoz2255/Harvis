"""Harvis CAD engine — an isolated build123d sidecar (Stage 2).

Runs the OCP/OCCT geometry kernel in its OWN container so its pinned
build123d==0.9.1 + cadquery-ocp stack never touches the backend's numpy<2 /
torch environment. The backend calls this over the internal network with a
recipe name + params; only VETTED named recipes run (no arbitrary code). It
returns a real STL/STEP (base64) + geometry metadata.

Internal network only — no host port, no auth secret needed beyond being
unreachable from outside the Docker network. Stateless.
"""
from __future__ import annotations

import base64
import os
import shutil
import tempfile

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import recipes

app = FastAPI(title="Harvis CAD engine")


class ExecReq(BaseModel):
    recipe: str
    params: dict = {}
    step: bool = True


@app.get("/health")
def health():
    return {"ok": True, "recipes": list(recipes.RECIPES.keys())}


@app.post("/cad/execute")
def execute(req: ExecReq):
    if req.recipe not in recipes.RECIPES:
        raise HTTPException(status_code=400, detail=f"unknown recipe: {req.recipe}")
    workdir = tempfile.mkdtemp(prefix="cad_")
    stl_path = os.path.join(workdir, "part.stl")
    step_path = os.path.join(workdir, "part.step") if req.step else None
    try:
        meta = recipes.run(req.recipe, req.params or {}, stl_path, step_path)
        with open(stl_path, "rb") as fh:
            stl_b64 = base64.b64encode(fh.read()).decode("ascii")
        step_b64 = None
        if step_path and os.path.exists(step_path):
            with open(step_path, "rb") as fh:
                step_b64 = base64.b64encode(fh.read()).decode("ascii")
        return {"ok": True, "meta": meta, "stl_b64": stl_b64, "step_b64": step_b64}
    except HTTPException:
        raise
    except Exception as e:  # geometry failure — honest 500, no partial pretend
        raise HTTPException(status_code=500, detail=f"cad execution failed: {e}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

"""Minimal local .env loading; no shell execution or interpolation."""
import os

from .corpus import ROOT


def load_local_env(path=None):
    path=path or ROOT/".env"
    if not path.exists():
        return
    allowed={"OPENAI_API_KEY","OPENAI_MODEL","LLM_ENABLED","DEMO_ACCESS_TOKEN","DATABASE_URL",
        "LLM_LIFETIME_BUDGET_USD","LLM_DAILY_BUDGET_USD","PUBLIC_DEMO"}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name,value=line.split("=",1)
        name,value=name.strip(),value.strip()
        if name in allowed:
            os.environ.setdefault(name,value.strip("\"'"))

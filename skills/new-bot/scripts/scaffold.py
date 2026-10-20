#!/usr/bin/env python3
"""Create a new UtilBots bot repo from the template.

    python scaffold.py --slug mediabot --name MediaBot --emoji 🎬 --tagline "..." --out ~/code/mediabot.utilbots.com

Picks the next free port from bots.json (3500+) unless --port is given, and records the bot there."""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # utilbots-core checkout
TEMPLATE = Path(__file__).resolve().parents[1] / "template"
REGISTRY = ROOT / "bots.json"
FIRST_PORT = 3500


def core_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


def next_port(apps: list[dict]) -> int:
    used = {a["port"] for a in apps}
    port = FIRST_PORT
    while port in used:
        port += 1
    return port


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="lowercase, e.g. mediabot (becomes mediabot.utilbots.com)")
    ap.add_argument("--name", required=True, help="display name, e.g. MediaBot")
    ap.add_argument("--emoji", required=True)
    ap.add_argument("--tagline", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--port", type=int)
    ap.add_argument("--core-ref", help="git ref of utilbots-core the bot pins (default v<core version>)")
    ap.add_argument("--workflow-ref", default="v0", help="ref of the reusable workflow (default v0)")
    ap.add_argument("--core-path", help="install utilbots-core from this local path instead (CI/self-test)")
    ap.add_argument("--no-registry", action="store_true", help="don't record the bot in bots.json")
    a = ap.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9-]{1,38}[a-z0-9]", a.slug):
        sys.exit("slug must be 3-40 chars of a-z, 0-9 and hyphens")
    if not a.slug.endswith("bot"):
        print(f"warning: bots are named <servicetype>bot; '{a.slug}' doesn't end in 'bot'", file=sys.stderr)
    cls = re.sub(r"[^A-Za-z0-9]", "", a.name)
    if not cls or not cls[0].isalpha():
        sys.exit("name must start with a letter")

    registry = json.loads(REGISTRY.read_text())
    apps = registry["apps"]
    existing = next((x for x in apps if x["slug"] == a.slug), None)
    port = a.port or (existing or {}).get("port") or next_port(apps)
    clash = next((x for x in apps if x["port"] == port and x["slug"] != a.slug), None)
    if clash:
        sys.exit(f"port {port} is already used by {clash['slug']}")

    out: Path = a.out.expanduser().resolve()
    if out.exists() and any(p.name != ".git" for p in out.iterdir()):
        sys.exit(f"{out} is not empty (only a .git folder is allowed)")

    subs = {
        "__SLUG__": a.slug, "__SNAKE__": a.slug.replace("-", "_"), "__NAME__": a.name, "__CLASS__": cls,
        "__EMOJI__": a.emoji, "__TAGLINE__": a.tagline.replace('"', "'"), "__PORT__": str(port),
        "__CORE_REF__": a.core_ref or f"v{core_version()}", "__WORKFLOW_REF__": a.workflow_ref,
    }
    for src in TEMPLATE.rglob("*"):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        dest = out / src.relative_to(TEMPLATE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        for k, v in subs.items():
            text = text.replace(k, v)
        dest.write_text(text)
        shutil.copymode(src, dest)
    if a.core_path:
        req = out / "requirements.txt"
        req.write_text(re.sub(r"^utilbots-core @ .*$", f"utilbots-core @ file://{Path(a.core_path).resolve()}",
                              req.read_text(), flags=re.M))

    if not a.no_registry and not existing:
        apps.append({"slug": a.slug, "kind": "bot", "repo": f"UnheardOTP/{a.slug}.utilbots.com", "port": port,
                     "url": f"https://{a.slug}.utilbots.com"})
        REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"slug": a.slug, "port": port, "out": str(out), "core_ref": subs["__CORE_REF__"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

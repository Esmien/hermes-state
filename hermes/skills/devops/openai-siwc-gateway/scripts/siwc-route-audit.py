#!/usr/bin/env python3
"""Аудит маршрутов LiteLLM: у каких групп плановая нога и есть ли рядом не-плановая.

Только чтение. Секреты не печатает: имя группы, order, blocked, model, api_base, credential.
Запуск: python3 scripts/siwc-route-audit.py [http://127.0.0.1:4000]
"""
import json
import os
import re
import sys
import urllib.request

ENV_PATHS = (
    "/home/ai_service/ai-stack/ai/.env",
    "/home/ai_service/ai-stack/ai/litellm/.env",
)


def master_key():
    key = os.environ.get("LITELLM_MASTER_KEY")
    if key:
        return key
    for path in ENV_PATHS:
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                m = re.match(r"\s*LITELLM_MASTER_KEY\s*=\s*(.+)", line)
                if m:
                    return m.group(1).strip().strip("'\"")
    return None


def kind(p):
    base = str(p.get("api_base") or "")
    model = str(p.get("model") or "")
    cred = str(p.get("litellm_credential_name") or "")
    if "4010" in base:
        return "bridge(plan)"
    if model.startswith("chatgpt/"):
        return "grey(plan)"
    if model.startswith("openrouter/") or "Openrouter" in cred:
        return "openrouter"
    if "OpenCode" in cred or model.startswith("opencode/"):
        return "opencode"
    return "other"


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4000"
    key = master_key()
    if not key:
        print("LITELLM_MASTER_KEY не найден (env или " + ", ".join(ENV_PATHS) + ")")
        return 2

    req = urllib.request.Request(
        base_url.rstrip("/") + "/model/info",
        headers={"Authorization": "Bearer " + key},
    )
    data = json.load(urllib.request.urlopen(req, timeout=30)).get("data", [])

    groups = {}
    for item in data:
        params = item.get("litellm_params") or {}
        info = item.get("model_info") or {}
        groups.setdefault(str(item.get("model_name")), []).append(
            {
                "order": params.get("order"),
                "blocked": bool(info.get("blocked")),
                "model": params.get("model"),
                "base": params.get("api_base"),
                "cred": params.get("litellm_credential_name"),
                "kind": kind(params),
            }
        )

    plan_only = []
    for name in sorted(groups):
        legs = sorted(groups[name], key=lambda l: (l["order"] is None, l["order"] or 0))
        if not any(l["kind"] == "bridge(plan)" for l in legs):
            continue
        print("\n" + name)
        for l in legs:
            print(
                "   order={:>4} blocked={:<5} {:<13} model={} base={} cred={}".format(
                    str(l["order"]), str(l["blocked"]), l["kind"],
                    l["model"] or "-", l["base"] or "-", l["cred"] or "-",
                )
            )
        live = [l for l in legs if not l["blocked"]]
        if not any(l["kind"] != "bridge(plan)" and l["kind"] != "grey(plan)" for l in live):
            plan_only.append(name)

    print("\nГруппы, где все живые ноги плановые: " + (", ".join(plan_only) if plan_only else "нет"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

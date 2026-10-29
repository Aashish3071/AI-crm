"""Score the configured AI model against the builder's evaluation set.

    OPENROUTER_API_KEY=... AI_MODEL=... python3 tools/run_builder_evals.py

Each request in tests/builder_evals.json is sent with a new company's configuration, exactly as
Customize with AI sends it. A case passes when every operation the model proposes is valid
and its operations cover the expected ones: the same operation on the same record type, of
the same field type or stage kind. Requests that should produce nothing pass only when the
model proposes nothing. Runs on throwaway storage; nothing is saved.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crm_test_isolation  # noqa: E402,F401  (throwaway storage)
import crm_ai  # noqa: E402
import crm_builder  # noqa: E402
import pipecat_server as server  # noqa: E402
from crm_routes import builder  # noqa: E402


def shape(op):
    p = op.get("params") or {}
    return (op.get("op"), p.get("object", "lead") if "field" in str(op.get("op")) or op.get("op") == "add_choice" else "",
            p.get("type") or p.get("category") or "")


async def main() -> int:
    reason = crm_ai.not_configured_reason()
    if reason:
        print(reason)
        return 2
    db = server._empty_company_db()
    config, checker = builder._config(db), builder._rule_checker(db)
    system = crm_builder.prompt(config, builder._vocabulary(db))
    cases = json.loads((ROOT / "tests" / "builder_evals.json").read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        answer = await crm_ai.complete("evals", [{"role": "system", "content": system},
                                                 {"role": "user", "content": case["request"]}], title="InsureCRM Builder evals",
                                       max_tokens=1500)
        try:
            reply = crm_builder.parse_reply(answer)
            ops = reply["operations"]
            _, results = crm_builder.check(config, ops, checker) if ops else (None, [])
            valid = all(r["ok"] for r in results)
            covered = {shape(o) for o in ops} >= {shape(o) for o in case["expected"]}
            ok = (not ops) if not case["expected"] else (valid and covered)
            detail = "" if ok else f" — proposed {[shape(o) for o in ops]}" + (
                "" if valid else f"; invalid: {[r['error'] for r in results if not r['ok']]}")
        except crm_builder.BuilderError as exc:
            ok, detail = False, f" — {exc}" if answer else f" — {crm_ai.last_error('evals')}"
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['request']}{detail}")
    print(f"\n{passed}/{len(cases)} passed with {crm_ai.model()}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

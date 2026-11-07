"""Summarize only completed benchmark evidence; missing cases remain blocked."""
import argparse
import collections
import json
import pathlib
import sqlite3
import statistics

from scripts.validation.local_ollama_benchmark import CASES, MODELS

def usage(row, sandbox):
    path = sandbox / row["model"].replace(":", "-") / f"{row['case']}-{row['repeat']}" / "data/local-coding-agent.sqlite3"
    if not path.is_file():
        return
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        calls = [json.loads(r[0]) for r in db.execute(
            "select metadata_json from runtime_events where kind='response.completed'")]
        known = [r for r in calls if not r.get("estimated") and all(
            isinstance(r.get(k), int) for k in ("input_tokens", "output_tokens"))]
        row["tokens"] = {k: sum(r[k] for r in known) for k in ("input_tokens", "output_tokens")} if known else None
        row["token_samples"] = len(known)
        row["completed_model_calls"] = len(calls)
        records = [r[0] for r in db.execute("select data_json from agent_execution_runs")]
        runs = [json.loads(record) for record in records]
        if row["case"] == "F-desktop" and row["status"] == "FAIL" and any(
                "DESKTOP_FOCUS_FAILED" in record for record in records):
            row["failure"] = "ENVIRONMENT_FAILURE"
            row["focus_error"] = "DESKTOP_FOCUS_FAILED"
        if runs:
            row["model_calls"] = sum(r.get("calls", 0) for r in runs)
            row["runtime_tool_calls"] = sum(r.get("tool_calls", 0) for r in runs)
            row["repairs"] = sum(r.get("unified", {}).get("repairs", 0) for r in runs)
            row["protocol_repairs"] = sum(r.get("tool_protocol_repairs", 0) for r in runs)

def normalize_failure(row):
    code = row.get("code") or ""
    if row.get("failure") == "AGENT_FAILURE":
        if "TIMEOUT" in code:
            row["failure"] = "TIMEOUT"
        elif code.startswith(("MODEL_", "OLLAMA_")):
            row["failure"] = "MODEL_FAILURE"

def load_source(path):
    if not path:
        return []
    root = pathlib.Path(path.with_name("scratch-path.txt").read_text(encoding="utf-8").strip())
    rows = json.loads(path.read_text(encoding="utf-8"))["results"]
    for row in rows:
        normalize_failure(row)
        usage(row, root)
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument("raw", type=pathlib.Path)
    p.add_argument("sandbox", type=pathlib.Path)
    p.add_argument("output", type=pathlib.Path)
    p.add_argument("--gui", type=pathlib.Path, action="append", default=[])
    p.add_argument("--gui-initial", type=pathlib.Path)
    p.add_argument("--retest", type=pathlib.Path)
    p.add_argument("--intermediate", type=pathlib.Path)
    p.add_argument("--native", type=pathlib.Path)
    a = p.parse_args()
    raw = json.loads(a.raw.read_text(encoding="utf-8"))
    index = {(r["model"],r["case"],r["repeat"]):r for r in raw["results"]}
    roots = {}
    superseded_gui = []
    for path in a.gui:
        gui_root = pathlib.Path(path.with_name("scratch-path.txt").read_text(encoding="utf-8").strip())
        for r in json.loads(path.read_text(encoding="utf-8"))["results"]:
            key = (r["model"], r["case"], r["repeat"])
            if key in roots:
                previous = index[key]
                normalize_failure(previous)
                usage(previous, roots[key])
                superseded_gui.append(previous)
            index[key] = r
            roots[key] = gui_root
    retest = load_source(a.retest)
    rows = []
    lines = ["| 模型 | 用例 | 通过 | 失败 | 阻断 | 已判定成功率 |", "|---|---|---:|---:|---:|---:|"]
    for model in MODELS:
        for case in (*CASES, "F-vision", "F-desktop"):
            group = []
            for n in range(1,4):
                r = index.get((model,case,n), {"model":model,"case":case,"repeat":n,
                    "status":"BLOCKED","failure":"NOT_RUN","detail":"无该轮终态证据"})
                normalize_failure(r)
                usage(r, roots.get((model,case,n), a.sandbox.resolve()))
                group.append(r)
            rows.extend(group)
            counts = collections.Counter(r["status"] for r in group)
            tested = counts["PASS"] + counts["FAIL"]
            rate = f"{counts['PASS']/tested:.0%}" if tested else "—"
            lines.append(f"| {model} | {case} | {counts['PASS']} | {counts['FAIL']} | {counts['BLOCKED']} | {rate} |")
    a.output.mkdir(parents=True,exist_ok=True)
    totals = {m: dict(collections.Counter(r["status"] for r in rows if r["model"] == m)) for m in MODELS}
    report = {"version":"1.0.0","planned":len(rows),"results":rows,"scores":totals,
              "source_retest":retest,"intermediate_source_retest":load_source(a.intermediate),
              "native_control":json.loads(a.native.read_text(encoding="utf-8-sig")) if a.native else None}
    if a.gui_initial:
        report["gui_setup_attempts"] = json.loads(a.gui_initial.read_text(encoding="utf-8"))["results"]
    if superseded_gui:
        report["gui_replaced_attempts"] = superseded_gui
    (a.output/"results.json").write_text(json.dumps(report,
        ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines.extend(["","| 模型 | 原版得分（满分 21） | 失败 | 阻断 |", "|---|---:|---:|---:|"])
    for model, count in totals.items():
        lines.append(f"| {model} | {count.get('PASS',0)}/21 | {count.get('FAIL',0)} | {count.get('BLOCKED',0)} |")
    lines.extend(["","| 模型 | 已判定轮次耗时中位数（秒） | 工具完成事件 | 已报告输入 Token | 已报告输出 Token |",
                  "|---|---:|---:|---:|---:|"])
    for model in MODELS:
        group = [r for r in rows if r["model"] == model and r["status"] != "BLOCKED"]
        seconds = [r["seconds"] for r in group if "seconds" in r]
        counts = [r["tokens"] for r in group if r.get("tokens")]
        median = f"{statistics.median(seconds):.2f}" if seconds else "—"
        inp = sum(r["input_tokens"] for r in counts) if counts else "—"
        out = sum(r["output_tokens"] for r in counts) if counts else "—"
        lines.append(f"| {model} | {median} | {sum(r.get('tool_calls',0) for r in group)} | {inp} | {out} |")
    if retest:
        lines.extend(["","| 模型 | 源码复测用例 | 通过 | 失败 | 阻断 |","|---|---|---:|---:|---:|"])
        for model in MODELS:
            for case in sorted({r["case"] for r in retest if r["model"] == model}):
                count = collections.Counter(r["status"] for r in retest if r["model"] == model and r["case"] == case)
                lines.append(f"| {model} | {case} | {count['PASS']} | {count['FAIL']} | {count['BLOCKED']} |")
    (a.output/"model-comparison.md").write_text("# 双模型对比\n\n"+"\n".join(lines)+
        "\n\n成功率分母只包含有 PASS 或 FAIL 终态的轮次。空白表示没有可判定轮次。\n",encoding="utf-8")

if __name__ == "__main__":
    main()

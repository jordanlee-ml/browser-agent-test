#!/usr/bin/env python3
"""Episode 2 — give several models a browser and a shopping task.

Each model gets the same local fixture, the same action protocol, and 20 steps.
The harness records the actions, observations, screenshots, and a screen video.

Usage:
    python3 series/episodes/ep002/run_browser_test.py \
      --agents deepseek-chat,deepseek-reasoner,qwen2.5:7b,qwen2.5-coder:7b
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture" / "shop.html"
OUT = HERE

SYSTEM = """You control a web browser. After each action you receive the page URL and visible text.
Return exactly one JSON object per turn, with no markdown and no explanation.

Available actions:
{"action":"click","selector":"CSS or Playwright selector"}
{"action":"fill","selector":"...","text":"..."}
{"action":"press","key":"Enter"}
{"action":"extract","selector":"..."}
{"action":"finish","answer":"..."}

Selectors may be CSS (e.g. "button[data-id=p1]") or Playwright text selectors
(e.g. "text=View Aero Mug", "text=Close", "text=Accept cookies").

TASK: Find the cheapest product that is in stock and has a rating of 4.0 or higher.
Report its name and price. Use the product buttons to read price, rating, and stock.
A cookie banner may block the page."""


def parse_action(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def call_model(model: str, messages: list[dict], timeout: int = 180) -> str:
    if model.startswith("deepseek-"):
        from openai import OpenAI
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=timeout)
        kwargs = {"model": model, "messages": messages, "max_tokens": 300}
        if model != "deepseek-reasoner":
            kwargs["temperature"] = 0
        return client.chat.completions.create(**kwargs).choices[0].message.content or ""
    response = requests.post(
        "http://127.0.0.1:11434/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": "5m",
            "options": {"temperature": 0, "num_ctx": 8192},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("message", {}).get("content", "")


def observation(page) -> str:
    url = page.url
    try:
        body = page.inner_text("body")
    except Exception:
        body = ""
    buttons = []
    try:
        buttons = page.locator("button").all_inner_texts()
    except Exception:
        pass
    text = body[:2200]
    if buttons:
        text += "\n\nBUTTONS: " + " | ".join(b.replace("\n", " ")[:40] for b in buttons[:12])
    return f"URL: {url}\nVISIBLE TEXT:\n{text}"


def run_agent(browser, model: str, max_steps: int = 20) -> dict:
    video_dir = OUT / "video" / re.sub(r"[^a-zA-Z0-9]+", "_", model)
    video_dir.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        record_video_dir=str(video_dir),
        record_video_size={"width": 1280, "height": 720},
    )
    page = context.new_page()
    page.goto(FIXTURE.as_uri(), wait_until="load")
    time.sleep(0.4)

    steps = []
    answer = None
    error = None
    started = time.time()
    messages = [{"role": "system", "content": SYSTEM}]
    obs = observation(page)

    for i in range(1, max_steps + 1):
        messages.append({"role": "user", "content": f"Observation:\n{obs}\n\nReturn one JSON action."})
        try:
            raw = call_model(model, messages)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            steps.append({"step": i, "action": None, "observation": obs, "error": error, "raw": ""})
            break
        action = parse_action(raw)
        messages.append({"role": "assistant", "content": raw})
        if action is None:
            steps.append({"step": i, "action": None, "observation": obs,
                          "error": "unparseable action", "raw": raw[:800]})
            obs = "Your previous response was not a parseable JSON action. Return one JSON object."
            continue

        kind = str(action.get("action", "")).lower()
        try:
            if kind == "click":
                page.locator(action["selector"]).first.click(timeout=2500)
                result = "clicked"
            elif kind == "fill":
                page.locator(action["selector"]).first.fill(str(action.get("text", "")), timeout=2500)
                result = "filled"
            elif kind == "press":
                page.keyboard.press(str(action.get("key", "Enter")))
                result = "pressed"
            elif kind == "extract":
                result = page.locator(action["selector"]).first.inner_text(timeout=2500)[:800]
            elif kind == "finish":
                answer = str(action.get("answer", ""))
                result = "finished"
            else:
                result = f"unknown action: {kind}"
            error = None
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {str(exc)[:220]}"
            result = "action failed"

        try:
            page.screenshot(path=str(video_dir / f"step_{i:02d}.png"))
        except Exception:
            pass
        steps.append({
            "step": i,
            "action": action,
            "result": result,
            "error": error,
            "observation": obs,
            "raw": raw[:1200],
        })
        if kind == "finish":
            break
        time.sleep(0.3)
        obs = observation(page)
        if error:
            obs += f"\nLAST ACTION ERROR: {error}"

    elapsed = round(time.time() - started, 2)
    context.close()

    success = bool(answer and "aero mug" in answer.lower() and "18" in answer.lower())
    failure = None
    if success:
        failure = None
    elif answer is None:
        failure = error or ("step limit" if len(steps) >= max_steps else "no finish")
    else:
        failure = "wrong answer"

    return {
        "agent": model,
        "success": success,
        "answer": answer,
        "steps": len(steps),
        "elapsed_s": elapsed,
        "failure": failure,
        "trajectory": steps,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", default="deepseek-chat,deepseek-reasoner,qwen2.5:7b,qwen2.5-coder:7b")
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]

    results = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path="/usr/bin/google-chrome")
        except Exception:
            browser = p.chromium.launch()
        for model in agents:
            print(f"\n=== {model} ===", flush=True)
            result = run_agent(browser, model, args.max_steps)
            results.append(result)
            print(f"  success={result['success']} steps={result['steps']} "
                  f"time={result['elapsed_s']}s failure={result['failure']}", flush=True)
        browser.close()

    summary = {
        "fixture": str(FIXTURE),
        "gold": "Aero Mug, $18",
        "tested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "agents": results,
    }
    (out / "results.json").write_text(json.dumps(summary, indent=2))

    lines = [
        "# Episode 2 — I gave an agent a browser",
        "",
        f"Tested: {summary['tested_at']}",
        f"Gold: {summary['gold']}",
        "",
        "| Agent | Success | Steps | Time | Failure | Answer |",
        "|---|---:|---:|---:|---|---|",
    ]
    for r in results:
        ans = (r["answer"] or "").replace("|", "/")[:80]
        lines.append(f"| {r['agent']} | {'yes' if r['success'] else 'no'} | {r['steps']} | "
                     f"{r['elapsed_s']}s | {r['failure'] or ''} | {ans} |")
    lines += ["", "## Trajectories", ""]
    for r in results:
        lines += [f"### {r['agent']}", ""]
        for s in r["trajectory"]:
            lines += [f"- **Step {s['step']}:** `{json.dumps(s['action'])[:220]}` → "
                      f"{s.get('result','')}" + (f" ERROR: {s['error']}" if s.get("error") else "")]
        lines += [""]
    (out / "transcript.md").write_text("\n".join(lines))
    print(f"\nwrote {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

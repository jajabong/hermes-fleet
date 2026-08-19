#!/usr/bin/env python3
"""Hermes lightweight subagent: direct LLM API calls, stdlib only.

Pure-dialogue tasks (hi/analyze/plan) skip the DSH agent entirely, saving
5-10x tokens. Provider keys come from ~/.dsh/settings.yaml (llm-pi-ai.providers).
Lightweight tools (web_search/web_fetch/read_file/write_file/bash/list_dir/
search_files) are available via a multi-round tool loop (--tools).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DSH_HOME = Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh")
DSH_SETTINGS = DSH_HOME / "settings.yaml"

PROVIDER_DEFAULTS = {
    "deepseek-official": ("https://api.deepseek.com/v1", "deepseek-v4-flash"),
    "minimax": ("https://api.minimaxi.com/v1", "MiniMax-M3"),
    "anthropic": ("", ""),
}

SYSTEM_PROMPT = (
    "You are Hermes, a lightweight assistant. Be concise and direct. "
    "Answer the user's task; do not over-explain."
    " You have lightweight tools available: web_search, web_fetch, read_file, "
    "write_file, bash, list_dir, search_files. If a task needs complex tools "
    "(excel formulas, ppt generation, docker, vision/OCR, browser automation), "
    "say so and stop."
)

TOOL_WHITELIST = {"web_search", "web_fetch", "read_file", "write_file",
                  "bash", "list_dir", "search_files"}
MAX_TOOL_ROUNDS = 5
MAX_READ_BYTES = 64 * 1024
MAX_WRITE_BYTES = 1024 * 1024
MAX_BASH_SECONDS = 30
MAX_LIST_ENTRIES = 100
MAX_SEARCH_MATCHES = 50
MAX_FETCH_BYTES = 5 * 1024

MAX_RESPONSE_BYTES = 1 << 20


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def _load_settings() -> dict:
    """Minimal YAML-subset parser: indentation-nested maps and key: value."""
    result: dict = {}
    try:
        text = DSH_SETTINGS.read_text(encoding="utf-8")
    except OSError:
        return {}
    stack: list[tuple[dict, int]] = [(result, -1)]
    key_re = re.compile(r"^(\s*)([A-Za-z0-9_-]+):\s*(.*)$")
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = key_re.match(raw)
        if not m:
            continue
        indent, key, value = len(m.group(1)), m.group(2), m.group(3).strip()
        while stack and indent <= stack[-1][1]:
            stack.pop()
        parent = stack[-1][0]
        if value:
            parent[key] = value.strip("\"'")
        else:
            child: dict = {}
            parent[key] = child
            stack.append((child, indent))
    return result


def _provider_cfg(provider: str) -> dict:
    data = _load_settings()
    providers = ((data.get("llm-pi-ai") or {}).get("providers") or {}).get(provider)
    return providers if isinstance(providers, dict) else {}


def _api_key(provider: str) -> str | None:
    cfg = _provider_cfg(provider)
    key = cfg.get("apiKey")
    if not key:
        env_name = f"{provider.upper().replace('-', '_')}_API_KEY"
        key = os.environ.get(env_name)
    return str(key).strip() if key else None


def _chat_request(provider, model, api_key, messages, timeout):
    cfg = _provider_cfg(provider)
    base = cfg.get("baseURL") or PROVIDER_DEFAULTS[provider][0]
    if not base:
        raise RuntimeError(f"{provider}: no OpenAI-compatible endpoint configured")
    url = base.rstrip("/") + "/chat/completions"
    body = json.dumps({"model": model, "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read(MAX_RESPONSE_BYTES).decode("utf-8"))
    choice = (payload.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    usage = payload.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens") or _estimate_tokens(messages[0]["content"]))
    tokens_out = int(usage.get("completion_tokens") or _estimate_tokens(text))
    return {"text": text, "tokens_in": tokens_in, "tokens_out": tokens_out}


def _tool_web_search(query: str) -> str:
    """DuckDuckGo HTML scrape; no API key."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read(MAX_FETCH_BYTES).decode("utf-8", "replace")
    except Exception as e:
        return f"error: {e}"
    links = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html)
    out = []
    for i, t in enumerate(links[:5]):
        text = re.sub(r"<[^>]+>", "", t).strip()
        snip = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
        out.append(f"{i+1}. {text} — {snip}")
    return "\n".join(out) or "no results"


def _tool_web_fetch(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read(MAX_FETCH_BYTES).decode("utf-8", "replace")
    except Exception as e:
        return f"error: {e}"


def _tool_read_file(path: str) -> str:
    try:
        data = Path(path).read_bytes()
    except Exception as e:
        return f"error: {e}"
    if len(data) > MAX_READ_BYTES:
        data = data[:MAX_READ_BYTES]
    return data.decode("utf-8", "replace")


def _tool_write_file(path: str, content: str) -> str:
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        return f"error: content exceeds {MAX_WRITE_BYTES} bytes"
    try:
        Path(path).write_bytes(data)
        return f"wrote {len(data)} bytes to {path}"
    except Exception as e:
        return f"error: {e}"


def _tool_bash(cmd: str) -> str:
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=MAX_BASH_SECONDS)
    except subprocess.TimeoutExpired:
        return f"error: timed out after {MAX_BASH_SECONDS}s"
    except Exception as e:
        return f"error: {e}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parts = [p for p in (out, f"stderr: {err}" if err else "") if p]
    return "\n".join(parts) or f"exit {proc.returncode}"


def _tool_list_dir(path: str) -> str:
    try:
        entries = sorted(Path(path).iterdir())[:MAX_LIST_ENTRIES]
    except Exception as e:
        return f"error: {e}"
    return "\n".join(f"{'d' if p.is_dir() else '-'} {p.name}" for p in entries)


def _tool_search_files(pattern: str) -> str:
    matches = []
    root = Path.cwd()
    try:
        rx = re.compile(pattern)
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    if rx.search(p.read_text("utf-8", "replace")):
                        matches.append(str(p))
                except Exception:
                    continue
            if len(matches) >= MAX_SEARCH_MATCHES:
                break
    except Exception as e:
        return f"error: {e}"
    return "\n".join(matches) if matches else "no matches"


_TOOL_HANDLERS = {
    "web_search": _tool_web_search,
    "web_fetch": _tool_web_fetch,
    "read_file": _tool_read_file,
    "write_file": _tool_write_file,
    "bash": _tool_bash,
    "list_dir": _tool_list_dir,
    "search_files": _tool_search_files,
}


def _execute_tool(name: str, arguments: dict) -> str:
    if name not in TOOL_WHITELIST:
        return f"error: tool '{name}' not allowed (defer to DSH for complex tools)"
    fn = _TOOL_HANDLERS[name]
    try:
        return str(fn(**arguments))
    except TypeError as e:
        return f"error: bad arguments for {name}: {e}"
    except Exception as e:
        return f"error: {e}"


def run_subagent(
    task: str,
    provider: str = "deepseek-official",
    model: str | None = None,
    system: str | None = None,
    timeout: int = 60,
) -> dict:
    """Direct single-turn LLM call. Returns {"text","tokens_in","tokens_out"}
    or {"error": "missing-api-key"|"api-error"|"timeout", "message": str}."""
    if provider not in PROVIDER_DEFAULTS:
        return {"error": "api-error", "message": f"unknown provider: {provider}"}
    if model is None:
        model = PROVIDER_DEFAULTS[provider][1]
    key = _api_key(provider)
    if not key:
        return {"error": "missing-api-key"}
    system = system or SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    try:
        return _chat_request(provider, model, key, messages, timeout)
    except urllib.error.HTTPError as e:
        return {"error": "api-error", "message": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": "api-error", "message": str(e.reason or e)}
    except TimeoutError:
        return {"error": "timeout"}
    except Exception as e:  # noqa: BLE001
        return {"error": "api-error", "message": str(e)}


def run_subagent_with_tools(
    task: str,
    provider: str = "deepseek-official",
    model: str | None = None,
    system: str | None = None,
    timeout: int = 60,
) -> dict:
    """Multi-round tool loop on top of run_subagent. Returns the same dict
    shape as run_subagent with tool rounds folded in."""
    key = _api_key(provider)
    if not key:
        return {"error": "missing-api-key"}
    if model is None:
        model = PROVIDER_DEFAULTS[provider][1]
    system = system or SYSTEM_PROMPT
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": task}]
    total_in, total_out = 0, 0
    for _ in range(MAX_TOOL_ROUNDS + 1):
        try:
            result = _chat_request(provider, model, key, messages, timeout)
        except urllib.error.HTTPError as e:
            return {"error": "api-error", "message": f"HTTP {e.code}: {e.reason}"}
        except urllib.error.URLError as e:
            return {"error": "api-error", "message": str(e.reason or e)}
        except TimeoutError:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": "api-error", "message": str(e)}
        total_in += result["tokens_in"]
        total_out += result["tokens_out"]
        text = result["text"]
        try:
            tool_call = json.loads(text.strip())
            if not isinstance(tool_call, dict) or "name" not in tool_call:
                return {"text": text, "tokens_in": total_in, "tokens_out": total_out}
        except (json.JSONDecodeError, ValueError):
            return {"text": text, "tokens_in": total_in, "tokens_out": total_out}
        tool_result = _execute_tool(tool_call.get("name", ""), tool_call.get("arguments") or {})
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "tool", "content": tool_result,
                         "name": tool_call.get("name", "")})
    return {"text": "max tool rounds reached", "tokens_in": total_in, "tokens_out": total_out}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hermes_subagent",
        description="Hermes lightweight subagent (direct LLM API)",
    )
    ap.add_argument("task", help="task text")
    ap.add_argument("--provider", default="deepseek-official",
                    help="provider name in settings.yaml")
    ap.add_argument("--model", default=None,
                    help="model id (default: provider default)")
    ap.add_argument("--system", default=None, help="override system prompt")
    ap.add_argument("--timeout", type=int, default=60,
                    help="request timeout in seconds")
    ap.add_argument("--tools", action="store_true",
                    help="enable the lightweight tool loop")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout")
    args = ap.parse_args(argv)

    if args.tools:
        result = run_subagent_with_tools(args.task, args.provider, args.model,
                                         args.system, args.timeout)
    else:
        result = run_subagent(args.task, args.provider, args.model, args.system, args.timeout)
    err = result.get("error")
    if err == "missing-api-key":
        print(f"[Hermes] missing API key for provider '{args.provider}' "
              f"(set ~/.dsh/settings.yaml)", file=sys.stderr)
        return 2
    if err == "timeout":
        print(f"[Hermes] request timed out after {args.timeout}s", file=sys.stderr)
        return 4
    if err == "api-error":
        print(f"[Hermes] API error: {result.get('message', '')}", file=sys.stderr)
        return 3
    print(f"[Hermes] tokens=prompt:{result['tokens_in']} completion:{result['tokens_out']}",
          file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

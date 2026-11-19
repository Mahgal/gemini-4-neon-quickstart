#!/usr/bin/env python3
"""gemini-4-neon-quickstart — try Google's Gemini 4 Neon from the command line.

Stdlib only. No pip installs. Python 3.8+.

    python gemini4_neon.py chat --mock "Explain quantum computing in one sentence."
    python gemini4_neon.py chat --mock --thinking-level low "Say hello."
    python gemini4_neon.py estimate --input-chars 10000 --output-tokens 500
    python gemini4_neon.py chat --live "Explain quantum computing in one sentence."

Live calls need GEMINI_API_KEY in the environment (paid tier — there is NO
free tier for gemini-4-neon, so every token is billed; run `estimate` first).
The key is never printed and never written anywhere by this tool.

Model: gemini-4-neon, generally available 2026-11-18.
Pricing (per 1M tokens, paid tier, Google):
    Standard  $3.00 input / $0.15 cached input / $15.00 output
    Batch     $1.50 input / $7.50 output          (0.5x Standard)
    Flex      $1.50 input / $7.50 output          (0.5x Standard)
    Priority  $5.40 input / $27.00 output         (1.8x Standard)
Thinking tokens are billed too (at the output rate). There is no free tier.

Cached-input rates for Batch/Flex ($0.075) and Priority ($0.27) are the
Standard $0.15 scaled by the same tier multiplier Google applies to
input/output; verify on the pricing page before relying on them for billing.

Context window: 1,048,576 tokens (unified input + thinking + output).
Thinking levels: low / medium / high / xhigh (default high).
Knowledge cutoff: March 2026. Max output: 65,536 tokens per synchronous
segment, up to 1M tokens with background long decode.

Exit codes: 0 success · 1 API call failed · 2 bad arguments / missing API key.

NOTE: the --live path is code-reviewed only. No live call was made while
building this quickstart (no GEMINI_API_KEY in this environment), so the
live path has not been verified against the real API. The --mock and
--estimate paths are fully real and tested.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

MODEL_ID = "gemini-4-neon"
API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-4-neon:generateContent"
)

# Rates per 1M tokens. "multiplier" is the tier's factor vs Standard.
TIERS = {
    "standard": {
        "label": "Standard",
        "input": 3.00,
        "cached_input": 0.15,
        "output": 15.00,
        "multiplier": 1.0,
    },
    "batch": {
        "label": "Batch",
        "input": 1.50,
        "cached_input": 0.075,
        "output": 7.50,
        "multiplier": 0.5,
    },
    "flex": {
        "label": "Flex",
        "input": 1.50,
        "cached_input": 0.075,
        "output": 7.50,
        "multiplier": 0.5,
    },
    "priority": {
        "label": "Priority",
        "input": 5.40,
        "cached_input": 0.27,
        "output": 27.00,
        "multiplier": 1.8,
    },
}

# Gemini 4 Carbon from 2026-12-01 (intro $2/$10 ends 2026-11-30, then $4/$20).
CARBON_DEC1_INPUT = 4.00
CARBON_DEC1_OUTPUT = 20.00

THINKING_LEVELS = ("low", "medium", "high", "xhigh")
DEFAULT_THINKING_LEVEL = "high"
DEFAULT_MAX_OUTPUT_TOKENS = 1024
CONTEXT_WINDOW_TOKENS = 1_048_576


def resolve_thinking_level(level):
    """Validate a thinking level; return the normalized lowercase value."""
    level = str(level).strip()
    if level not in THINKING_LEVELS:
        raise ValueError(
            "unknown thinking level %r (use one of: %s)"
            % (level, ", ".join(THINKING_LEVELS))
        )
    return level


def resolve_tier(name):
    """Accept a tier name; return the normalized lowercase key."""
    name = str(name).strip().lower()
    if name not in TIERS:
        raise ValueError(
            "unknown tier %r (use one of: %s)" % (name, ", ".join(TIERS))
        )
    return name


def estimate_tokens(chars):
    """Rough token estimate: chars/4 — an approximation, stated openly."""
    return max(0, int(chars) // 4)


def estimate_cost(tier, input_tokens, output_tokens, cached=False,
                  thinking_tokens=0):
    """Cost in USD for one request. Pure arithmetic, no network.

    Thinking tokens are billed at the output rate.
    """
    spec = TIERS[tier]
    input_rate = spec["cached_input"] if cached else spec["input"]
    input_cost = input_tokens * input_rate / 1_000_000
    output_cost = (output_tokens + thinking_tokens) * spec["output"] / 1_000_000
    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total": input_cost + output_cost,
    }


def carbon_dec1_cost(input_tokens, output_tokens):
    """Same request priced on Gemini 4 Carbon at its 2026-12-01 rates."""
    return {
        "input_cost": input_tokens * CARBON_DEC1_INPUT / 1_000_000,
        "output_cost": output_tokens * CARBON_DEC1_OUTPUT / 1_000_000,
        "total": input_tokens * CARBON_DEC1_INPUT / 1_000_000
        + output_tokens * CARBON_DEC1_OUTPUT / 1_000_000,
    }


def estimate_table(input_chars, output_tokens, cached=False, thinking_tokens=0):
    """Cost table across all four Neon tiers + the Carbon Dec-1 comparison.

    Deterministic, no network. Input tokens are chars/4 (approximation).
    """
    input_tokens = estimate_tokens(input_chars)
    lines = []
    lines.append(
        "Input: %d chars ~= %d tokens (chars/4 estimate — verify with a "
        "tokenizer for exact counts)" % (input_chars, input_tokens)
    )
    lines.append("Output: %d tokens" % output_tokens)
    if thinking_tokens:
        lines.append(
            "Thinking: %d tokens (billed at the output rate — "
            "there is no free tier, thinking included)" % thinking_tokens
        )
    if cached:
        lines.append("Input priced at the cached-input rate.")
    lines.append("")
    lines.append("%-10s %12s %12s %12s" % ("Tier", "Input", "Output", "Total"))
    totals = {}
    for key in ("standard", "batch", "flex", "priority"):
        cost = estimate_cost(key, input_tokens, output_tokens, cached,
                             thinking_tokens)
        totals[key] = cost["total"]
        lines.append(
            "%-10s $%11.6f $%11.6f $%11.6f"
            % (
                TIERS[key]["label"],
                cost["input_cost"],
                cost["output_cost"],
                cost["total"],
            )
        )
    lines.append("")
    lines.append(
        "Batch/Flex cost %.2fx Standard; Priority costs %.2fx Standard."
        % (totals["batch"] / totals["standard"] if totals["standard"] else 0,
           totals["priority"] / totals["standard"] if totals["standard"] else 0)
    )
    lines.append(
        "Prices per 1M tokens: Standard $3.00 in / $0.15 cached / $15.00 out; "
        "Batch/Flex $1.50 / $7.50; Priority $5.40 / $27.00."
    )
    lines.append("")
    carbon = carbon_dec1_cost(input_tokens, output_tokens)
    neon = totals["standard"]
    if carbon["total"] > 0 and neon > 0:
        saving = (carbon["total"] - neon) / carbon["total"] * 100
        lines.append(
            "From Dec 1, the same request on Gemini 4 Carbon costs $%.4f "
            "(at $4.00/$20.00) vs $%.4f on Neon Standard — "
            "Neon is %.0f%% cheaper." % (carbon["total"], neon, saving)
        )
    else:
        lines.append(
            "From Dec 1, Carbon costs $4.00/$20.00 per 1M tokens vs "
            "Neon $3.00/$15.00 — Neon is 25% cheaper."
        )
    return "\n".join(lines)


def build_request(prompt, thinking_level=DEFAULT_THINKING_LEVEL,
                  max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS):
    """The exact JSON body sent to the Gemini generateContent endpoint."""
    return {
        "model": MODEL_ID,
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": thinking_level},
            "maxOutputTokens": max_output_tokens,
        },
    }


def simulated_reply(prompt):
    return (
        "This is a SIMULATED reply from %s. "
        "No network call was made and no API key was used. "
        "Run without --mock (with GEMINI_API_KEY set) to get a real answer to: %r"
        % (MODEL_ID, prompt)
    )


def cmd_estimate(args):
    try:
        selected = resolve_tier(args.tier)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.input_chars < 0 or args.output_tokens < 0 or args.thinking_tokens < 0:
        print(
            "error: --input-chars, --output-tokens and --thinking-tokens "
            "must be >= 0",
            file=sys.stderr,
        )
        return 2
    print(estimate_table(args.input_chars, args.output_tokens, args.cached,
                         args.thinking_tokens))
    print("")
    print("Selected tier: %s ($%.2f in / $%.2f out per 1M tokens)"
          % (TIERS[selected]["label"], TIERS[selected]["input"],
             TIERS[selected]["output"]))
    return 0


def cmd_chat(args):
    try:
        thinking_level = resolve_thinking_level(args.thinking_level)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    request = build_request(args.prompt, thinking_level, args.max_output_tokens)
    request_json = json.dumps(request, indent=2, ensure_ascii=False)

    if args.mock:
        print("Request JSON (would be sent to %s):" % API_URL)
        print("")
        print(request_json)
        print("")
        print("[SIMULATED RESPONSE — no network call was made, no API key used]")
        reply = simulated_reply(args.prompt)
        print(reply)
        # Deterministic fake token accounting, chars/4 like the estimator.
        input_tokens = estimate_tokens(len(args.prompt))
        output_tokens = estimate_tokens(len(reply))
        cost = estimate_cost("standard", input_tokens, output_tokens)
        print("")
        print(
            "Simulated usage: %d input + %d output tokens "
            "(chars/4 estimate) — would cost $%.6f at the Standard tier. "
            "Neon has NO free tier: even this first call would be billed."
            % (input_tokens, output_tokens, cost["total"])
        )
        return 0

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "error: GEMINI_API_KEY is not set.\n"
            "Set it first, e.g.:\n"
            "  export GEMINI_API_KEY=<your-key>\n"
            "Then re-run this command. Your key is never printed or stored "
            "by this tool.\n"
            "WARNING: gemini-4-neon has NO free tier — every token is billed "
            "(thinking tokens included). Run `estimate` first to see the "
            "price.\n"
            "Tip: use --mock to try the quickstart with no key and no network.",
            file=sys.stderr,
        )
        return 2

    body = json.dumps(request).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        print("error: API request failed (HTTP %s): %s" % (exc.code, detail),
              file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print("error: network request failed: %s" % exc.reason, file=sys.stderr)
        return 1

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        print("error: unexpected API response: %s" % json.dumps(payload)[:500],
              file=sys.stderr)
        return 1
    print(text)
    usage = payload.get("usageMetadata") or {}
    prompt_tokens = usage.get("promptTokenCount")
    completion_tokens = usage.get("candidatesTokenCount")
    thinking_tokens = usage.get("thoughtsTokenCount") or 0
    if prompt_tokens is not None and completion_tokens is not None:
        cost = estimate_cost("standard", prompt_tokens, completion_tokens,
                             thinking_tokens=thinking_tokens)
        print("")
        print(
            "Usage: %d prompt + %d completion + %d thinking tokens — "
            "estimated cost $%.6f at the Standard tier"
            % (prompt_tokens, completion_tokens, thinking_tokens, cost["total"])
        )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="gemini4_neon.py",
        description="Call Google Gemini 4 Neon (gemini-4-neon) from the "
                    "command line. Stdlib only.",
    )
    parser.add_argument("--mock", action="store_true",
                        help="simulate the chat call (no network, no key)")
    parser.add_argument("--live", action="store_true",
                        help="make a real API call (needs GEMINI_API_KEY)")
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="send one prompt to Gemini 4 Neon")
    chat.add_argument("prompt", help="the prompt to send")
    chat.add_argument("--thinking-level", default=DEFAULT_THINKING_LEVEL,
                      choices=list(THINKING_LEVELS),
                      help="thinking level: low|medium|high|xhigh "
                           "(default: high)")
    chat.add_argument("--max-output-tokens", type=int,
                      default=DEFAULT_MAX_OUTPUT_TOKENS)
    chat.add_argument("--mock", action="store_true", default=argparse.SUPPRESS,
                      help="simulate the call (no network, no key)")
    chat.add_argument("--live", action="store_true", default=argparse.SUPPRESS,
                      help="make a real API call (needs GEMINI_API_KEY)")
    chat.set_defaults(func=cmd_chat)

    est = sub.add_parser("estimate", help="estimate the cost of a request")
    est.add_argument("--tier", default="standard",
                     help="'standard', 'batch', 'flex' or 'priority' "
                          "(table always shows all four)")
    est.add_argument("--input-chars", type=int, required=True,
                     help="approximate input size in characters (tokens ~= chars/4)")
    est.add_argument("--output-tokens", type=int, required=True,
                     help="expected output tokens")
    est.add_argument("--thinking-tokens", type=int, default=0,
                     help="expected thinking tokens (billed at output rate)")
    est.add_argument("--cached", action="store_true",
                     help="price input at the cached-input rate")
    est.set_defaults(func=cmd_estimate)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # --mock / --live may be given before or after the subcommand.
    if getattr(args, "mock", False):
        args.mock = True
    if getattr(args, "live", False):
        args.live = True
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

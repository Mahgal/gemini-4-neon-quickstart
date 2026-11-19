"""Tests for gemini4_neon.py — pricing math, tiers, thinking levels, mock, key handling.

Stdlib unittest only. Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gemini4_neon

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run_cli(argv, env=None):
    """Run gemini4_neon.py as a subprocess; returns (exit_code, stdout, stderr)."""
    full_env = dict(os.environ)
    full_env.pop("GEMINI_API_KEY", None)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "gemini4_neon.py")] + argv,
        capture_output=True, text=True, env=full_env, timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestPricingMath(unittest.TestCase):
    def test_worked_example_standard(self):
        # Hand-verified: 10,000 chars ~= 2,500 tokens in, 500 out.
        # 2500 * $3.00/1M = $0.0075; 500 * $15.00/1M = $0.0075; total $0.0150.
        cost = gemini4_neon.estimate_cost("standard", 2500, 500)
        self.assertAlmostEqual(cost["input_cost"], 0.0075)
        self.assertAlmostEqual(cost["output_cost"], 0.0075)
        self.assertAlmostEqual(cost["total"], 0.0150)

    def test_worked_example_batch_is_half(self):
        cost = gemini4_neon.estimate_cost("batch", 2500, 500)
        self.assertAlmostEqual(cost["total"], 0.0075)

    def test_worked_example_flex_is_half(self):
        cost = gemini4_neon.estimate_cost("flex", 2500, 500)
        self.assertAlmostEqual(cost["total"], 0.0075)

    def test_worked_example_priority_is_1_8x(self):
        # 2500 * $5.40/1M = $0.0135; 500 * $27.00/1M = $0.0135; total $0.0270.
        cost = gemini4_neon.estimate_cost("priority", 2500, 500)
        self.assertAlmostEqual(cost["input_cost"], 0.0135)
        self.assertAlmostEqual(cost["output_cost"], 0.0135)
        self.assertAlmostEqual(cost["total"], 0.0270)

    def test_cached_input_rate(self):
        # 2500 cached tokens * $0.15/1M = $0.000375.
        cost = gemini4_neon.estimate_cost("standard", 2500, 0, cached=True)
        self.assertAlmostEqual(cost["input_cost"], 0.000375)
        # Cached input is 20x cheaper than uncached.
        uncached = gemini4_neon.estimate_cost("standard", 2500, 0)
        self.assertAlmostEqual(uncached["input_cost"], 20 * cost["input_cost"])

    def test_cached_tier_scaling(self):
        # Batch/Flex cached = $0.075 (0.5x of $0.15); Priority = $0.27 (1.8x).
        batch = gemini4_neon.estimate_cost("batch", 1_000_000, 0, cached=True)
        self.assertAlmostEqual(batch["input_cost"], 0.075)
        priority = gemini4_neon.estimate_cost("priority", 1_000_000, 0, cached=True)
        self.assertAlmostEqual(priority["input_cost"], 0.27)

    def test_tier_multipliers(self):
        for in_tok, out_tok in [(100, 50), (2500, 500), (100_000, 10_000)]:
            std = gemini4_neon.estimate_cost("standard", in_tok, out_tok)
            batch = gemini4_neon.estimate_cost("batch", in_tok, out_tok)
            priority = gemini4_neon.estimate_cost("priority", in_tok, out_tok)
            self.assertAlmostEqual(batch["total"], 0.5 * std["total"])
            self.assertAlmostEqual(priority["total"], 1.8 * std["total"])

    def test_thinking_tokens_billed_at_output_rate(self):
        # 500 thinking tokens cost the same as 500 output tokens: $0.0075.
        cost = gemini4_neon.estimate_cost("standard", 0, 0, thinking_tokens=500)
        self.assertAlmostEqual(cost["output_cost"], 0.0075)
        self.assertAlmostEqual(cost["total"], 0.0075)

    def test_zero_tokens(self):
        for tier in ("standard", "batch", "flex", "priority"):
            cost = gemini4_neon.estimate_cost(tier, 0, 0)
            self.assertEqual(cost["total"], 0.0)

    def test_full_context_window(self):
        # Full 1,048,576-token context in + 65,536 max sync output tokens.
        # 1048576 * $3/1M = $3.145728; 65536 * $15/1M = $0.98304.
        cost = gemini4_neon.estimate_cost("standard", 1_048_576, 65_536)
        self.assertAlmostEqual(cost["input_cost"], 3.145728)
        self.assertAlmostEqual(cost["output_cost"], 0.98304)
        self.assertAlmostEqual(cost["total"], 4.128768)

    def test_one_million_tokens(self):
        cost = gemini4_neon.estimate_cost("standard", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost["input_cost"], 3.00)
        self.assertAlmostEqual(cost["output_cost"], 15.00)
        self.assertAlmostEqual(cost["total"], 18.00)


class TestCarbonComparison(unittest.TestCase):
    def test_carbon_dec1_worked_example(self):
        # Carbon Dec 1: 2500 * $4/1M = $0.01; 500 * $20/1M = $0.01; total $0.02.
        carbon = gemini4_neon.carbon_dec1_cost(2500, 500)
        self.assertAlmostEqual(carbon["total"], 0.0200)
        neon = gemini4_neon.estimate_cost("standard", 2500, 500)
        # Neon ($0.0150) is 25% cheaper than Carbon Dec 1 ($0.0200).
        self.assertAlmostEqual((carbon["total"] - neon["total"]) / carbon["total"],
                              0.25)

    def test_estimate_table_has_carbon_line(self):
        table = gemini4_neon.estimate_table(10000, 500)
        self.assertIn("Carbon", table)
        self.assertIn("25% cheaper", table)


class TestThinkingLevels(unittest.TestCase):
    def test_all_four_levels_valid(self):
        for level in ("low", "medium", "high", "xhigh"):
            self.assertEqual(gemini4_neon.resolve_thinking_level(level), level)

    def test_default_is_high(self):
        self.assertEqual(gemini4_neon.DEFAULT_THINKING_LEVEL, "high")

    def test_invalid_level_rejected(self):
        for bad in ("ultra", "max", "", "HIGH "):
            with self.assertRaises(ValueError):
                gemini4_neon.resolve_thinking_level(bad)
        # "HIGH " is rejected because trailing space is stripped but case
        # is not folded: only exact lowercase levels are accepted.
        with self.assertRaises(ValueError):
            gemini4_neon.resolve_thinking_level("HIGH")

    def test_invalid_level_cli_exits_2(self):
        code, _, err = run_cli(
            ["chat", "--mock", "--thinking-level", "ultra", "Hello"]
        )
        self.assertEqual(code, 2)

    def test_each_level_in_request_json(self):
        for level in ("low", "medium", "high", "xhigh"):
            req = gemini4_neon.build_request("Hi", level)
            self.assertEqual(
                req["generationConfig"]["thinkingConfig"]["thinkingLevel"], level
            )


class TestRequestShape(unittest.TestCase):
    def test_model_id(self):
        req = gemini4_neon.build_request("Hello")
        self.assertEqual(req["model"], "gemini-4-neon")

    def test_contents_structure(self):
        req = gemini4_neon.build_request("Hello")
        self.assertEqual(
            req["contents"], [{"parts": [{"text": "Hello"}]}]
        )

    def test_default_thinking_level_in_request(self):
        req = gemini4_neon.build_request("Hello")
        self.assertEqual(
            req["generationConfig"]["thinkingConfig"]["thinkingLevel"], "high"
        )

    def test_max_output_tokens_passthrough(self):
        req = gemini4_neon.build_request("Hello", max_output_tokens=2048)
        self.assertEqual(req["generationConfig"]["maxOutputTokens"], 2048)

    def test_request_is_json_serializable(self):
        req = gemini4_neon.build_request("héllo wörld", "low")
        self.assertIn("gemini-4-neon", json.dumps(req, ensure_ascii=False))

    def test_unknown_tier_rejected(self):
        with self.assertRaises(ValueError):
            gemini4_neon.resolve_tier("turbo")


class TestEstimateTable(unittest.TestCase):
    def test_all_four_tiers_shown(self):
        table = gemini4_neon.estimate_table(10000, 500)
        for label in ("Standard", "Batch", "Flex", "Priority"):
            self.assertIn(label, table)
        self.assertIn("2500 tokens", table)  # 10000 chars / 4

    def test_approximation_stated(self):
        table = gemini4_neon.estimate_table(400, 10)
        self.assertIn("chars/4", table)

    def test_deterministic(self):
        a = gemini4_neon.estimate_table(12345, 678, cached=True,
                                        thinking_tokens=100)
        b = gemini4_neon.estimate_table(12345, 678, cached=True,
                                        thinking_tokens=100)
        self.assertEqual(a, b)

    def test_zero_request_is_free(self):
        table = gemini4_neon.estimate_table(0, 0)
        self.assertIn("$   0.000000", table)

    def test_estimate_cli_exit_0(self):
        code, out, _ = run_cli(
            ["estimate", "--input-chars", "10000", "--output-tokens", "500"]
        )
        self.assertEqual(code, 0)
        self.assertIn("Standard", out)
        self.assertIn("Priority", out)
        self.assertIn("Carbon", out)
        self.assertIn("0.015000", out)  # Standard total for the worked example

    def test_estimate_cli_cached_flag(self):
        code, out, _ = run_cli(
            ["estimate", "--input-chars", "4000000", "--output-tokens", "0",
             "--cached"]
        )
        self.assertEqual(code, 0)
        self.assertIn("cached", out.lower())

    def test_estimate_cli_negative_rejected(self):
        code, _, err = run_cli(
            ["estimate", "--input-chars", "-5", "--output-tokens", "10"]
        )
        self.assertEqual(code, 2)

    def test_estimate_cli_thinking_tokens(self):
        code, out, _ = run_cli(
            ["estimate", "--input-chars", "10000", "--output-tokens", "500",
             "--thinking-tokens", "1000"]
        )
        self.assertEqual(code, 0)
        self.assertIn("Thinking", out)


class TestMock(unittest.TestCase):
    def test_mock_contains_simulated_label(self):
        code, out, _ = run_cli(["chat", "--mock", "Say hello."])
        self.assertEqual(code, 0)
        self.assertIn("SIMULATED", out)

    def test_mock_flag_before_subcommand(self):
        code, out, _ = run_cli(["--mock", "chat", "Say hello."])
        self.assertEqual(code, 0)
        self.assertIn("SIMULATED", out)

    def test_mock_prints_request_json(self):
        code, out, _ = run_cli(["chat", "--mock", "Hi"])
        self.assertEqual(code, 0)
        self.assertIn("gemini-4-neon", out)
        self.assertIn("thinkingLevel", out)
        self.assertIn('"contents"', out)

    def test_mock_needs_no_key(self):
        # Env has no GEMINI_API_KEY (run_cli strips it); mock must still exit 0.
        code, out, _ = run_cli(["chat", "--mock", "Hi"])
        self.assertEqual(code, 0)
        self.assertNotIn("GEMINI_API_KEY is not set", out)

    def test_mock_deterministic(self):
        _, out1, _ = run_cli(["chat", "--mock", "Say hello in one sentence."])
        _, out2, _ = run_cli(["chat", "--mock", "Say hello in one sentence."])
        self.assertEqual(out1, out2)

    def test_mock_shows_cost_warning(self):
        code, out, _ = run_cli(["chat", "--mock", "Hi"])
        self.assertEqual(code, 0)
        self.assertIn("NO free tier", out)

    def test_mock_thinking_level_passthrough(self):
        code, out, _ = run_cli(
            ["chat", "--mock", "--thinking-level", "low", "Hi"]
        )
        self.assertEqual(code, 0)
        self.assertIn('"thinkingLevel": "low"', out)


class TestMissingKey(unittest.TestCase):
    def test_live_chat_without_key_exits_2(self):
        code, _, err = run_cli(["chat", "Hello"])
        self.assertEqual(code, 2)
        self.assertIn("GEMINI_API_KEY", err)

    def test_live_flag_without_key_exits_2(self):
        code, _, err = run_cli(["chat", "--live", "Hello"])
        self.assertEqual(code, 2)
        self.assertIn("GEMINI_API_KEY", err)

    def test_missing_key_message_names_the_fix(self):
        code, _, err = run_cli(["chat", "Hello"])
        self.assertEqual(code, 2)
        self.assertIn("export GEMINI_API_KEY", err)
        self.assertIn("NO free tier", err)
        # The message must not contain any key value (there is none to leak).
        self.assertNotIn("AIza", err)


if __name__ == "__main__":
    unittest.main()

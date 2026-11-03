#!/usr/bin/env python3
"""Prepare and independently verify an isolated Local Coding Agent coding task."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "workspace"
SOURCE = '''"""Order pricing: discount applies only to goods, never shipping."""
from decimal import Decimal

def total_price(unit_price, quantity, discount_percent=0, shipping=0):
    """Return a two-decimal Decimal total; reject invalid inputs."""
    unit = Decimal(str(unit_price))
    rate = Decimal(str(discount_percent))
    freight = Decimal(str(shipping))
    if unit < 0 or quantity < 0 or rate < 0 or rate > 100 or freight < 0:
        raise ValueError("invalid order")
    subtotal = unit * quantity
    return ((subtotal + freight) * (Decimal("100") - rate) / Decimal("100")).quantize(Decimal("0.01"))
'''
PUBLIC_TEST = '''import unittest
from decimal import Decimal
from calculator import total_price

class OrderTests(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(total_price(100, 3, 0, 10), Decimal("310.00"))

    def test_shipping_not_discounted(self):
        self.assertEqual(total_price(100, 3, 10, 10), Decimal("280.00"))

if __name__ == "__main__":
    unittest.main()
'''
PRIVATE_TEST = '''import unittest
from decimal import Decimal
from calculator import total_price

class IndependentTests(unittest.TestCase):
    def test_shipping_not_discounted(self):
        self.assertEqual(total_price(100, 3, 10, 10), Decimal("280.00"))
    def test_free_shipping(self):
        self.assertEqual(total_price("19.99", 2, 25, 0), Decimal("29.99"))
    def test_full_discount_keeps_shipping(self):
        self.assertEqual(total_price(100, 1, 100, 8), Decimal("8.00"))
    def test_zero_quantity_shipping(self):
        self.assertEqual(total_price(100, 0, 50, 10), Decimal("10.00"))
    def test_invalid_discount(self):
        with self.assertRaises(ValueError):
            total_price(10, 1, 101, 0)
    def test_invalid_shipping(self):
        with self.assertRaises(ValueError):
            total_price(10, 1, 0, -1)

if __name__ == "__main__":
    unittest.main()
'''
PROMPT = """请修复当前 Python 订单计算项目的金额计算错误。规则：折扣只适用于商品小计，运费不参与折扣。示例：单价100元，数量3，折扣10%，运费10元，正确总额280.00元。请先阅读项目文件，定位原因，只修改必要的业务代码，不要修改测试文件，不要跳过测试；自行运行 python -m unittest discover -v，如果失败继续修复，最后报告修改文件、原因和真实测试结果。不要访问工程以外的文件。"""

def setup():
    WORK.mkdir(parents=True, exist_ok=True)
    for name, body in {"calculator.py": SOURCE, "test_calculator.py": PUBLIC_TEST,
                       "README.md": "# Order calculator acceptance fixture\n\nFix the discount bug without editing tests.\n"}.items():
        (WORK / name).write_text(body, encoding="utf-8")
    print("WORKSPACE:", WORK)
    print("PROMPT:\n" + PROMPT)
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-v"], cwd=WORK, capture_output=True, text=True)
    print("BASELINE_EXPECTED_FAIL:", p.returncode != 0)
    print((p.stdout + p.stderr)[-2500:])
    if p.returncode == 0:
        raise SystemExit("Fixture baseline unexpectedly passed")

def verify():
    if not WORK.exists():
        raise SystemExit("Run --setup first")
    checks = {}
    checks["original_public_tests_unchanged"] = (WORK / "test_calculator.py").read_text(encoding="utf-8") == PUBLIC_TEST
    checks["calculator_exists"] = (WORK / "calculator.py").is_file()
    checks["private_test_not_in_workspace"] = not (WORK / "test_independent.py").exists()
    # Execute independent tests from a temporary folder outside the agent workspace.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="lca-independent-") as temp:
        path = Path(temp) / "test_independent.py"
        path.write_text(PRIVATE_TEST, encoding="utf-8")
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = str(WORK)
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", temp, "-v"], cwd=WORK, env=env, capture_output=True, text=True, timeout=30)
        checks["independent_tests_pass"] = p.returncode == 0
        print("INDEPENDENT TEST OUTPUT:\n" + (p.stdout + p.stderr)[-4000:])
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-v"], cwd=WORK, capture_output=True, text=True, timeout=30)
    checks["public_tests_pass"] = p.returncode == 0
    print("PUBLIC TEST OUTPUT:\n" + (p.stdout + p.stderr)[-2500:])
    report = {"passed": all(checks.values()), "checks": checks}
    (ROOT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT:", json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    setup() if args.setup else verify()

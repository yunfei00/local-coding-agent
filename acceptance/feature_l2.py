#!/usr/bin/env python3
"""L2: prepare an isolated feature task and run independent acceptance tests."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "workspace_l2"
SOURCE = '''"""Order pricing with percentage discount and shipping."""
from decimal import Decimal, ROUND_HALF_UP

def total_price(unit_price, quantity, discount_percent=0, shipping=0):
    unit = Decimal(str(unit_price))
    rate = Decimal(str(discount_percent))
    freight = Decimal(str(shipping))
    if unit < 0 or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0 or rate < 0 or rate > 100 or freight < 0:
        raise ValueError("invalid order")
    subtotal = unit * quantity
    goods = subtotal * (Decimal("100") - rate) / Decimal("100")
    return (goods + freight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
'''
PUBLIC = '''import unittest
from decimal import Decimal
from calculator import total_price

class ExistingBehavior(unittest.TestCase):
    def test_discount_and_shipping(self):
        self.assertEqual(total_price(100, 3, 10, 10), Decimal("280.00"))
    def test_no_discount(self):
        self.assertEqual(total_price(50, 2, 0, 5), Decimal("105.00"))
    def test_full_discount_still_shipping(self):
        self.assertEqual(total_price(100, 1, 100, 8), Decimal("8.00"))

if __name__ == "__main__":
    unittest.main()
'''
PRIVATE = '''import unittest
from decimal import Decimal
from calculator import total_price

class FeatureAcceptance(unittest.TestCase):
    def test_eligible_coupon(self):
        self.assertEqual(total_price(100, 3, 10, 10, coupon=30, min_spend=200), Decimal("250.00"))
    def test_below_threshold(self):
        self.assertEqual(total_price(100, 1, 10, 10, coupon=30, min_spend=200), Decimal("100.00"))
    def test_threshold_equal(self):
        self.assertEqual(total_price(100, 2, 0, 5, coupon=20, min_spend=200), Decimal("185.00"))
    def test_coupon_cannot_make_goods_negative(self):
        self.assertEqual(total_price(20, 1, 50, 8, coupon=99, min_spend=0), Decimal("8.00"))
    def test_shipping_not_counted_for_threshold(self):
        self.assertEqual(total_price(90, 1, 0, 100, coupon=20, min_spend=100), Decimal("190.00"))
    def test_discount_then_coupon(self):
        self.assertEqual(total_price(100, 2, 25, 10, coupon=20, min_spend=200), Decimal("140.00"))
    def test_old_signature(self):
        self.assertEqual(total_price(100, 3, 10, 10), Decimal("280.00"))
    def test_coupon_default(self):
        self.assertEqual(total_price(100, 1, 0, 5, coupon=0), Decimal("105.00"))
    def test_invalid_coupon(self):
        with self.assertRaises(ValueError):
            total_price(10, 1, coupon=-1)
    def test_invalid_min_spend(self):
        with self.assertRaises(ValueError):
            total_price(10, 1, min_spend=-1)

if __name__ == "__main__":
    unittest.main()
'''
PROMPT = """请在当前 Python 订单计算项目中新增“满减优惠券”功能。保留现有 total_price(unit_price, quantity, discount_percent=0, shipping=0) 的兼容性，新增两个可选参数 coupon=0 和 min_spend=0。规则：先计算商品小计（单价×数量），按 discount_percent 计算商品折扣；若原始商品小计达到 min_spend，则在折后商品金额中再减去固定金额 coupon，商品金额最低为0；最后加上运费（运费既不参与折扣也不计入满减门槛）。金额返回两位小数 Decimal；coupon 或 min_spend 为负数时抛 ValueError。例：100元×3、折扣10%、运费10、满200减30，最终250.00。请自行阅读工程、实现功能、增加必要的公开单元测试并执行 python -m unittest discover -v；失败时继续修复，最后报告修改文件、测试结果。不要访问工程外文件。"""

def run_public():
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "-v"], cwd=WORK, capture_output=True, text=True, timeout=30)

def setup():
    WORK.mkdir(parents=True, exist_ok=True)
    for name, value in {"calculator.py": SOURCE, "test_calculator.py": PUBLIC,
                        "README.md": "# L2 order coupon feature\n\nImplement coupon and min_spend while retaining original API.\n"}.items():
        (WORK / name).write_text(value, encoding="utf-8")
    result = run_public()
    print("WORKSPACE:", WORK)
    print("BASELINE_EXISTING_TESTS_PASS:", result.returncode == 0)
    print("PROMPT:\n" + PROMPT)
    if result.returncode != 0:
        print(result.stdout + result.stderr)
        raise SystemExit(1)

def verify():
    if not WORK.is_dir():
        raise SystemExit("Run --setup first")
    checks = {
        "original_public_tests_preserved": "class ExistingBehavior" in (WORK / "test_calculator.py").read_text(encoding="utf-8") and all(x in (WORK / "test_calculator.py").read_text(encoding="utf-8") for x in ["test_discount_and_shipping", "test_no_discount", "test_full_discount_still_shipping"]),
        "calculator_exists": (WORK / "calculator.py").is_file(),
        "independent_tests_not_in_workspace": not (WORK / "test_independent_l2.py").exists()
    }
    with tempfile.TemporaryDirectory(prefix="lca-l2-") as tmp:
        (Path(tmp) / "test_independent_l2.py").write_text(PRIVATE, encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(WORK))
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", tmp, "-v"],
                              cwd=WORK, env=env, capture_output=True, text=True, timeout=30)
        checks["independent_tests_pass"] = proc.returncode == 0
        print("INDEPENDENT TESTS:\n" + (proc.stdout + proc.stderr)[-6000:])
    public = run_public()
    checks["public_tests_pass"] = public.returncode == 0
    print("PUBLIC TESTS:\n" + (public.stdout + public.stderr)[-2500:])
    result = {"passed": all(checks.values()), "checks": checks}
    (ROOT / "result_l2.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("RESULT:", json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--setup", action="store_true")
    g.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    setup() if args.setup else verify()

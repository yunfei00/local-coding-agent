"""Independent coupon acceptance; never writes Agent implementation or tests."""
import sys
import unittest
from datetime import date
from decimal import Decimal


class CouponContract(unittest.TestCase):
    def apply(self, amount=100, **coupon):
        from coupon_engine import apply_coupon
        return apply_coupon(amount, {'type':'fixed','value':10, **coupon}, date(2026,11,3))

    def test_fixed(self): self.assertEqual(self.apply(), Decimal('90.00'))
    def test_percent(self): self.assertEqual(self.apply(type='percent',value=20), Decimal('80.00'))
    def test_threshold(self): self.assertEqual(self.apply(min_spend=101), Decimal('100.00'))
    def test_threshold_equal(self): self.assertEqual(self.apply(min_spend=100), Decimal('90.00'))
    def test_cap(self): self.assertEqual(self.apply(type='percent',value=50,max_discount=15), Decimal('85.00'))
    def test_expired(self): self.assertEqual(self.apply(expires='2026-11-02'), Decimal('100.00'))
    def test_expiry_inclusive(self): self.assertEqual(self.apply(expires='2026-11-03'), Decimal('90.00'))
    def test_floor(self): self.assertEqual(self.apply(value=200), Decimal('0.00'))
    def test_money(self): self.assertIsInstance(self.apply(), Decimal)
    def test_invalid_amount(self):
        for value in [-1,True,'nan','Infinity',None]:
            with self.subTest(value=value), self.assertRaises(ValueError): self.apply(amount=value)
    def test_invalid_coupon(self):
        for coupon in [dict(value=-1),dict(type='unknown'),dict(type='percent',value=101),
                       dict(min_spend=-1),dict(max_discount=-1),dict(expires='invalid'),dict(value=True)]:
            with self.subTest(coupon=coupon), self.assertRaises(ValueError): self.apply(**coupon)
    def test_no_stacking(self):
        from coupon_engine import apply_coupons
        with self.assertRaises(ValueError):
            apply_coupons(100,[{'type':'fixed','value':10}]*2,date(2026,11,3))


if __name__ == '__main__':
    sys.path.insert(0,sys.argv.pop(1))
    unittest.main()

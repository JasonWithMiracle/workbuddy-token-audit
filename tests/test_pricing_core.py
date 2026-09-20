# -*- coding: utf-8 -*-
"""
计价核心单元测试
运行：python -m unittest discover -s tests -v
"""
import os, sys, json, datetime, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

import pricing_core as pc   # noqa: E402

ASSETS = os.path.join(SKILL_ROOT, "assets")
BJ = pc.BJ


def ts_of(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=BJ).timestamp()


class TestLookup(unittest.TestCase):
    """价格表匹配优先级：精确 → 最长前缀 → 包含"""

    def setUp(self):
        self.models = {
            "hy3": {"kind": "flat", "price": [1, 4, 0.25]},
            "hy": {"kind": "flat", "price": [9, 9, 9]},
            "deepseek-v4-flash": {"kind": "split", "peak": [2, 8, 0.04], "off": [1, 4, 0.02]},
            "deepseek-v4": {"kind": "flat", "price": [99, 99, 99]},
        }

    def test_exact(self):
        self.assertEqual(pc.lookup(self.models, "hy3")["price"], [1, 4, 0.25])

    def test_longest_prefix_wins(self):
        # hy3-x 应命中 hy3（更长）而不是 hy
        self.assertEqual(pc.lookup(self.models, "hy3-x")["price"], [1, 4, 0.25])

    def test_prefix(self):
        self.assertEqual(pc.lookup(self.models, "deepseek-v4-flash-vision")["kind"], "split")

    def test_contains_fallback(self):
        self.assertIsNotNone(pc.lookup(self.models, "vendor/hy3-turbo"))

    def test_miss(self):
        self.assertIsNone(pc.lookup(self.models, "totally-unknown-model"))

    def test_empty_table(self):
        self.assertIsNone(pc.lookup({}, "hy3"))


class TestWorkday(unittest.TestCase):
    """工作日判定：调休上班日 → 法定放假日 → 周一至周五"""

    def setUp(self):
        self.cals = pc.load_calendars(ASSETS, [2026])
        self.wd = pc.make_workday_fn(self.cals)

    def test_plain_weekday(self):
        self.assertTrue(self.wd(datetime.datetime(2026, 9, 17)))   # 周四

    def test_plain_weekend(self):
        self.assertFalse(self.wd(datetime.datetime(2026, 9, 19)))  # 周六

    def test_makeup_sunday_is_workday(self):
        # 2026-09-20 是周日，但为国庆调休上班日
        self.assertTrue(self.wd(datetime.datetime(2026, 9, 20)))

    def test_holiday_weekday_is_off(self):
        # 2026-10-01 周四，但为国庆法定假日
        self.assertFalse(self.wd(datetime.datetime(2026, 10, 1)))

    def test_spring_festival_range(self):
        for d in range(15, 24):
            self.assertFalse(self.wd(datetime.datetime(2026, 2, d)), f"2026-02-{d} 应为假日")

    def test_missing_year_falls_back(self):
        wd = pc.make_workday_fn({})
        self.assertTrue(wd(datetime.datetime(2026, 9, 17)))
        self.assertFalse(wd(datetime.datetime(2026, 9, 19)))


class TestPeak(unittest.TestCase):
    """峰谷判定：工作日 09:00-12:00、14:00-18:00"""

    def setUp(self):
        self.wd = pc.make_workday_fn(pc.load_calendars(ASSETS, [2026]))

    def test_workday_peak_morning(self):
        self.assertTrue(pc.is_peak(ts_of(2026, 9, 17, 9, 30), self.wd))

    def test_workday_boundary_9_inclusive(self):
        self.assertTrue(pc.is_peak(ts_of(2026, 9, 17, 9, 0), self.wd))

    def test_workday_boundary_12_exclusive(self):
        self.assertFalse(pc.is_peak(ts_of(2026, 9, 17, 12, 0), self.wd))

    def test_workday_lunch_off(self):
        self.assertFalse(pc.is_peak(ts_of(2026, 9, 17, 13, 0), self.wd))

    def test_workday_afternoon_peak(self):
        self.assertTrue(pc.is_peak(ts_of(2026, 9, 17, 17, 59), self.wd))

    def test_workday_evening_off(self):
        self.assertFalse(pc.is_peak(ts_of(2026, 9, 17, 20, 0), self.wd))

    def test_weekend_never_peak(self):
        for h in range(24):
            self.assertFalse(pc.is_peak(ts_of(2026, 9, 19, h, 0), self.wd),
                             f"周六 {h} 点不应为高峰")

    def test_holiday_never_peak(self):
        self.assertFalse(pc.is_peak(ts_of(2026, 10, 1, 10, 0), self.wd))

    def test_makeup_sunday_has_peak(self):
        # 调休上班日 2026-09-20（周日）应有高峰
        self.assertTrue(pc.is_peak(ts_of(2026, 9, 20, 10, 0), self.wd))


class TestTier(unittest.TestCase):
    """智谱分段判档"""

    def setUp(self):
        self.entry = {
            "kind": "tiered",
            "tiers": [
                {"in_max": 32768, "out_max": 200, "price": [2, 8, 0.4]},
                {"in_max": 32768, "out_max": None, "price": [3, 14, 0.6]},
                {"in_max": 204800, "out_max": None, "price": [4, 16, 0.8]},
            ],
        }

    def test_low_in_low_out(self):
        self.assertEqual(pc.pick_tier(self.entry, 1000, 100), [2, 8, 0.4])

    def test_low_in_high_out(self):
        self.assertEqual(pc.pick_tier(self.entry, 1000, 300), [3, 14, 0.6])

    def test_high_in(self):
        self.assertEqual(pc.pick_tier(self.entry, 50000, 300), [4, 16, 0.8])

    def test_boundary_in_max(self):
        self.assertEqual(pc.pick_tier(self.entry, 32768, 100), [2, 8, 0.4])

    def test_over_all_tiers_uses_last(self):
        self.assertEqual(pc.pick_tier(self.entry, 999999, 999999), [4, 16, 0.8])

    def test_empty_tiers(self):
        self.assertIsNone(pc.pick_tier({"tiers": []}, 100, 100))


class TestCost(unittest.TestCase):
    """成本公式与缓存分档"""

    def test_no_cache(self):
        # 1M 输入(无缓存) + 1M 输出，价 [1, 4, 0.25] → 1*1 + 4*1 = 5
        self.assertAlmostEqual(pc.calc_cost(1_000_000, 1_000_000, 0, 0, [1, 4, 0.25]), 5.0)

    def test_all_cache_hit(self):
        # 1M 输入全部缓存命中 + 无输出 → 0.25
        self.assertAlmostEqual(pc.calc_cost(1_000_000, 0, 1_000_000, 0, [1, 4, 0.25]), 0.25)

    def test_mixed_cache(self):
        # 500k 未命中 + 500k 命中
        expect = (500_000 * 1 + 500_000 * 0.25) / 1e6
        self.assertAlmostEqual(pc.calc_cost(1_000_000, 0, 500_000, 0, [1, 4, 0.25]), expect)

    def test_cache_write_penalty(self):
        # 缓存写入按输入价 1.25 倍
        expect = (1_000_000 * 1 * 1.25) / 1e6
        self.assertAlmostEqual(pc.calc_cost(1_000_000, 0, 0, 1_000_000, [1, 4, 0.25]), expect)

    def test_cache_over_input_is_clamped(self):
        # 缓存数超过输入时不应产生负成本
        c = pc.calc_cost(100, 0, 999, 0, [1, 4, 0.25])
        self.assertGreaterEqual(c, 0.0)

    def test_zero_price_is_free(self):
        self.assertEqual(pc.calc_cost(1_000_000, 1_000_000, 0, 0, [0, 0, 0]), 0.0)


class TestSafeDiv(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(pc.safe_div(10, 4), 2.5)

    def test_zero_denominator(self):
        self.assertEqual(pc.safe_div(10, 0), 0.0)

    def test_none_denominator(self):
        self.assertEqual(pc.safe_div(10, None), 0.0)

    def test_custom_default(self):
        self.assertEqual(pc.safe_div(10, 0, default=-1), -1)


class TestRealPriceTable(unittest.TestCase):
    """对随仓库分发的真实价格表做契约检查"""

    def setUp(self):
        self.models = pc.load_price_models(ASSETS)

    def test_table_not_empty(self):
        self.assertGreater(len(self.models), 0, "价格表为空")

    def test_every_entry_has_kind_and_price(self):
        for k, v in self.models.items():
            kind = v.get("kind")
            self.assertIn(kind, ("flat", "split", "tiered"), f"{k} 的 kind 非法: {kind}")
            if kind == "flat":
                self.assertEqual(len(v.get("price") or []), 3, f"{k} 固定价应为 3 元组")
            elif kind == "split":
                self.assertEqual(len(v.get("peak") or []), 3, f"{k} 高峰价应为 3 元组")
                self.assertEqual(len(v.get("off") or []), 3, f"{k} 空闲价应为 3 元组")
            else:
                self.assertTrue(v.get("tiers"), f"{k} 分段表为空")

    def test_split_price_relationship(self):
        """DeepSeek 系：高峰价 = 空闲价 × 2"""
        for k, v in self.models.items():
            if v.get("kind") != "split":
                continue
            for i in range(3):
                self.assertAlmostEqual(v["peak"][i], v["off"][i] * 2, places=6,
                                       msg=f"{k} 第 {i} 项不满足 高峰=空闲×2")

    def test_deepseek_flash_known_price(self):
        e = pc.lookup(self.models, "deepseek-v4.1-flash")
        self.assertIsNotNone(e)
        self.assertEqual(e["peak"], [2, 8, 0.04])
        self.assertEqual(e["off"], [1, 4, 0.02])

    def test_minimax_corrected_price(self):
        """回归测试：MiniMax-M3 曾误用高一倍的价"""
        e = pc.lookup(self.models, "MiniMaxAI/MiniMax-M3")
        self.assertIsNotNone(e)
        self.assertEqual(e["price"], [2.1, 8.4, 0.42])


class TestRealCalendar(unittest.TestCase):
    def setUp(self):
        self.cals = pc.load_calendars(ASSETS, [2026])
        self.cal = self.cals.get(2026) or {}

    def test_calendar_present(self):
        self.assertTrue(self.cal, "缺少 2026 年日历")

    def test_calendar_has_source(self):
        self.assertIn("source", self.cal)
        self.assertIn("published_at", self.cal["source"])

    def test_seven_holiday_blocks(self):
        hol = self.cal.get("holidays") or {}
        self.assertGreaterEqual(len(hol), 33, "2026 年法定放假日应不少于 33 天")

    def test_expected_makeup_days(self):
        mk = set((self.cal.get("makeup_workdays") or {}).keys())
        expect = {"2026-01-04", "2026-02-14", "2026-02-28",
                  "2026-05-09", "2026-09-20", "2026-10-10"}
        self.assertEqual(mk, expect, "调休上班日集合与国办通知不一致")


if __name__ == "__main__":
    unittest.main(verbosity=2)

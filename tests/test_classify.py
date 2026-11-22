"""规则分类器的单测：不需要安装任何依赖，也不 import 采集器。

跑法：python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.classify import UNCLASSIFIED, categories, classify


class TestClassify(unittest.TestCase):
    def test_categories_order(self):
        self.assertEqual(categories(), ["影视解说", "情绪共鸣", "生活消费", "技能学习", UNCLASSIFIED])

    def test_movie(self):
        cat, score = classify("一部悬疑片的三条叙事线，第二次看才懂", "影评小站")
        self.assertEqual(cat, "影视解说")
        self.assertGreater(score, 0)

    def test_emotion(self):
        cat, _ = classify("成年人的内耗，往往从一句「我没事」开始", "树洞频道")
        self.assertEqual(cat, "情绪共鸣")

    def test_life(self):
        cat, _ = classify("探店：开在老小区的咖啡店", "街头食记")
        self.assertEqual(cat, "生活消费")

    def test_skill_with_tag_and_case(self):
        # 大小写不敏感：Python 与 python 等价
        cat, score = classify("Python 处理表格：把手工复制粘贴换掉", "代码小工具")
        self.assertEqual(cat, "技能学习")
        self.assertGreaterEqual(score, 1)

    def test_unclassified(self):
        cat, score = classify("周末随手记", "无名")
        self.assertEqual(cat, UNCLASSIFIED)
        self.assertEqual(score, 0)

    def test_tie_goes_to_narrower_category(self):
        # 「电影」与「美食」各命中 1 次，并列时按 RULES 顺序归更窄的类目
        cat, score = classify("电影里的美食镜头", "")
        self.assertEqual(cat, "影视解说")
        self.assertEqual(score, 1)

    def test_more_hits_wins(self):
        # 多个强特征词同时出现时，命中多的类目胜出
        cat, score = classify("减脂健身训练计划：四周课程", "")
        self.assertEqual(cat, "技能学习")
        self.assertGreaterEqual(score, 3)


if __name__ == "__main__":
    unittest.main()

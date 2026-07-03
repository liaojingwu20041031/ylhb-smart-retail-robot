import os
import unittest

from ylhb_llm.product_catalog import ProductCatalog
from ylhb_llm.retail_task_node import RetailTaskNode


class B1RecommendationSpeechTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        products_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'config', 'products.yaml')
        )
        cls.catalog = ProductCatalog.from_yaml(products_path)

    def test_hungry_image_speech_does_not_recommend_before_shelf_vlm(self):
        node = RetailTaskNode.__new__(RetailTaskNode)
        node.catalog = self.catalog

        speech = node.build_b1_image_speech({
            'description_cn': '图片中的人物看起来有些饿，可能想吃点东西。',
            'need': 'hungry',
            'preferred_categories': ['零食'],
        })

        self.assertIn('图片中的人物看起来有些饿', speech)
        self.assertNotIn('薯片', speech)
        self.assertNotIn('推荐', speech)


if __name__ == '__main__':
    unittest.main()

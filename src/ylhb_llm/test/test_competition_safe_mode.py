import os
import time
import unittest

from ylhb_llm.product_catalog import ProductCatalog
from ylhb_llm.retail_task_node import RetailTaskNode
from ylhb_llm.vlm_recognition_nodes import VlmShelfRecognitionNode


class CompetitionSafeModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        products_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'config', 'products.yaml')
        )
        cls.catalog = ProductCatalog.from_yaml(products_path)

    def make_task_node(self):
        node = RetailTaskNode.__new__(RetailTaskNode)
        node.catalog = self.catalog
        node.shelf_snapshot_ttl_sec = 15.0
        return node

    def test_b1_recommendation_uses_only_shelf_products(self):
        node = self.make_task_node()
        node.shelf_updated_at = time.monotonic()
        node.shelf_products = [
            (self.catalog.get('water_nongfu'), {'confidence': 0.9}),
        ]

        product, reason = node.choose_product_from_shelf({
            'need': 'hungry',
            'preferred_categories': ['零食'],
        })

        self.assertIsNone(product)
        self.assertEqual(reason, 'no matching shelf product')

    def test_b1_empty_shelf_does_not_fallback_to_catalog(self):
        node = self.make_task_node()
        node.shelf_updated_at = time.monotonic()
        node.shelf_products = []

        product, _reason = node.choose_product_from_shelf({
            'need': 'hungry',
            'preferred_categories': ['零食'],
        })

        self.assertIsNone(product)

    def test_checkout_quantity_uses_vlm_quantity_field(self):
        node = self.make_task_node()
        node.latest_detected_updated_at = time.monotonic()
        node.latest_detected_products = [
            (self.catalog.get('cola_coca'), {'quantity': 2, 'confidence': 0.9}),
            (self.catalog.get('cola_coca'), {'quantity': 1, 'confidence': 0.8}),
        ]

        items = node.checkout_items_from_latest_detection()

        self.assertEqual(items['cola_coca']['quantity'], 3)

    def test_vlm_filter_keeps_only_known_products(self):
        node = VlmShelfRecognitionNode.__new__(VlmShelfRecognitionNode)
        node.catalog = self.catalog

        objects = VlmShelfRecognitionNode.filter_objects(node, [
            {'name': '可口可乐', 'quantity': 2, 'confidence': 0.91},
            {'name': '不存在商品', 'quantity': 1, 'confidence': 0.99},
        ])

        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]['item_id'], 'cola_coca')
        self.assertEqual(objects[0]['quantity'], 2)


if __name__ == '__main__':
    unittest.main()

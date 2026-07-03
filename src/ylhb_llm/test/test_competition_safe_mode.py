import os
import tempfile
import time
import unittest
from types import SimpleNamespace

from ylhb_llm.product_catalog import ProductCatalog
from ylhb_llm.retail_competition_executor_node import RetailCompetitionExecutorNode
from ylhb_llm.retail_task_node import RetailTaskNode
from ylhb_llm.vlm_recognition_nodes import VlmRecognitionNode, VlmShelfRecognitionNode


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
        node.shelf_products = []
        node.latest_detected_products = []
        node.shelf_updated_at = 0.0
        node.latest_detected_updated_at = 0.0
        node.shelf_products_by_task = {}
        node.checkout_products_by_task = {}
        node.shelf_updated_at_by_task = {}
        node.checkout_updated_at_by_task = {}
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

    def test_b1_recommendation_waits_for_shelf_recognition_success(self):
        node = self.make_task_node()
        calls = []
        node.pending_tasks = {'t1': {'workflow': 'task_b_1_recommend', 'raw': {}}}
        node.say = lambda *args, **kwargs: None
        node.handle_shelf_inspection_succeeded = lambda *args: calls.append(args)

        node.task_status_callback(SimpleNamespace(task_id='t1', status='succeeded', stage='navigate_a', reason=''))
        self.assertEqual(calls, [])

        node.task_status_callback(SimpleNamespace(task_id='t1', status='succeeded', stage='shelf_recognition', reason=''))
        self.assertEqual(len(calls), 1)

    def test_b2_finishes_only_after_return_start(self):
        node = self.make_task_node()
        product = self.catalog.get('cola_coca')
        node.pending_tasks = {'t2': {'workflow': 'task_b_2', 'product': product}}
        node.completed_task_ids = set()
        node.cart_items = {}
        node.say = lambda *args, **kwargs: None
        node.publish_cart = lambda: None

        node.task_status_callback(SimpleNamespace(task_id='t2', status='succeeded', stage='navigate_a', reason=''))
        self.assertIn('t2', node.pending_tasks)
        self.assertEqual(node.cart_items, {})

        node.task_status_callback(SimpleNamespace(task_id='t2', status='succeeded', stage='arm_place', reason=''))
        self.assertIn('t2', node.pending_tasks)
        self.assertEqual(node.cart_items['cola_coca']['quantity'], 1)

        node.task_status_callback(SimpleNamespace(task_id='t2', status='succeeded', stage='return_start', reason=''))
        self.assertNotIn('t2', node.pending_tasks)
        self.assertIn('t2', node.completed_task_ids)

    def test_checkout_reads_current_task_only_on_success(self):
        node = self.make_task_node()
        node.pending_tasks = {'c1': {'workflow': 'task_c_checkout', 'raw': {}}}
        node.checkout_updated_at_by_task = {'c1': time.monotonic()}
        node.checkout_products_by_task = {
            'c1': [(self.catalog.get('water_nongfu'), {'quantity': 1})],
            'old': [(self.catalog.get('cola_coca'), {'quantity': 4})],
        }
        node.say = lambda *args, **kwargs: None
        node.publish_cart_from_items = lambda items: setattr(node, 'last_checkout_items', items)
        node.publish_task_event = lambda *args, **kwargs: None

        node.task_status_callback(SimpleNamespace(task_id='c1', status='request_sent', stage='checkout_inspect', reason=''))
        self.assertFalse(hasattr(node, 'last_checkout_items'))

        node.task_status_callback(SimpleNamespace(task_id='c1', status='succeeded', stage='checkout_inspect', reason=''))
        self.assertEqual(set(node.last_checkout_items), {'water_nongfu'})

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

    def test_executor_routes_b1_image_pick_without_a_or_s(self):
        node = RetailCompetitionExecutorNode.__new__(RetailCompetitionExecutorNode)
        node.busy = False
        calls = []
        node.start_workflow = lambda msg, points, **kwargs: calls.append((points, kwargs))
        event = SimpleNamespace(
            task_id='b1',
            intent='pick_item',
            source='image',
            raw_json='{"flow":"task_b_1"}',
        )

        node.task_event_callback(event)

        self.assertEqual(calls[0][0], ['B'])
        self.assertTrue(calls[0][1]['arm'])

    def test_executor_routes_b2_pick_through_a_b_s(self):
        node = RetailCompetitionExecutorNode.__new__(RetailCompetitionExecutorNode)
        node.busy = False
        calls = []
        node.start_workflow = lambda msg, points, **kwargs: calls.append((points, kwargs))
        event = SimpleNamespace(
            task_id='b2',
            intent='pick_item',
            source='voice',
            raw_json='{"flow":"task_b_2"}',
        )

        node.task_event_callback(event)

        self.assertEqual(calls[0][0], ['A', 'B', 'S'])
        self.assertTrue(calls[0][1]['inspect_shelf'])

    def test_executor_does_not_fake_vlm_success(self):
        node = RetailCompetitionExecutorNode.__new__(RetailCompetitionExecutorNode)
        node.busy = False
        node.stage_pause_sec = 0.0
        node.navigate_to = lambda point, task_id: True
        node.vlm_shelf_pub = object()
        statuses = []
        node.publish_status = lambda task_id, stage, status, reason: statuses.append((stage, status))
        node.publish_vlm_request = lambda *args: None
        node.arm_stage = lambda task_id, stage: statuses.append((stage, 'succeeded'))

        node.run_workflow(SimpleNamespace(task_id='b2'), ['A', 'B', 'S'], inspect_shelf=True, arm=True)

        self.assertIn(('shelf_recognition', 'request_sent'), statuses)
        self.assertNotIn(('shelf_recognition', 'succeeded'), statuses)

    def test_vlm_debug_image_path_is_used_without_delete(self):
        node = VlmRecognitionNode.__new__(VlmRecognitionNode)
        fd, path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        try:
            node.debug_image_path = path
            node.latest_image = None
            image_path, remove_image = node.image_path_for_request()
            self.assertEqual(image_path, path)
            self.assertFalse(remove_image)
            self.assertTrue(os.path.exists(path))
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()

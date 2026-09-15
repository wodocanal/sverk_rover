import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rover_configuration import (
    node_parameters, read_config, resolve_runtime_references,
)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.lookup = patch('rover_configuration.package_path',
                            side_effect=lambda pkg, *parts: str(self.root.joinpath(pkg, *parts)))
        self.lookup.start()
        self.addCleanup(self.lookup.stop)

    def yaml(self, package, text):
        path = self.root / package / 'config' / 'default.yaml'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_typed_reference_and_package_path(self):
        self.yaml('source', 'value: 0.03\nitems: [3, 1, 2, 0]\nenabled: true\n')
        path = self.yaml('consumer', '''node:
  ros__parameters:
    radius: package://source/config/default.yaml#value
    order: package://source/config/default.yaml#items
    enabled: package://source/config/default.yaml#enabled
    path: package://source/config/default.yaml
''')
        params = node_parameters(path, 'node')
        self.assertIsInstance(params['radius'], float)
        self.assertEqual(params['order'], [3, 1, 2, 0])
        self.assertIs(params['enabled'], True)
        self.assertEqual(params['path'], str(self.root/'source/config/default.yaml'))

    def test_configuration_is_reread_after_edit(self):
        target = self.yaml('source', 'value: 1\n')
        consumer = self.yaml('consumer', 'value: package://source/config/default.yaml#value\n')
        self.assertEqual(read_config(consumer)['value'], 1)
        target.write_text('value: 2\n')
        self.assertEqual(read_config(consumer)['value'], 2)

    def test_missing_reference_fails_instead_of_using_defaults(self):
        self.yaml('source', 'value: 1\n')
        path = self.yaml('consumer', 'value: package://source/config/default.yaml#missing\n')
        with self.assertRaisesRegex(KeyError, 'Unknown config reference'):
            read_config(path)

    def test_reference_cycle_fails(self):
        path = self.yaml('a', 'value: package://b/config/default.yaml#value\n')
        self.yaml('b', 'value: package://a/config/default.yaml#value\n')
        with self.assertRaisesRegex(ValueError, 'Cyclic config reference'):
            read_config(path)

    def test_path_traversal_is_rejected(self):
        path = self.yaml('consumer', 'value: package://source/../secret\n')
        with self.assertRaisesRegex(ValueError, 'Invalid package reference'):
            read_config(path)

    def test_wrong_yaml_schema_fails(self):
        path = self.yaml('consumer', '- not a mapping\n')
        with self.assertRaisesRegex(ValueError, 'Expected a YAML mapping'):
            read_config(path)

    def test_runtime_reference_and_environment(self):
        with patch.dict(os.environ, {'ROVER_TEST_VALUE': 'sample'}):
            self.assertEqual(resolve_runtime_references({
                'name': '@env.ROVER_TEST_VALUE', 'port': '@mcp.port',
            }, {'mcp': {'port': 8766}}), {'name': 'sample', 'port': 8766})

    def test_missing_node_section_fails(self):
        path = self.yaml('consumer', 'other: {}\n')
        with self.assertRaisesRegex(ValueError, 'ros__parameters'):
            node_parameters(path, 'node')


if __name__ == '__main__':
    unittest.main()

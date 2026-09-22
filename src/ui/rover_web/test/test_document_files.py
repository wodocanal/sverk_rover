from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from rover_web.web_gateway_node import RoverWebGateway


@pytest.mark.parametrize('name', ['web.yaml', 'default.example.yaml'])
def test_document_directory_defaults_to_docs(name):
    config_dir = Path(__file__).resolve().parents[1] / 'config'
    config = yaml.safe_load((config_dir / name).read_text())
    parameters = config['web_gateway_node']['ros__parameters']
    assert parameters['hackathon_files_root'] == '~/sverk_rover/docs'


def test_document_browser_reads_docs_and_blocks_parent_paths(tmp_path):
    docs = tmp_path / 'docs'
    docs.mkdir()
    document = docs / 'manual.pdf'
    document.write_bytes(b'%PDF-1.4\n')
    outside = tmp_path / 'outside.pdf'
    outside.write_bytes(b'%PDF-1.4\n')
    node = SimpleNamespace(hackathon_files_root=docs)
    payload = RoverWebGateway.hackathon_files_payload(node)
    assert payload['root'] == str(docs)
    assert [item['path'] for item in payload['files']] == ['manual.pdf']
    assert RoverWebGateway._resolve_hackathon_file(node, 'manual.pdf') == document
    with pytest.raises(PermissionError):
        RoverWebGateway._resolve_hackathon_file(node, '../outside.pdf')

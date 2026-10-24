"""Exercise the actual SDK stdio transport with a disposable synthetic chart."""
import json
import tempfile
import unittest
from pathlib import Path
import sys

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    'rpe_capabilities', 'rpe_list_projects', 'rpe_open_project',
    'rpe_get_segment', 'rpe_propose_patch', 'rpe_validate_patch',
    'rpe_preview_diff', 'rpe_commit_patch',
}


def payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(''.join(item.text for item in result.content if item.type == 'text'))


class TestStdioMCP(unittest.TestCase):
    def test_tools_and_unapproved_commit(self):
        anyio.run(self.exercise_stdio)

    async def exercise_stdio(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'test.json'
            original = (ROOT / 'fixtures/rpe_minimal.json').read_bytes()
            source.write_bytes(original)
            parameters = StdioServerParameters(
                command=sys.executable,
                args=['-B', '-m', 'pamos_mcp.server'],
                cwd=ROOT,
                env={'PAMOs_RPE_WORKSPACE': directory, 'PYTHONIOENCODING': 'utf-8'},
            )
            with anyio.fail_after(30):
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=10) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        self.assertEqual({tool.name for tool in listing.tools}, TOOLS)
                        capabilities = await session.call_tool('rpe_capabilities')
                        self.assertFalse(capabilities.is_error)
                        self.assertFalse(payload(capabilities)['live_rpe_next'])
                        self.assertFalse(payload(capabilities)['noise_write'])
                        opened = await session.call_tool('rpe_open_project', {
                            'project_id': 'test.json', 'chart_mode': 'pure_keys', 'key_count': 4,
                        })
                        self.assertFalse(opened.is_error)
                        proposed = await session.call_tool('rpe_propose_patch', {
                            'project_id': 'test.json',
                            'expected_revision': payload(opened)['revision'],
                            'chart_mode': 'pure_keys', 'key_count': 4,
                            'operations': [{'op': 'MOVE_NOTE_LANE', 'note_ref': 'l0:n0', 'value': 1}],
                        })
                        self.assertFalse(proposed.is_error)
                        proposal = {'proposal_id': payload(proposed)['proposal_id']}
                        validated = await session.call_tool('rpe_validate_patch', proposal)
                        self.assertFalse(validated.is_error)
                        previewed = await session.call_tool('rpe_preview_diff', proposal)
                        self.assertFalse(previewed.is_error)
                        rejected = await session.call_tool('rpe_commit_patch', proposal)
                        # SDK masks exception details; core tests check the specific reason.
                        self.assertTrue(rejected.is_error)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list((Path(directory) / '.pamos_state/candidates').glob('*.json')), [])


if __name__ == '__main__':
    unittest.main()

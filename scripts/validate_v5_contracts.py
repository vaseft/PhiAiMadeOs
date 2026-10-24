"""V5 contract-only check. Does NOT prove live MCP/GUI/Phira Pro functionality."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator, RefResolver

ROOT=Path(__file__).resolve().parents[1]
def data(rel):return json.loads((ROOT/rel).read_text(encoding='utf-8'))
schema=data('schemas/rpe_mcp_patch_request.schema.json')
Draft202012Validator.check_schema(schema)
patch_schema=data('schemas/llm_patch.schema.json')
v=Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store={
 'llm_patch.schema.json':patch_schema, (ROOT/'schemas/llm_patch.schema.json').as_uri():patch_schema
}))
ok=data('examples/rpe_mcp_patch_pure4k.json')
assert not list(v.iter_errors(ok)), [str(e) for e in v.iter_errors(ok)]
bad=data('examples/rpe_mcp_patch_invalid_noise.json')
assert list(v.iter_errors(bad)), 'noise write must be rejected'
assert list(v.iter_errors({**ok,'operations':ok['operations']*13})), 'batch limit expected'
assert list(v.iter_errors({**ok,'format_adapter':'unknown'})), 'adapter must be constrained'
for path in [
 'docs/26_RPE_NEXT_MCP_ARCHITECTURE.md','docs/27_RPE_MCP_TOOL_CONTRACTS.md',
 'docs/28_GITHUB_VERSION_CONTROL.md','docs/29_LLM_MCP_INTERACTION_GUIDE.md',
 'docs/30_V5_ACCEPTANCE_AND_GITHUB_LINK.md',
 'prompts/PAMOS_RPE_MCP_EDITOR_SYSTEM_ZH.md',
 'prompts/LLM_CHART_REFINER_SYSTEM_ZH.md',
 'configs/mcp_bridge_v5.example.yaml','.github/workflows/ci.yml'
]:
 assert (ROOT/path).exists(),f'missing {path}'
a=(ROOT/'prompts/PAMOS_RPE_MCP_EDITOR_SYSTEM_ZH.md').read_text(encoding='utf-8')
assert all(s in a for s in ['noise_area','rpe_capabilities','rpe_commit_patch','pure_keys','审计','GitHub'])
print('PAMOs V5 MCP/schema/prompts/GitHub-CI static checks: PASS (not live integration)')

# SPDX-License-Identifier: GPL-3.0-only
"""Minimal MCP v2 stdio server for OFFLINE RPE JSON/PEZ proposals.

Install: pip install 'mcp>=2,<3'
Run: PAMOs_RPE_WORKSPACE=/path/to/authorized/charts python -m pamos_mcp.server
All tools are scoped to the workspace root. Live RPE Next editor commit is not implemented.
"""
import os
from pathlib import Path
from mcp.server import MCPServer
from .core import Workspace, RPEError

ROOT=os.environ.get('PAMOs_RPE_WORKSPACE')
if not ROOT:
    raise RuntimeError('PAMOs_RPE_WORKSPACE must point to a dedicated authorized data directory')
ws=Workspace(Path(ROOT))
app=MCPServer('PhiAiMadeOs RPE offline safe edit')

@app.tool()
def rpe_capabilities()->dict:
    """Read capabilities. This prototype supports offline JSON and PEZ input, not live RPE Next GUI editing."""
    return {'formats_in':['rpe_original_json','rpe_next_json','rpe_original_pez','rpe_next_pez'],
            'formats_out':['candidate_json_only'],'tools':['list','open','segment','propose','validate','preview','candidate_commit'],
            'live_rpe_next':False,'rpe_original_live':False,'noise_write':False,
            'supported_ops':['SHIFT_NOTE_BEATS','SET_NOTE_X','SET_NOTE_TYPE','SET_HOLD_END','MOVE_NOTE_LANE'],
            'warning':'Dual-format import means supported common structure; NOT certified lossless original/next conversion'}

@app.tool()
def rpe_list_projects()->list[str]:
    """Enumerate only files directly inside the approved PAMOs_RPE_WORKSPACE."""
    return ws.projects()

@app.tool()
def rpe_open_project(project_id:str,chart_mode:str='regular',key_count:int|None=None)->dict:
    """Check and hash a local RPE JSON/PEZ without modifying it."""
    s=ws.open(project_id,chart_mode,key_count)
    return {'project_id':s.name,'revision':s.revision,'format':'pez' if s.archive_member else 'json',
            'rpe_version':s.chart['META'].get('RPEVersion'),'num_lines':len(s.chart['judgeLineList']),
            'live_editor':'NOT_CONNECTED'}

@app.tool()
def rpe_get_segment(project_id:str,start_beat:list[int],end_beat:list[int],max_notes:int=128)->dict:
    """Read a bounded beat window, with stable-on-revision line:note refs."""
    s=ws.open(project_id)
    return ws.get_segment(s,start_beat,end_beat,max_notes)

@app.tool()
def rpe_propose_patch(project_id:str,expected_revision:str,operations:list[dict],chart_mode:str='regular',key_count:int|None=None)->dict:
    """Propose whitelist-only edits. Nothing is saved or applied."""
    s=ws.open(project_id,chart_mode,key_count)
    if s.revision!=expected_revision:raise RPEError('REVISION_CONFLICT')
    return ws.propose(s,operations,chart_mode,key_count)

@app.tool()
def rpe_validate_patch(proposal_id:str)->dict:
    """Check the patch and revision deterministically. Audio DSP remains a separate step."""
    return ws.validate(proposal_id)

@app.tool()
def rpe_preview_diff(proposal_id:str)->dict:
    """Return proposed operations for human review without applying."""
    return ws.preview(proposal_id)

@app.tool()
def rpe_commit_patch(proposal_id:str)->dict:
    """Write a NEW candidate JSON file only when manually approved in a local terminal.
    Never overwrites source. Does not commit to a live editor or certify Phira playability.
    """
    return ws.commit_candidate(proposal_id)

if __name__=='__main__':
    app.run(transport='stdio')

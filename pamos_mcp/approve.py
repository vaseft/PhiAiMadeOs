# SPDX-License-Identifier: GPL-3.0-only
"""Human-only, interactive approval entrypoint; never expose via MCP."""
import argparse
from pathlib import Path
from .core import Workspace

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workspace',required=True)
    p.add_argument('--proposal',required=True)
    args=p.parse_args()
    ws=Workspace(Path(args.workspace))
    print('查看原始谱面及变更摘要：',ws.preview(args.proposal))
    print('仅批准生成新的候选 JSON，不修改原谱面或编辑器。')
    typed=input('请输入精确的 APPROVE <proposal_id> 以继续：').strip()
    print(ws.human_approve(args.proposal,typed))
if __name__=='__main__':main()

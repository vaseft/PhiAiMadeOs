"""V4 contract test (spec/schema and samples only; NOT model / Phira Pro e2e verification)."""
from pathlib import Path
import json
from jsonschema import Draft202012Validator, RefResolver, ValidationError
ROOT=Path(__file__).resolve().parents[1]
SCHEMA_DIR=ROOT/'schemas'

def load(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))

def validator(name):
  sch=load('schemas/'+name)
  Draft202012Validator.check_schema(sch)
  # Cross-file refs use a local schema store, never network
  store={'llm_patch.schema.json':load('schemas/llm_patch.schema.json')}
  for nm in ['llm_patch.schema.json']:
    store[(SCHEMA_DIR/nm).as_uri()]=store[nm]
  return Draft202012Validator(sch, resolver=RefResolver.from_schema(sch,store=store))

def check(v, object_, expected=True):
  errors=list(v.iter_errors(object_))
  if bool(not errors)!=expected:
    raise AssertionError(f"expected valid={expected}, errors={[str(x) for x in errors[:3]]}")

if __name__=='__main__':
  for nm in ['llm_patch.schema.json','llm_postprocess_proposal.schema.json','llm_segment_payload.schema.json','postprocess_request.schema.json','generation_request.schema.json','chart_ir.schema.json']:
    validator(nm)
  req=load('examples/postprocess_request_suggest.json');v=validator('postprocess_request.schema.json');check(v,req)
  q=req|{'confirm_external_upload':False};check(v,q,False)
  p=validator('llm_postprocess_proposal.schema.json');n=load('examples/llm_proposal_no_change.json');check(p,n)
  one=load('examples/llm_proposal_one_patch.json');check(p,one)
  forbidden=one.copy();forbidden['patches']=[dict(one['patches'][0],payload={'noise_areas':[]})];check(p,forbidden,False)
  invalid=dict(one);invalid['patches']=[dict(one['patches'][0],op='RUN_SHELL')];check(p,invalid,False)
  wrong_status=one.copy();wrong_status['status']='no_change';check(p,wrong_status,False)
  dupe=one.copy();dupe['patches']=[dict(one['patches'][0],payload={'new_start_beat':33.125,'BPMList':[120]})];check(p,dupe,False)
  g=validator('generation_request.schema.json');legacy=load('examples/generation_regular.json');check(g,legacy)
  # V4 disabled noise-area generation should reject true
  on={**legacy,'noise_area':{'generation_enabled':True}};check(g,on,False)
  off={**legacy,'noise_area':{'generation_enabled':False},'target_runtime':{'engine':'phira_pro','revision':'pinned-sha'}};check(g,off)
  prompt=(ROOT/'prompts/LLM_CHART_REFINER_SYSTEM_ZH.md').read_text(encoding='utf-8')
  assert all(x in prompt for x in ['noise_areas','pure_keys','噪域','evidence_refs','JSON'])
  print('PAMOs V4 schemas / examples / negative policy cases: PASS (offline static checks only)')

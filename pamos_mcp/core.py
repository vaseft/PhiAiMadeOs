# SPDX-License-Identifier: GPL-3.0-only
"""Conservative RPE JSON/PEZ offline reader and revisioned patch proposal backend.

NOT a replacement for the RPE Next GUI adapter, RPE official format conversion,
non-AI audio audit, or playable Phira-Pro testing. Originals are never overwritten.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import re
import stat
import uuid
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PureWindowsPath

MAX_CHART_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
NOTE_TYPES = {1, 2, 3, 4}  # RPE: Tap Hold Flick Drag
_ALLOWED = {"SHIFT_NOTE_BEATS", "SET_NOTE_X", "SET_NOTE_TYPE", "SET_HOLD_END", "MOVE_NOTE_LANE"}

class RPEError(ValueError):
    """A structured, fail-closed domain rejection."""

def _dumps(obj: object) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")

def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def beat_number(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 3 or not all(type(v) is int for v in value):
        raise RPEError("INVALID_BEAT")
    whole, num, den = value
    if den <= 0 or den > 1000000 or abs(whole) > 10000000 or abs(num) > 1000000:
        raise RPEError("INVALID_BEAT_RANGE")
    return Fraction(whole) + Fraction(num, den)

def to_beat(value: Fraction) -> list[int]:
    whole = math.floor(value)
    rest = value - whole
    return [whole, rest.numerator, rest.denominator]

def _is_noise(op: object) -> bool:
    return any(x in str(op).lower() for x in ('noise', 'blockarea', 'noisearea', '噪域'))

def _validate_chart(chart: object) -> None:
    if not isinstance(chart, dict) or not isinstance(chart.get('META'), dict) or not isinstance(chart.get('BPMList'), list) or not isinstance(chart.get('judgeLineList'), list):
        raise RPEError("NOT_RPE_CHART")
    if len(chart['judgeLineList']) > 500:
        raise RPEError('TOO_MANY_LINES')
    if not chart['BPMList']:
        raise RPEError('EMPTY_BPM')
    for bpm in chart['BPMList']:
        beat_number(bpm['startTime'])
        if not isinstance(bpm.get('bpm'), (int, float)) or not math.isfinite(bpm['bpm']) or bpm['bpm'] <= 0:
            raise RPEError('INVALID_BPM')
    for line in chart['judgeLineList']:
        if not isinstance(line, dict) or not isinstance(line.get('notes'), list):
            raise RPEError('INVALID_LINE')
        if len(line['notes']) > 50000:
            raise RPEError('TOO_MANY_NOTES')
        for note in line['notes']:
            if type(note.get('type')) is not int or note['type'] not in NOTE_TYPES:
                raise RPEError('INVALID_NOTE_TYPE')
            if not isinstance(note.get('positionX'), (int,float)) or not math.isfinite(note['positionX']):
                raise RPEError('INVALID_NOTE_X')
            start=beat_number(note.get('startTime'))
            end=beat_number(note.get('endTime'))
            if start < 0 or end < start or (note['type'] == 2 and end <= start):
                raise RPEError('INVALID_NOTE_TIME')

def _lane_positions(chart: dict, key_count: int | None) -> list:
    positions = chart.get('PAMOs_lane_positions')
    if not isinstance(positions, list):
        raise RPEError('LANE_MAP_MISSING')
    if (key_count not in (4, 5, 6) or len(positions) != key_count
            or not all(type(x) in (int, float) and math.isfinite(x) for x in positions)
            or len(set(positions)) != key_count):
        raise RPEError('INVALID_LANE_MAP')
    return positions


def _validate_static(chart: dict, key_count: int | None) -> None:
    positions = _lane_positions(chart, key_count)
    for line in chart['judgeLineList']:
        for note in line['notes']:
            if type(note['positionX']) not in (int, float) or note['positionX'] not in positions:
                raise RPEError('PURE_KEYS_NOTE_OUTSIDE_LANES')
        if line.get('father',-1) != -1:
            raise RPEError('PURE_KEYS_PARENT_LINE_UNSUPPORTED')
        for layer in line.get('eventLayers',[]) or []:
            for name in ('moveXEvents','moveYEvents','rotateEvents'):
                constant = None
                for event in layer.get(name,[]) or []:
                    start, end = event.get('start'), event.get('end')
                    if any(type(value) not in (int, float) or not math.isfinite(value)
                           for value in (start, end)):
                        raise RPEError('PURE_KEYS_INVALID_TRANSFORM')
                    if start != end or (constant is not None and start != constant):
                        raise RPEError('PURE_KEYS_DYNAMIC_LINE')
                    constant = start
        # Scale/transforms absent from the simple invariant -> no proof, reject.
        if line.get('extended') and any(line['extended'].get(k) for k in ('moveXEvents','moveYEvents','rotateEvents','scaleXEvents','scaleYEvents')):
            raise RPEError('PURE_KEYS_EXTENDED_TRANSFORM')

@dataclass
class Snapshot:
    name: str
    path: Path
    data: bytes
    chart: dict
    archive_member: str | None
    revision: str

class Workspace:
    def __init__(self, root: Path):
        self.root=root.resolve(strict=True)
        self.state=self.root/'.pamos_state'
        self.pending=self.state/'proposals'
        self.approvals=self.state/'approvals'
        self.outputs=self.state/'candidates'
        for p in (self.pending,self.approvals,self.outputs): p.mkdir(parents=True,exist_ok=True)

    def projects(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.json','.pez','.zip'))

    def _file(self, name: str) -> Path:
        if not re.fullmatch(r'[\w .()\-\u4e00-\u9fff]+\.(?:json|pez|zip)',name,re.IGNORECASE):
            raise RPEError('INVALID_PROJECT_ID')
        p=self.root/name
        if p.is_symlink() or not p.is_file() or p.resolve().parent!=self.root:
            raise RPEError('PROJECT_NOT_FOUND')
        return p

    def _unpack(self, path: Path) -> tuple[bytes,str|None]:
        if path.suffix.lower()=='.json':
            if path.stat().st_size>MAX_CHART_BYTES: raise RPEError('CHART_TOO_LARGE')
            return path.read_bytes(),None
        if path.stat().st_size>MAX_ARCHIVE_BYTES: raise RPEError('ARCHIVE_TOO_LARGE')
        candidates=[]
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                normalized = info.filename.replace('\\', '/')
                parts = normalized.rstrip('/').split('/')
                windows_path = PureWindowsPath(normalized)
                unsafe_part = any(
                    part in ('', '.', '..') or part.endswith((' ', '.'))
                    or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                    or PureWindowsPath(part).is_reserved()
                    for part in parts
                )
                if (windows_path.drive or windows_path.root or unsafe_part
                        or len(parts) > 12 or '\x00' in info.orig_filename
                        or (info.external_attr >>16 & 0o170000)==stat.S_IFLNK):
                    raise RPEError('UNSAFE_ARCHIVE_PATH')
                if info.file_size>MAX_CHART_BYTES and info.filename.lower().endswith('.json'):
                    raise RPEError('CHART_TOO_LARGE')
                if info.filename.lower().endswith('.json') and info.file_size<=MAX_CHART_BYTES:
                    try:
                        b=z.read(info)
                        val=json.loads(b.decode('utf-8-sig'))
                    except (ValueError,UnicodeError,RuntimeError): continue
                    if isinstance(val,dict) and 'META' in val and 'judgeLineList' in val:
                        candidates.append((info.filename,b))
        if len(candidates)!=1: raise RPEError('ARCHIVE_CHART_AMBIGUOUS_OR_ABSENT')
        return candidates[0][1],candidates[0][0]

    def open(self, name: str, mode: str='regular', key_count: int|None=None) -> Snapshot:
        if mode not in {'regular','pure_keys','anomaly'}: raise RPEError('INVALID_MODE')
        if mode=='pure_keys' and key_count not in (4,5,6):raise RPEError('INVALID_KEY_COUNT')
        if mode!='pure_keys' and key_count is not None: raise RPEError('UNEXPECTED_KEY_COUNT')
        p=self._file(name)
        raw,member=self._unpack(p)
        try: val=json.loads(raw.decode('utf-8-sig'))
        except (ValueError,UnicodeError): raise RPEError('INVALID_JSON') from None
        _validate_chart(val)
        if mode=='pure_keys':_validate_static(val, key_count)
        return Snapshot(name,p,raw,val,member,_hash(raw))

    def get_segment(self, snap: Snapshot, start: list[int],end: list[int], limit: int=128)->dict:
        a=beat_number(start);b=beat_number(end)
        if a<0 or b<=a or b-a>256 or limit<1 or limit>512: raise RPEError('INVALID_WINDOW')
        notes=[]
        for li,line in enumerate(snap.chart['judgeLineList']):
            for ni,note in enumerate(line['notes']):
                if a<=beat_number(note['startTime'])<b:
                    notes.append({'ref':f'l{li}:n{ni}','line':li,'note':note})
        notes.sort(key=lambda n:beat_number(n['note']['startTime']))
        return {'project_id':snap.name,'revision':snap.revision,'start':start,'end':end,
                'total':len(notes),'notes':notes[:limit],'truncated':len(notes)>limit}

    def _apply(self,snap:Snapshot,ops:list[dict],mode:str,key_count:int|None)->dict:
        if not isinstance(ops,list) or len(ops)<1 or len(ops)>12: raise RPEError('INVALID_OP_BATCH')
        result=copy.deepcopy(snap.chart)
        touched=set()
        for op in ops:
            if not isinstance(op,dict) or _is_noise(op): raise RPEError('NOISE_WRITE_FORBIDDEN')
            verb=op.get('op')
            if verb not in _ALLOWED: raise RPEError('OP_NOT_ALLOWED')
            if any(key not in ('op','note_ref','value','reason') for key in op):raise RPEError('EXTRA_PATCH_FIELDS')
            ref=op.get('note_ref','')
            match=re.fullmatch(r'l(\d+):n(\d+)',ref)
            if not match:raise RPEError('INVALID_NOTE_REF')
            li,ni=map(int,match.groups())
            try: note=result['judgeLineList'][li]['notes'][ni]
            except (IndexError,TypeError):raise RPEError('NOTE_NOT_FOUND') from None
            if ref in touched:raise RPEError('DUPLICATE_NOTE_EDIT')
            touched.add(ref)
            value=op.get('value')
            if verb=='SHIFT_NOTE_BEATS':
                delta=beat_number(value)  # represent signed difference as beat triple
                if abs(delta)>Fraction(1,8):raise RPEError('NOTE_SHIFT_TOO_LARGE')
                start=beat_number(note['startTime'])+delta
                end=beat_number(note['endTime'])+delta
                if start<0: raise RPEError('NEGATIVE_NOTE_TIME')
                note['startTime']=to_beat(start);note['endTime']=to_beat(end)
            elif verb=='SET_NOTE_X':
                if mode=='pure_keys':raise RPEError('PURE_KEYS_USE_LANE')
                if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>675:
                    raise RPEError('INVALID_NOTE_X')
                note['positionX']=value
            elif verb=='SET_NOTE_TYPE':
                if type(value) is not int or value not in (1,3,4) or note['type']==2:
                    raise RPEError('NOTE_KIND_TRANSITION_UNSUPPORTED')
                note['type']=value
            elif verb=='SET_HOLD_END':
                if note['type']!=2:raise RPEError('NOT_A_HOLD')
                end=beat_number(value)
                if end<=beat_number(note['startTime']):raise RPEError('INVALID_HOLD_END')
                note['endTime']=to_beat(end)
            elif verb=='MOVE_NOTE_LANE':
                if mode!='pure_keys' or key_count not in (4,5,6) or type(value) is not int or not 0<=value<key_count:
                    raise RPEError('INVALID_LANE')
                # Critical: do not guess K-track x coordinates. Require chart-specific mapping.
                positions=_lane_positions(snap.chart, key_count)
                note['positionX']=positions[value]
        _validate_chart(result)
        if mode=='pure_keys':_validate_static(result, key_count)
        if snap.chart.get('blockAreaList')!=result.get('blockAreaList') or snap.chart.get('noiseAreaLayers')!=result.get('noiseAreaLayers'):
            raise RPEError('NOISE_CHANGED')
        return result

    def propose(self,snap:Snapshot,ops:list[dict],mode='regular',key_count=None)->dict:
        result=self._apply(snap,ops,mode,key_count)
        proposal_id=str(uuid.uuid4())
        descriptor={'proposal_id':proposal_id,'project_id':snap.name,'source_revision':snap.revision,
                    'chart_mode':mode,'key_count':key_count,'operations':ops,'result_revision':_hash(_dumps(result))}
        (self.pending/f'{proposal_id}.json').write_bytes(_dumps(descriptor))
        return {'proposal_id':proposal_id,'source_revision':snap.revision,'preview_revision':descriptor['result_revision'],
                'operation_count':len(ops),'warning':'STRUCTURAL_CHECK_ONLY; DSP and GUI preview not yet implemented'}

    def _proposal(self,pid:str)->dict:
        if not re.fullmatch(r'[a-f0-9-]{36}',pid):raise RPEError('INVALID_PROPOSAL')
        path=self.pending/f'{pid}.json'
        if not path.is_file():raise RPEError('PROPOSAL_NOT_FOUND')
        return json.loads(path.read_text(encoding='utf-8'))

    def validate(self,pid:str)->dict:
        d=self._proposal(pid)
        snap=self.open(d['project_id'],d['chart_mode'],d['key_count'])
        if snap.revision!=d['source_revision']: raise RPEError('REVISION_CONFLICT')
        result=self._apply(snap,d['operations'],d['chart_mode'],d['key_count'])
        if _hash(_dumps(result))!=d['result_revision']:raise RPEError('PROPOSAL_TAMPERED')
        return {'proposal_id':pid,'valid':True,'source_revision':snap.revision,'preview_revision':d['result_revision'],
                'audit':'STRUCTURAL_ONLY','live_editor':'NOT_CONNECTED'}

    def preview(self,pid:str)->dict:
        valid=self.validate(pid)
        d=self._proposal(pid)
        return {**valid,'operations':d['operations'],'write_applied':False,
                'note':'User must inspect this diff and approve via local terminal; there is no automatic LLM approval'}

    def commit_candidate(self,pid:str)->dict:
        self.validate(pid)
        d=self._proposal(pid)
        approval_path=self.approvals/f'{pid}.json'
        if not approval_path.is_file():raise RPEError('HUMAN_APPROVAL_REQUIRED')
        approval=json.loads(approval_path.read_text(encoding='utf-8'))
        if approval != {'proposal_id':pid,'source_revision':d['source_revision'],'preview_revision':d['result_revision']}:
            raise RPEError('INVALID_APPROVAL')
        snap=self.open(d['project_id'],d['chart_mode'],d['key_count'])
        if snap.revision != d['source_revision']:
            raise RPEError('REVISION_CONFLICT')
        result=self._apply(snap,d['operations'],d['chart_mode'],d['key_count'])
        candidate_data = _dumps(result)
        if _hash(candidate_data) != d['result_revision']:
            raise RPEError('PROPOSAL_TAMPERED')
        output=self.outputs/f'{snap.path.stem}.pamos-{d["result_revision"][:12]}.json'
        try:
            with output.open('xb') as candidate:
                candidate.write(candidate_data)
        except FileExistsError:
            raise RPEError('CANDIDATE_ALREADY_EXISTS') from None
        approval_path.unlink()
        return {'candidate':str(output),'source_revision':snap.revision,'candidate_revision':_hash(candidate_data),
                'original_untouched':True,'live_editor':'NOT_CONNECTED','audit':'STRUCTURAL_ONLY',
                'status':'CANDIDATE_NOT_VERIFIED_FOR_PHIRA'}

    def human_approve(self,pid:str,typed:str)->dict:
        d=self._proposal(pid)
        self.validate(pid)
        if typed != f'APPROVE {pid}':raise RPEError('HUMAN_CONFIRMATION_FAILED')
        payload={'proposal_id':pid,'source_revision':d['source_revision'],'preview_revision':d['result_revision']}
        path=self.approvals/f'{pid}.json'
        path.write_bytes(_dumps(payload))
        os.chmod(path,0o600)
        return {'approved':True,'proposal_id':pid}

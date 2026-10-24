import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from pamos_mcp.core import Workspace,RPEError,beat_number,to_beat

FIX=Path(__file__).resolve().parents[1]/'fixtures'/'rpe_minimal.json'
class TestOfflineMCP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/'test.json').write_bytes(FIX.read_bytes())
        self.ws=Workspace(self.root)
        self.s=self.ws.open('test.json','pure_keys',4)
    def tearDown(self):self.tmp.cleanup()
    def test_read_and_pure_keys(self):
        self.assertEqual(self.ws.projects(),['test.json'])
        self.assertEqual(self.ws.get_segment(self.s,[0,0,1],[4,0,1])['total'],2)
        self.assertEqual(beat_number(to_beat(beat_number([1,1,8]))),beat_number([1,1,8]))
    def test_approved_lane_edit_keeps_original(self):
        p=self.ws.propose(self.s,[{'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':3}], 'pure_keys',4)
        pid=p['proposal_id'];self.ws.validate(pid)
        with self.assertRaisesRegex(RPEError,'HUMAN_APPROVAL_REQUIRED'):
            self.ws.commit_candidate(pid)
        with self.assertRaisesRegex(RPEError,'HUMAN_CONFIRMATION_FAILED'):
            self.ws.human_approve(pid,'APPROVE all')
        self.ws.human_approve(pid,f'APPROVE {pid}')
        commit=self.ws.commit_candidate(pid)
        output=json.loads(Path(commit['candidate']).read_text())
        original=json.loads((self.root/'test.json').read_text())
        self.assertEqual(output['judgeLineList'][0]['notes'][0]['positionX'],450)
        self.assertEqual(original['judgeLineList'][0]['notes'][0]['positionX'],-450)
        self.assertEqual(output['x-unknown'],original['x-unknown'])
        self.assertEqual(output['blockAreaList'],original['blockAreaList'])
    def test_reject_unsupported_and_noise(self):
        for op in [
            {'op':'EDIT_NOISE','note_ref':'l0:n0','value':1},
            {'op':'TUNE_LINE_EVENT','note_ref':'l0:n0','value':5},
            {'op':'SET_NOTE_X','note_ref':'l0:n0','value':120},
            {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':9}
        ]:
            with self.assertRaises(RPEError):
                self.ws.propose(self.s,[op],'pure_keys',4)
    def test_reject_stale_revision_and_path(self):
        p=self.ws.propose(self.s,[{'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':1}],'pure_keys',4)
        orig=json.loads((self.root/'test.json').read_text());orig['META']['name']='changed'
        (self.root/'test.json').write_text(json.dumps(orig))
        with self.assertRaisesRegex(RPEError,'REVISION_CONFLICT'):self.ws.validate(p['proposal_id'])
        with self.assertRaisesRegex(RPEError,'INVALID_PROJECT_ID'):
            self.ws.open('../test.json')
    def test_pez_read(self):
        with zipfile.ZipFile(self.root/'test.pez','w') as z:
            z.writestr('chart.json',FIX.read_bytes())
            z.writestr('info.txt','FileName: chart.json')
        v=self.ws.open('test.pez','pure_keys',4)
        self.assertEqual(v.archive_member,'chart.json')
    def test_unsafe_zip_rejected(self):
        with zipfile.ZipFile(self.root/'bad.pez','w') as z:
            z.writestr('../chart.json',FIX.read_bytes())
        with self.assertRaisesRegex(RPEError,'UNSAFE_ARCHIVE_PATH'):
            self.ws.open('bad.pez')

    def test_pure_keys_rejects_cross_event_position_jumps(self):
        for track in ('moveXEvents', 'moveYEvents', 'rotateEvents'):
            with self.subTest(track=track):
                chart = copy.deepcopy(self.s.chart)
                chart['judgeLineList'][0]['eventLayers'][0][track].append({
                    'startTime': [1, 0, 1], 'endTime': [2, 0, 1],
                    'start': 400, 'end': 400,
                })
                (self.root/'jump.json').write_text(json.dumps(chart), encoding='utf-8')
                with self.assertRaisesRegex(RPEError, 'PURE_KEYS_DYNAMIC_LINE'):
                    self.ws.open('jump.json', 'pure_keys', 4)

    def test_pure_keys_accepts_repeated_constant_events(self):
        chart = copy.deepcopy(self.s.chart)
        chart['judgeLineList'][0]['eventLayers'][0]['moveXEvents'].append({
            'startTime': [1, 0, 1], 'endTime': [2, 0, 1], 'start': 0, 'end': 0,
        })
        (self.root/'static.json').write_text(json.dumps(chart), encoding='utf-8')
        self.assertEqual(self.ws.open('static.json', 'pure_keys', 4).chart, chart)

    def test_pure_keys_requires_matching_distinct_lane_mapping(self):
        for key_count, positions in (
            (5, [-450, -150, 150, 450]),
            (6, [-450, -150, 150, 450]),
            (4, [-450, -150, 150, 150]),
            (4, [-450, -150, 150, True]),
            (4, [-450, -150, 150, float('nan')]),
        ):
            with self.subTest(key_count=key_count, positions=positions):
                chart = copy.deepcopy(self.s.chart)
                chart['PAMOs_lane_positions'] = positions
                (self.root/'lanes.json').write_text(json.dumps(chart), encoding='utf-8')
                with self.assertRaisesRegex(RPEError, 'INVALID_LANE_MAP'):
                    self.ws.open('lanes.json', 'pure_keys', key_count)

    def test_pure_keys_accepts_explicit_five_and_six_lane_maps(self):
        for positions in ([-450, -150, 0, 150, 450], [-450, -300, -150, 150, 300, 450]):
            with self.subTest(key_count=len(positions)):
                chart = copy.deepcopy(self.s.chart)
                chart['PAMOs_lane_positions'] = positions
                (self.root/'lanes.json').write_text(json.dumps(chart), encoding='utf-8')
                snap = self.ws.open('lanes.json', 'pure_keys', len(positions))
                proposal = self.ws.propose(snap, [
                    {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':len(positions)-1},
                ], 'pure_keys', len(positions))
                self.assertTrue(self.ws.validate(proposal['proposal_id'])['valid'])

    def test_pure_keys_rejects_off_lane_notes_before_and_after_patch(self):
        chart = copy.deepcopy(self.s.chart)
        chart['judgeLineList'][0]['notes'][1]['positionX'] = 0
        source = self.root/'off-lane.json'
        source.write_text(json.dumps(chart), encoding='utf-8')
        original_bytes = source.read_bytes()
        with self.assertRaisesRegex(RPEError, 'PURE_KEYS_NOTE_OUTSIDE_LANES'):
            self.ws.open(source.name, 'pure_keys', 4)
        regular = self.ws.open(source.name)
        with self.assertRaisesRegex(RPEError, 'PURE_KEYS_NOTE_OUTSIDE_LANES'):
            self.ws.propose(regular, [
                {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':3},
            ], 'pure_keys', 4)
        self.assertEqual(source.read_bytes(), original_bytes)
        self.assertEqual(list(self.ws.pending.iterdir()), [])
        self.assertEqual(list(self.ws.outputs.iterdir()), [])

    def test_commit_rejects_source_change_after_initial_validation(self):
        proposal = self.ws.propose(self.s, [
            {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':3},
        ], 'pure_keys', 4)
        pid = proposal['proposal_id']
        self.ws.human_approve(pid, f'APPROVE {pid}')
        original_open = self.ws.open
        calls = 0

        def change_before_second_open(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                chart = copy.deepcopy(self.s.chart)
                chart['META']['name'] = 'Concurrent synthetic edit'
                (self.root/'test.json').write_text(json.dumps(chart), encoding='utf-8')
            return original_open(*args, **kwargs)

        with patch.object(self.ws, 'open', side_effect=change_before_second_open):
            with self.assertRaisesRegex(RPEError, 'REVISION_CONFLICT'):
                self.ws.commit_candidate(pid)
        self.assertEqual(list(self.ws.outputs.iterdir()), [])
        self.assertTrue((self.ws.approvals/f'{pid}.json').is_file())

    def test_commit_rejects_operations_changed_after_initial_validation(self):
        proposal = self.ws.propose(self.s, [
            {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':3},
        ], 'pure_keys', 4)
        pid = proposal['proposal_id']
        self.ws.human_approve(pid, f'APPROVE {pid}')
        original_proposal = self.ws._proposal
        reads = 0

        def change_second_descriptor(proposal_id):
            nonlocal reads
            reads += 1
            descriptor = original_proposal(proposal_id)
            if reads == 2:
                descriptor['operations'][0]['value'] = 2
            return descriptor

        with patch.object(self.ws, '_proposal', side_effect=change_second_descriptor):
            with self.assertRaisesRegex(RPEError, 'PROPOSAL_TAMPERED'):
                self.ws.commit_candidate(pid)
        self.assertEqual(list(self.ws.outputs.iterdir()), [])

    def test_commit_never_overwrites_an_existing_candidate(self):
        proposal = self.ws.propose(self.s, [
            {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':3},
        ], 'pure_keys', 4)
        pid = proposal['proposal_id']
        self.ws.human_approve(pid, f'APPROVE {pid}')
        output = self.ws.outputs/f'test.pamos-{proposal["preview_revision"][:12]}.json'
        output.write_bytes(b'existing candidate must survive')
        # Simulate another writer creating the file after any existence check.
        with patch.object(Path, 'exists', return_value=False):
            with self.assertRaisesRegex(RPEError, 'CANDIDATE_ALREADY_EXISTS'):
                self.ws.commit_candidate(pid)
        self.assertEqual(output.read_bytes(), b'existing candidate must survive')

    def test_commit_rejects_approval_for_another_preview(self):
        proposal = self.ws.propose(self.s, [
            {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':3},
        ], 'pure_keys', 4)
        pid = proposal['proposal_id']
        self.ws.human_approve(pid, f'APPROVE {pid}')
        approval_path = self.ws.approvals/f'{pid}.json'
        approval = json.loads(approval_path.read_text(encoding='utf-8'))
        approval['preview_revision'] = '0' * 64
        approval_path.write_text(json.dumps(approval), encoding='utf-8')
        with self.assertRaisesRegex(RPEError, 'INVALID_APPROVAL'):
            self.ws.commit_candidate(pid)
        self.assertEqual(list(self.ws.outputs.iterdir()), [])

    def test_windows_and_ambiguous_zip_paths_rejected_on_every_platform(self):
        for member in (
            'C:/outside/chart.json', 'C:chart.json', 'stream:chart.json',
            '\\\\server\\share\\chart.json', '\\chart.json', 'folder\\..\\chart.json',
            'CON/chart.json', 'folder./chart.json', 'folder /chart.json',
            './chart.json', 'folder//chart.json',
        ):
            with self.subTest(member=member):
                with zipfile.ZipFile(self.root/'bad.pez', 'w') as archive:
                    archive.writestr(member, FIX.read_bytes())
                with self.assertRaisesRegex(RPEError, 'UNSAFE_ARCHIVE_PATH'):
                    self.ws.open('bad.pez')

    def test_relative_unicode_zip_member_still_supported(self):
        with zipfile.ZipFile(self.root/'nested.pez', 'w') as archive:
            archive.writestr('合成样本/', b'')
            archive.writestr('合成样本/chart.json', FIX.read_bytes())
        self.assertEqual(self.ws.open('nested.pez').archive_member, '合成样本/chart.json')

    def test_candidate_reimport_preserves_synthetic_noise_and_unknown_fields(self):
        # These tiny inline values are synthetic sentinels, not upstream assets.
        chart = copy.deepcopy(self.s.chart)
        chart['blockAreaList'] = [{'id':'synthetic-area', 'unknown':{'values':[1, 2]}}]
        chart['noiseAreaLayers'] = [{'id':'synthetic-layer', 'enabled':False}]
        chart['x-unknown'] = {'nested':[{'text':'合成字段', 'flag':True}]}
        chart['judgeLineList'][0]['x-line-unknown'] = {'preserve':17}
        chart['judgeLineList'][0]['notes'][0]['x-note-unknown'] = ['keep', 23]
        expected = copy.deepcopy(chart)
        expected['judgeLineList'][0]['notes'][0]['positionX'] = 450
        for suffix in ('json', 'pez'):
            with self.subTest(source_format=suffix):
                source = self.root/f'synthetic-{suffix}.{suffix}'
                if suffix == 'json':
                    source.write_text(json.dumps(chart, ensure_ascii=False), encoding='utf-8')
                else:
                    with zipfile.ZipFile(source, 'w') as archive:
                        archive.writestr('chart.json', json.dumps(chart, ensure_ascii=False))
                original_bytes = source.read_bytes()
                snap = self.ws.open(source.name, 'pure_keys', 4)
                proposal = self.ws.propose(snap, [
                    {'op':'MOVE_NOTE_LANE','note_ref':'l0:n0','value':3},
                ], 'pure_keys', 4)
                pid = proposal['proposal_id']
                self.ws.human_approve(pid, f'APPROVE {pid}')
                committed = self.ws.commit_candidate(pid)
                candidate = Path(committed['candidate'])
                imported = Workspace(candidate.parent).open(candidate.name, 'pure_keys', 4)
                self.assertEqual(imported.chart, expected)
                self.assertEqual(imported.revision, proposal['preview_revision'])
                self.assertEqual(committed['candidate_revision'], proposal['preview_revision'])
                self.assertEqual(source.read_bytes(), original_bytes)

if __name__=='__main__':unittest.main()

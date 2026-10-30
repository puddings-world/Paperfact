"""Actual claim extraction with a simulated model, authenticated HTTP and explicit deletion."""
import copy
import importlib.util
import json
import sys
import tempfile
import threading
from contextlib import closing, nullcontext
from pathlib import Path

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / 'src'))

from paper_daily import annotation_content, claim_content, llm, store, sync_capture  # noqa: E402
from paper_daily import research_generation as generation  # noqa: E402
from paper_daily.ai_types import Completion, Settings  # noqa: E402
from paper_daily.claim_jobs import ClaimJob  # noqa: E402
from paper_daily.sync_blobs import BlobStore  # noqa: E402
from paper_daily.sync_file_transfers import FileTransfers  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402

spec = importlib.util.spec_from_file_location(
    'claim_fixture_setup', Path(__file__).with_name('chat-service-fixture.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def no_ai(*_args, **_kwargs):
    raise AssertionError('Reading, syncing or deleting claims must never call a model')


def variants(body):
    """Reference-validated status and Unicode vectors without changing shared golden files."""
    values = []
    for state, reason in [('missing', 'quote_not_found'),
                          ('ambiguous', 'multiple_quote_locations'),
                          ('invalid_page', 'page_out_of_range'),
                          ('invalid_anchor', 'anchor_does_not_bound_unique_quote')]:
        value = copy.deepcopy(body)
        passage = value['report']['claims'][0]['passages'][0]
        passage['id'] = passage['proposal_id']
        passage['location'] = dict(state=state, reason=reason, anchor=None, page=None,
                                   candidates=[], truncated=False)
        if state == 'ambiguous':
            passage['location']['candidates'] = [
                dict(p0=0, o0=0, p1=0, o1=1), dict(p0=0, o0=2, p1=0, o1=3)]
        value['report']['id'] = claim_content.hashed(
            {key: item for key, item in value['report'].items() if key != 'id'})
        annotation_content.validate('claims', value)
        values.append({'name': state, 'body': value})
    value = copy.deepcopy(body)
    claim = value['report']['claims'][0]
    claim['text'] = 'F\u00adoo co-\n hort\u0085 \u4e2d\u6587\U0001f600'
    claim['id'] = claim_content.hashed(
        ['claim', value['report']['source'], claim_content.normalize(claim['text'])])
    value['report']['id'] = claim_content.hashed(
        {key: item for key, item in value['report'].items() if key != 'id'})
    annotation_content.validate('claims', value)
    values.append({'name': 'Python Unicode normalization', 'body': value})
    return values


def main():
    import pymupdf

    with tempfile.TemporaryDirectory(prefix='paperfact-mobile-claims-') as folder:
        root = Path(folder)
        authority = ReferenceService(root / 'service.sqlite', blob_root=root / 'authority-blobs')
        desktop = setup.client(root / 'desktop' / 'papers.db', 'desktop')
        database = desktop.journal.path
        token_desktop = authority.enroll('qa-workspace', 'desktop')
        transfers = FileTransfers(
            desktop, BlobStore(root / 'desktop-blobs'), authority,
            origin='https://fixture.invalid', token=token_desktop,
        )
        with store.connect() as conn:
            conn.execute("INSERT INTO lists VALUES('list','Claims fixture','',?)",
                         ('2026-10-30T00:00:00+00:00',))
            store.upsert_papers(conn, [{'id': 'local-paper', 'title': 'Claims fixture',
                                       'venue': 'Fixture', 'year': 2026, 'source': 'fixture'}])
            conn.execute('INSERT INTO list_papers(list_id,paper_id,position,added_at) '
                         'VALUES(?,?,0,?)', ('list', 'local-paper', '2026-10-30T00:00:00+00:00'))
        pdf_root = database.parent / 'pdf'
        pdf_root.mkdir()
        quote = 'The study enrolled 50 participants in a single center.'
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40, 50), quote)
            pdf.save(pdf_root / 'local-paper.pdf')
        for table in ('dives', 'close_readings'):
            with closing(generation._connect(database)) as conn:
                context = generation.begin_generation(conn, table=table, owner_id='local-paper',
                                                      input_reader='target')
            assert generation.publish_generation(context, row={
                'paper_id': 'local-paper',
                'body': 'The single-center sample limits generalization.',
                'written_at': store.now(), 'spec': 'fixture',
            }).status == 'accepted'
        calls = []
        llm.capture_connections = lambda: {}
        llm.connection_scope = lambda *_a, **_k: nullcontext()
        llm.settings = lambda **_kwargs: Settings('fixture', model='requested-fixture')

        def complete(*_args, **kwargs):
            assert kwargs['task'] == 'claims'
            calls.append(1)
            return Completion(json.dumps({'claims': [{
                'text': 'The study used a single-center cohort.',
                'judgment': {'status': 'supported',
                             'reason': 'Caller proposal; evaluate validity.'},
                'passages': [{'quote': quote, 'page': 1, 'anchor': None}],
            }]}), model='returned-fixture')

        llm.complete_result = complete
        job = ClaimJob.capture(database, 'local-paper', legacy_root=pdf_root)
        assert job.run().status == 'accepted'
        assert job.run().status == 'accepted' and len(calls) == 1
        llm.complete = llm.complete_result = no_ai
        claim = {'data': {key: json.loads(value) if key == 'body_json' else value
                          for key, value in job.result.items() if key != 'paper_id'},
                 'source_document_hash': job.result['document_hash']}
        # Accepted claims publish their original source as a real declared file operation.
        for operation in desktop.journal.pending():
            if operation['entity_type'] == 'research_file' and operation['action'] == 'put':
                for _ in range(40):
                    if transfers.upload(operation)['state'] == 'uploaded':
                        break
                else:
                    raise AssertionError('Accepted claim source upload did not finish')
        desktop.sync_once(authority, token_desktop, prepare_push=transfers.ready_to_push)
        token = authority.enroll('qa-workspace', 'phone')
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}', 'token': token,
                          'claims': claim, 'variants': variants(claim['data']['body_json']),
                          'events': len(authority.pull(token))}), flush=True)
        try:
            if sys.stdin.readline().strip() == 'delete':
                with closing(generation._connect(database)) as conn:
                    observed = sync_capture.observe_target(conn, 'paper', 'local-paper', 'claims')
                    with sync_capture.expecting(conn, [observed]):
                        conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='local-paper'")
                        conn.commit()
                desktop.sync_once(authority, token_desktop)
                print(json.dumps({'deleted': True, 'events': len(authority.pull(token))}),
                      flush=True)
                sys.stdin.readline()
            assert len(calls) == 1
        finally:
            transfers.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()

"""Two-process facility recovery acceptance, without the empty-window tests."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
def module(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
render=module('facility_check_common','run-rendering-check.py')
base=render.backend
write=render.write_json

MODES = {'engine': 'real-session-real-backend-two-process-harness',
         'native': 'real-native-renderer-real-backend-two-process-harness'}
PHASE_CHECKS = {
    1: {'twoManualEditsCloseCancel', 'closeDuringPendingApply', 'closeDuringPendingUndo', 'lostAcknowledgementDurableHandle'},
    2: {'restartKeepsSaveBlocked', 'readOnlyReconciliationWithoutReplay', 'recoveredUndoRestoresExactManualHistory', 'closeWithoutSave'},
}


def guarded_stderr(message):
    try:
        sys.stderr.write(message + '\n')
        sys.stderr.flush()
    except BaseException:
        pass


def final_write(target, value, primary):
    """Preserve an active failure when its diagnostic write also fails."""
    try:
        write(target, value)
    except OSError as error:
        # A Windows reader can deny replacement of the normal report filename.
        # Keep a uniquely named, flushed final receipt without touching that
        # reader or treating a failed replacement as successful persistence.
        fallback = target.with_name(target.stem + '.final-diagnostic-' + uuid.uuid4().hex + '.json')
        fallback_value = dict(value, status='failed', diagnosticWriteError=str(error), requestedReport=str(target))
        try:
            with fallback.open('x', encoding='utf-8') as stream:
                json.dump(fallback_value, stream, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            guarded_stderr('Facility recovery final diagnostics retained at ' + str(fallback))
        except OSError as fallback_error:
            guarded_stderr('Facility recovery fallback diagnostic write failed: ' + str(fallback_error))
        if primary is None:
            raise
        guarded_stderr('Facility recovery diagnostic write failed: ' + str(error))


def validate_stage_report(value, phase, mode, layout_id, prior_calls=None):
    checks = set(PHASE_CHECKS[phase])
    if phase == 1 and mode == 'native':
        checks.add('loadedAssets')
    if (not isinstance(value, dict) or value.get('revision') != 'facility-recovery-acceptance-v1'
            or value.get('status') != 'passed' or type(value.get('phase')) is not int or value['phase'] != phase
            or value.get('mode') != MODES[mode] or not isinstance(value.get('checks'), dict)
            or set(value['checks']) != checks or any(result != 'passed' for result in value['checks'].values())
            or type(value.get('saveRequests')) is not int or value['saveRequests'] != 0):
        raise ValueError('Facility recovery report does not prove the expected phase, mode, checks, and zero Save requests')
    calls = value.get('transactionCalls')
    counts = {'apply/prepare': 0, 'apply/commit': 0, 'apply/acknowledge': 0, 'undo/prepare': 0, 'undo/acknowledge': 0}
    prefix = '/api/facility-layout-design/site-local/' + layout_id
    pattern = re.compile(re.escape(prefix) + r'/(?:proposals/[A-Za-z0-9_-]+/(apply/prepare)|transactions/[A-Za-z0-9_-]+/(apply/commit|apply/acknowledge|undo/prepare|undo/acknowledge))')
    if not isinstance(calls, dict) or not calls:
        raise ValueError('Facility transaction endpoint evidence is missing')
    for route, count in calls.items():
        match = pattern.fullmatch(route) if isinstance(route, str) else None
        if not match or type(count) is not int or count != 1:
            raise ValueError('Facility transaction endpoint was missing, repeated, or unexpected')
        counts[next(part for part in match.groups() if part)] += 1
    expected = {'apply/prepare': 2, 'apply/commit': 2, 'apply/acknowledge': 2,
                'undo/prepare': phase, 'undo/acknowledge': phase}
    if counts != expected or (prior_calls is not None and any(calls.get(key) != count for key, count in prior_calls.items())):
        raise ValueError('Facility recovery report omits or changes the expected transaction sequence')
    return value


def run_worker_stage(command, stage, *, env, phase, mode, layout_id, prior_calls=None,
                     process_factory=None, timeout=240, drain_timeout=5):
    """Own one worker and its pipe; a prior stage can never supply cleanup proof."""
    worker = reader = pipe_state = None
    result = {'status': 'starting', 'phase': phase, 'terminationConfirmed': False,
              'stdioEOFVerified': False, 'stdioClosed': False, 'descendantTerminationVerified': False}
    log_path = stage / 'process.log'
    error = None
    stage_report = None
    process_factory = process_factory or subprocess.Popen
    try:
        write(stage / 'process-result.json', result)
        worker = process_factory(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **render.spawn_options())
        result['pid'] = worker.pid
        write(stage / 'process-result.json', result)
        reader, pipe_state = render.start_pipe_capture(worker.stdout, log_path)
        try:
            worker.wait(timeout=timeout)
        except subprocess.TimeoutExpired as caught:
            result['status'] = 'timed-out'
            raise RuntimeError('Facility recovery worker exceeded its deadline') from caught
        if worker.returncode != 0:
            raise RuntimeError('Facility recovery worker failed with exit code ' + str(worker.returncode) + '; inspect ' + str(log_path))
        report_path = stage / 'report.json'
        if not report_path.is_file() or report_path.stat().st_size > 1024 * 1024:
            raise ValueError('Facility recovery worker report is missing or oversized')
        stage_report = validate_stage_report(json.loads(report_path.read_text(encoding='utf-8')),
                                             phase, mode, layout_id, prior_calls)
    except BaseException as caught:
        error = caught
        result['error'] = str(caught) or type(caught).__name__
        if result['status'] != 'timed-out':
            result['status'] = 'spawn-error' if worker is None else 'failed'
    finally:
        cleanup_errors = []
        if worker is not None:
            try:
                if worker.poll() is None:
                    try:
                        worker.terminate()
                        worker.wait(timeout=5)
                    except (OSError, subprocess.TimeoutExpired):
                        if worker.poll() is None:
                            worker.kill()
                            worker.wait(timeout=5)
            except BaseException as caught:
                cleanup_errors.append(str(caught) or type(caught).__name__)
            finally:
                result.update(code=worker.poll(), terminationConfirmed=worker.poll() is not None)
                if reader is not None:
                    try:
                        reader.join(timeout=drain_timeout)
                        result['stdioEOFVerified'] = not reader.is_alive() and pipe_state.get('eof') is True
                        result['stdioClosed'] = result['stdioEOFVerified'] and pipe_state.get('closed') is True
                        if pipe_state.get('error'):
                            result['logError'] = pipe_state['error']
                    except BaseException as caught:
                        cleanup_errors.append(str(caught) or type(caught).__name__)
                elif worker.stdout is not None:
                    # No reader owns this untouched pipe. Close our handle, but
                    # never describe that close as observed EOF.
                    try:
                        worker.stdout.close()
                    except OSError as caught:
                        cleanup_errors.append(str(caught))
        if cleanup_errors:
            result['cleanupError'] = '; '.join(cleanup_errors)
        if not result['terminationConfirmed'] or not result['stdioClosed'] or result.get('logError') or cleanup_errors:
            if error is None:
                error = RuntimeError('Facility worker termination, diagnostic EOF, or log persistence was not confirmed')
                result['error'] = str(error)
            if result['status'] not in {'timed-out', 'spawn-error'}:
                result['status'] = 'failed'
        elif error is None:
            result['status'] = 'passed'
        result['finishedAt'] = render.now()
        try:
            final_write(stage / 'process-result.json', result, error)
        except OSError as caught:
            error = error or caught
            result['status'] = 'failed'
            result['diagnosticWriteError'] = str(caught)
    if error is not None:
        error.facility_process_result = result
        raise error
    return result, stage_report


def http(origin, route, token=None):
    request=urllib.request.Request(origin+route,headers={'X-InspectorPro-Recovery-Test':token} if token else {})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request,timeout=30)


def execute(args):
    data=base.no_links(args.data_root)
    output=base.no_links(args.output)
    output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((data/'facility-recovery-fixture.json').read_text())
    identity=manifest['identity']
    if args.port!=int(identity['origin'].rsplit(':',1)[1]):raise ValueError('Port differs from prepared fixture')
    library,identity=base.prepare_fixture(ROOT,data,identity['profileId'],args.port)
    source_layout=Path(manifest['source']['root'])/manifest['source']['layoutRelativePath']
    copy_layout=data/manifest['layout']['relativePath']
    before={'source':render.file_hash(source_layout),'isolated':render.file_hash(copy_layout)}
    if before['source']!=before['isolated'] or before['source']!=manifest['layout']['revision']:raise ValueError('Manual layout provenance mismatch')
    if (data/'recovery-harness-requests.json').exists() or (data/'facility-recovery-scenario-state.json').exists():raise ValueError('Use a fresh isolated fixture for each acceptance run; prior transactions are retained')
    token_path=data/'facility-recovery-test-token.txt'
    with token_path.open('x',encoding='ascii') as stream:
        token=secrets.token_hex(32);stream.write(token);stream.flush();os.fsync(stream.fileno())
    instance=str(uuid.uuid4())
    env=base.child_environment(dict(os.environ),data,library)
    env.update(INSPECTORPRO_DESKTOP_INSTANCE_ID=instance,INSPECTORPRO_FACILITY_RECOVERY_HARNESS='1')
    # Enable only dependencies for local manual edits and design transactions.
    from ai_inspector.facility_layout.feature_flags import FACILITY_LAYOUT_FEATURE_FLAGS,FACILITY_DESIGN_LOOP_FEATURE_FLAGS
    for name in FACILITY_LAYOUT_FEATURE_FLAGS:env[name]='1'
    for name in FACILITY_DESIGN_LOOP_FEATURE_FLAGS:
        env[name]='0' if name.endswith(('_LAB','_SAGE')) else '1'
    command=[sys.executable,'-u',str(Path(__file__).with_name('facility-recovery-backend.py')),'--serve','--data-root',str(data),'--port',str(args.port),'--profile-id',identity['profileId'],'--token-file',str(token_path)]
    report={'revision':'facility-recovery-acceptance-v1','mode':args.mode,'status':'starting','instanceId':instance,'startedAt':render.now(),'manualLayoutHashesBefore':before,'stages':{},'backend':{'terminationConfirmed':False,'resourceCleanupVerified':False},'editingScope':'explicit isolated test harness only','researchBrowsing':False}
    process=None
    try:
        write(output/'check.json',report)
        with (output/'backend.log').open('ab',buffering=0) as log:
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,**render.spawn_options())
            report['backend']['pid']=process.pid;write(output/'check.json',report)
            base.wait_ready(process,identity,45,instance)
            report['backend']['ready']=True
            try:
                with http(identity['origin'],'/api/facility-layouts/site-local/'+manifest['layout']['layoutId']):
                    raise AssertionError('Non-harness request reached manual layout')
            except urllib.error.HTTPError as error:
                try:
                    if error.code != 403:
                        raise AssertionError('Non-harness request was not explicitly denied')
                finally:
                    error.close()
            with http(identity['origin'],'/api/facility-layout-bootstrap',token) as response:bootstrap=json.load(response)
            catalog_ids={a['assetId'] for a in bootstrap['assetCatalog']}
            assert {a['assetId'] for a in manifest['assets']}<=catalog_ids
            with http(identity['origin'],'/api/industrial-assets',token) as response:library_response=json.load(response)
            # Store only counts and IDs, not private catalog payloads.
            report['assetLibrary']={'referencedAssetTypes':len(manifest['assets']),'bootstrapCatalogCount':len(catalog_ids),'industrialEndpointStatus':200,'industrialResponseKeys':list(library_response) if isinstance(library_response,dict) else ['array'],'assets':[]}
            for asset in manifest['assets']:
                digest=hashlib.sha256();size=0
                with http(identity['origin'],asset['route'],token) as response:
                    for chunk in iter(lambda:response.read(1024*1024),b''):digest.update(chunk);size+=len(chunk)
                assert digest.hexdigest()==asset['sha256'] and size==asset['bytes'],asset['assetId']
                report['assetLibrary']['assets'].append({'assetId':asset['assetId'],'sha256':digest.hexdigest(),'bytes':size,'served':True})
            report['assetLibrary']['status']='passed';write(output/'check.json',report)
            if args.mode=='backend-only':
                report['status']='passed';report['recoveryScenariosExecuted']=False
                return report
            if args.mode=='native':
                binary=render.resolve_electron();executable=binary['executable'];entry=Path(__file__).with_name('facility-recovery-native.cjs');report['electron']=binary
            else:
                executable=shutil.which('node');entry=Path(__file__).with_name('facility-recovery-engine.cjs')
                if not executable:raise RuntimeError('Installed Node runtime required')
            prior_calls = None
            for phase in (1,2):
                stage=output/('phase-'+str(phase));stage.mkdir()
                config={'phase':phase,'dataRoot':str(data),'output':str(stage),'origin':identity['origin'],'tokenFile':str(token_path),'mode':args.mode}
                config_path=data/('facility-check-phase-'+str(phase)+'.json');write(config_path,config)
                worker_env=dict(os.environ);worker_env['INSPECTORPRO_FACILITY_RECOVERY_HARNESS']='1'
                for name in ('ELECTRON_RUN_AS_NODE','ELECTRON_OVERRIDE_DIST_PATH','NODE_OPTIONS'):worker_env.pop(name,None)
                worker_command=[executable,str(entry),str(config_path)]
                try:
                    if args.mode == 'native' and render.file_hash(Path(executable)) != binary['sha256']:
                        raise ValueError('Pinned Electron executable changed before a recovery stage')
                    worker_result, stage_report = run_worker_stage(worker_command, stage, env=worker_env,
                        phase=phase, mode=args.mode, layout_id=manifest['layout']['layoutId'], prior_calls=prior_calls)
                except BaseException as error:
                    report['stages'][str(phase)] = getattr(error, 'facility_process_result', {
                        'status': 'failed', 'error': str(error), 'terminationConfirmed': False, 'stdioEOFVerified': False})
                    raise
                report['stages'][str(phase)] = worker_result
                prior_calls = stage_report['transactionCalls']
                write(output/'check.json',report)
            report['status']='passed';report['recoveryScenariosExecuted']=True
            return report
    except BaseException as error:
        report['status']='failed';report['error']=str(error);raise
    finally:
        primary=sys.exc_info()[1]
        cleanup_error=None
        if process is not None:
            try:
                base.stop_child(process)
                if process.poll() is None:
                    raise RuntimeError('Owned backend termination was not confirmed')
                receipt_path=base.shutdown_receipt_path(data,instance)
                receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
                expected={'schemaVersion':1,'instanceId':instance,'status':'lifespan-stopped','resourcesClosed':True}
                if receipt!=expected:raise RuntimeError('Backend shutdown/resource cleanup receipt missing or mismatched')
                report['backend']['resourceCleanupVerified']=True
            except BaseException as error:cleanup_error=error;report['backend']['cleanupError']=str(error);report['status']='failed'
            finally:
                report['backend'].update(exitCode=process.poll(),terminationConfirmed=process.poll() is not None)
        try:
            report['manualLayoutHashesAfter']={'source':render.file_hash(source_layout),'isolated':render.file_hash(copy_layout)}
            report['manualLayoutUnchanged']=report['manualLayoutHashesAfter']==before
            if not report['manualLayoutUnchanged']:
                raise RuntimeError('Manual layout bytes changed')
        except BaseException as error:
            report['status']='failed';report['manualLayoutUnchanged']=False;report['manualLayoutHashError']=str(error)
            cleanup_error=cleanup_error or error
        report['finishedAt']=render.now();final_write(output/'check.json',report,primary or cleanup_error)
        if primary is None and cleanup_error is not None:raise cleanup_error


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--port',type=int,default=8199);parser.add_argument('--mode',choices=['engine','native','backend-only'],default='native');args=parser.parse_args()
    sys.path.insert(0,str(ROOT))
    try:report=execute(args);print(json.dumps({'status':report['status'],'mode':args.mode,'output':str(args.output)}));return 0
    except Exception as error:print(str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())

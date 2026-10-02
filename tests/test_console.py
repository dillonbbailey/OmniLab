import multiprocessing
import time
import pytest
from pxr import UsdGeom

from omnilab.core.fixtures import demo_document
from omnilab.automation.console import snapshot, apply_result, run_worker


def execute(document, code, tmp_path):
    context = multiprocessing.get_context('spawn')
    connection, child = context.Pipe()
    process = context.Process(target=run_worker, args=(child,))
    process.start()
    child.close()
    before = snapshot(document)
    try:
        connection.send(dict(type='execute', id='test', stage=before, code=code,
                             frame=document.frame, selection=[], cancel=str(tmp_path/'cancel')))
        deadline = time.monotonic()+10
        messages = []
        while time.monotonic() < deadline:
            if connection.poll(.1):
                message = connection.recv()
                messages.append(message)
                if message['type'] == 'finished':
                    return before, message, messages
        raise TimeoutError('Console worker did not complete.')
    finally:
        process.terminate()
        process.join(timeout=2)
        process.close()
        connection.close()


def test_console_layers_commit_as_single_undo_and_preserve_prior_history(tmp_path):
    document = demo_document()
    document.command('add_prim', '/World', 'Before', 'Xform')
    before, result, messages = execute(document, "with usd.edit('Create'):\n    UsdGeom.Cube.Define(stage, '/World/PythonCube')\nprint('ready')", tmp_path)
    assert result['status'] == 'ok', messages
    apply_result(document, before, result)
    assert document.stage.GetPrimAtPath('/World/PythonCube')
    document.command('restore')
    assert not document.stage.GetPrimAtPath('/World/PythonCube')
    assert document.stage.GetPrimAtPath('/World/Before')
    document.command('restore')
    assert not document.stage.GetPrimAtPath('/World/Before')
    document.command('restore', True)
    document.command('restore', True)
    assert document.stage.GetPrimAtPath('/World/PythonCube')


def test_console_exception_and_conflicting_edit_do_not_commit(tmp_path):
    document = demo_document()
    _, result, _ = execute(document, "UsdGeom.Cube.Define(stage, '/World/Bad')\nraise RuntimeError('oops')", tmp_path)
    assert result['status'] == 'error' and result['stage'] is None
    assert not document.stage.GetPrimAtPath('/World/Bad')
    before, result, _ = execute(document, "UsdGeom.Cube.Define(stage, '/World/Good')", tmp_path)
    document.command('add_prim', '/World', 'Concurrent', 'Xform')
    with pytest.raises(ValueError, match='document changed'):
        apply_result(document, before, result)
    assert not document.stage.GetPrimAtPath('/World/Good')


def test_console_read_only_cell_does_not_rewrite_layers(tmp_path):
    document = demo_document()
    original = document.stage.GetRootLayer().ExportToString()
    before, result, _ = execute(document, 'len(list(stage.Traverse()))', tmp_path)
    apply_result(document, before, result)
    assert document.stage.GetRootLayer().ExportToString() == original
    assert not document.edits.undo

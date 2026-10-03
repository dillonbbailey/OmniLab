import pytest

from omnilab.core.document import Document
from omnilab.core.fixtures import demo_document
from omnilab.core.relaunch import write_checkpoint, read_checkpoint


@pytest.mark.parametrize('dirty', [False, True])
def test_relaunch_preserves_document_and_save_destination(tmp_path, dirty):
    document = demo_document()
    source = tmp_path/'source.omnilab'
    document.save(source)
    original = source.read_bytes()
    if dirty:
        document.command('set_property', dict(path='/World/Cube', group='Attributes', name='size', value=3))
    document.select(['/World/Cube'])
    document.frame = 2.5
    document.view['test'] = {'nested': [1, 2]}
    checkpoint = write_checkpoint(document, {'console': "print('do not execute')"}, tmp_path/'relaunch')
    assert source.read_bytes() == original
    assert document.path == str(source) and document.dirty == dirty
    resumed, workspace = read_checkpoint(checkpoint)
    assert resumed.path == str(source) and resumed.dirty == dirty
    assert resumed.selection == ['/World/Cube'] and resumed.frame == 2.5
    assert resumed.view['test'] == {'nested': [1, 2]}
    assert workspace['console'] == "print('do not execute')"
    assert resumed.stage.GetPrimAtPath('/World/Cube').GetAttribute('size').Get() == (3 if dirty else 1.5)
    assert not resumed.edits.undo and not resumed.edits.redo
    resumed.save()
    assert not resumed.dirty
    assert Document.open(source).stage.GetPrimAtPath('/World/Cube').GetAttribute('size').Get() == (3 if dirty else 1.5)


def test_relaunch_preserves_untitled_session_and_mute_state(tmp_path):
    document = demo_document()
    document.stage.SetEditTarget(document.stage.GetSessionLayer())
    document.command('set_property', dict(path='/World/Cube', group='Attributes', name='size', value=6))
    sublayer = document.command('create_sublayer', dict(identifier=document.stage.GetRootLayer().identifier,
        storage='memory', name='muted.usda', expected=[], sublayers=[]))
    document.command('set_layer_muted', sublayer, True)
    checkpoint = write_checkpoint(document, directory=tmp_path)
    resumed, _ = read_checkpoint(checkpoint)
    assert resumed.path == '' and resumed.dirty
    assert resumed.stage.GetEditTarget().GetLayer() == resumed.stage.GetSessionLayer()
    assert len(resumed.stage.GetMutedLayers()) == 1
    assert resumed.stage.GetPrimAtPath('/World/Cube').GetAttribute('size').Get() == 6
    assert checkpoint.exists()  # Durable recovery also works with ordinary Open.

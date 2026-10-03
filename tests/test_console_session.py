"""Exercise the actual frontend-neutral console process and cancellation boundary."""

import time

from omnilab.automation.console_session import ConsoleSession
from omnilab.core.fixtures import demo_document


def finish(session):
    deadline = time.monotonic() + 20
    while session.running:
        assert time.monotonic() < deadline, "Console did not finish"
        session.tick()
        time.sleep(0.01)


def test_console_session_commit_and_cancel():
    document = demo_document()
    output, changes = [], []
    session = ConsoleSession(
        lambda: document, lambda: changes.append(True), output.append
    )
    try:
        session.run(
            "usd.command('add_prim', '/World', 'FromConsole', 'Cube'); print('done')"
        )
        finish(session)
        assert document.stage.GetPrimAtPath("/World/FromConsole")
        assert len(document.edits.undo) == 1
        assert changes == [True]
        session.run(
            "usd.command('add_prim', '/World', 'Cancelled', 'Cube'); import time; time.sleep(30)"
        )
        session.stop()
        finish(session)
        assert not document.stage.GetPrimAtPath("/World/Cancelled")
        assert len(document.edits.undo) == 1
    finally:
        session.close()


def test_console_discards_result_after_document_replacement():
    documents = [demo_document()]
    output = []
    session = ConsoleSession(lambda: documents[0], lambda: None, output.append)
    try:
        session.run("usd.command('add_prim', '/World', 'LateResult', 'Cube')")
        documents[0] = demo_document()
        finish(session)
        assert not documents[0].stage.GetPrimAtPath("/World/LateResult")
        assert not documents[0].edits.undo
        assert any("document changed" in text for text in output)
    finally:
        session.close()

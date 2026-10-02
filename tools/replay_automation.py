"""Actual Qt console controls and a real MCP stdio-client/GUI round trip."""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from omnilab.frontends.qt.window import MainWindow


def main():
    out = Path('artifacts/automation').resolve()
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    window = MainWindow(False)
    window.new_demo()
    window.show()
    report = {}
    def wait(predicate, timeout=30):
        deadline = time.monotonic()+timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise TimeoutError('Desktop automation timed out.')
            app.processEvents()
            QTest.qWait(10)
    try:
        assert not getattr(window, 'mcp_bridge', None)
        window.open_python_console()
        console = window.python_console
        console.code.setPlainText("UsdGeom.Cube.Define(stage, '/World/FromPython')\nlen(list(stage.Traverse()))")
        QTest.mouseClick(console.run_button, Qt.LeftButton)
        wait(lambda: not console.running)
        assert window.document.stage.GetPrimAtPath('/World/FromPython'), console.output.toPlainText()
        window.execute('restore')
        assert not window.document.stage.GetPrimAtPath('/World/FromPython')
        console.code.setPlainText("UsdGeom.Cube.Define(stage, '/World/Cancelled')\nimport time\ntime.sleep(60)")
        console.run()
        QTest.qWait(300)
        started = time.monotonic()
        console.stop()
        wait(lambda: not console.running)
        report['console_native_stop_seconds'] = time.monotonic()-started
        assert not window.document.stage.GetPrimAtPath('/World/Cancelled')
        console.grab().save(str(out/'console.png'))
        console.close()
        window.mcp_action.trigger()
        descriptor = window.mcp_bridge.descriptor
        editor_id = window.mcp_bridge.editor_id
        errors = []
        done = threading.Event()
        async def exercise():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            parameters = StdioServerParameters(command=sys.executable, args=['-m', 'omnilab.automation.mcp_server'],
                env=dict(os.environ, OMNILAB_SESSION=editor_id))
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    report['mcp_tools'] = len((await session.list_tools()).tools)
                    def payload(result):
                        assert not result.isError, result
                        return json.loads(result.content[0].text)
                    state = payload(await session.call_tool('get_state', {}))
                    result = payload(await session.call_tool('edit_graph', dict(material='/World/Looks/Surface',
                        expected_revision=state['revision'], operations=[
                            dict(op='add_node', identifier='ND_constant_color3', name='MCPColor', ref='color'),
                            dict(op='set_value', node='$color', input='value', value=[.8,.1,.02]),
                            dict(op='connect', source='$color', target='/World/Looks/Surface/Shader', input='base_color')])))
                    stale = await session.call_tool('edit_graph', dict(material='/World/Looks/Surface',
                        expected_revision=state['revision'], operations=[dict(op='remove',nodes=[result['created']['color']])]))
                    assert stale.isError
                    graph = payload(await session.call_tool('get_graph', dict(material='/World/Looks/Surface')))
                    assert any(node['name']=='MCPColor' for node in graph['nodes'])
                    payload(await session.call_tool('document_command', dict(command='restore',arguments=[],expected_revision=graph['revision'])))
                    graph = payload(await session.call_tool('get_graph', dict(material='/World/Looks/Surface')))
                    assert not any(node['name']=='MCPColor' for node in graph['nodes'])
                    report.update(mcp_atomic_edit_undo=True, mcp_stale_revision_rejected=True)
        def worker():
            try:
                asyncio.run(exercise())
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()
        threading.Thread(target=worker, daemon=True).start()
        wait(done.is_set)
        if errors:
            raise errors[0]
        window.mcp_action.trigger()
        assert not descriptor.exists()
        report.update(status='passed', mcp_starts_stopped=True, mcp_endpoint_removed=True)
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:
        window.document.edits.saved={layer:layer.ExportToString() for layer in window.document.edits.saved}
        window.close()


if __name__ == '__main__':
    main()

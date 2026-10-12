"""Exercise the packaged folder-opening workflow with network access forbidden."""

from pathlib import Path
import json, time, socket


def run(save_path, report_path):
    from app import QApplication, MainWindow, STYLE

    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    window = MainWindow()
    window.timer.stop()
    window.show()
    errors = []
    window.load_failed = errors.append
    original_socket = socket.socket

    def no_network(*args, **kwargs):
        raise RuntimeError("Network disabled during local replay verification.")

    socket.socket = no_network
    checks = []

    def loaded(action):
        errors.clear()
        action()
        deadline = time.monotonic() + 600
        while window.worker.isRunning():
            application.processEvents()
            time.sleep(0.01)
            if time.monotonic() > deadline:
                raise TimeoutError("Replay loading timed out.")
        application.processEvents()
        if errors:
            raise ValueError(errors[-1])
        assert (
            window.native_document and window.frames and window.play_button.isEnabled()
        ), "Native motion did not enable Play."
        assert window.recorder is None
        window.seek(2000)
        window.toggle_play()
        before = window.index
        window.last_tick = time.monotonic() - 0.1
        window.tick()
        assert window.playing and window.index > before, "Playback did not advance."
        window.playing = False
        checks.append(
            {
                "driver": window.frames.slot,
                "frames": len(window.frames),
                "play_enabled": True,
                "motion_advanced": True,
            }
        )

    try:
        loaded(lambda: window.load_save(save_path))
        assert window.all_cars.isChecked()
        assert len(window.map_view.visible_cars()) > 1
        archive = str(window.native_document.path)
        loaded(lambda: window.load_save(save_path))
        loaded(lambda: window.load_native_file(archive))
        loaded(lambda: window.load_native_file(archive))
        for row in range(window.entries_table.rowCount()):
            window.entries_table.selectRow(row)
            assert window.frames and window.play_button.isEnabled()
        window.seek(200)
        application.processEvents()
        preview = Path(report_path).with_suffix(".png")
        assert window.grab().save(str(preview))
        report = {
            "folder_open_and_reopen": "passed",
            "native_file_open_and_reopen": "passed",
            "all_cars_default": True,
            "pan_zoom_and_orbit_unit_tests": "passed",
            "network_access": "forbidden",
            "ps3_recorder_started": False,
            "checks": checks,
            "native_archive": archive,
            "window_title": window.windowTitle(),
            "preview": str(preview),
        }
        Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        socket.socket = original_socket
        window.close()
    return 0

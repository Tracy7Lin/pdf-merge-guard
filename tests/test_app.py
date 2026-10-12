from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from pypdf import PdfWriter

from pdf_merge_guard.app import MainWindow


def make_pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def settings(path: Path) -> QSettings:
    return QSettings(str(path / "settings.ini"), QSettings.IniFormat)


def test_add_deduplicate_and_default_output(tmp_path: Path, monkeypatch) -> None:
    app()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.Ok)
    window = MainWindow(settings(tmp_path))
    first = make_pdf(tmp_path / "first.pdf", 2)
    second = make_pdf(tmp_path / "second.pdf", 3)

    window.add_paths([first, second, first])

    assert window.file_list.count() == 2
    assert window.directory_edit.text() == str(tmp_path)
    assert window.merge_button.isEnabled()
    assert window.file_list.item(1).data(Qt.UserRole)["pages"] == 3
    window.close()


def test_manual_directory_survives_reorder(tmp_path: Path) -> None:
    app()
    window = MainWindow(settings(tmp_path))
    folder = tmp_path / "other"
    folder.mkdir()
    first = make_pdf(tmp_path / "first.pdf", 1)
    second = make_pdf(folder / "second.pdf", 1)
    window.add_paths([first, second])
    window.directory_edit.setText("C:/chosen")
    window._directory_edited("C:/chosen")

    item = window.file_list.takeItem(1)
    window.file_list.insertItem(0, item)
    window._order_changed()

    assert window.directory_edit.text() == "C:/chosen"
    window.close()


def test_language_is_persisted(tmp_path: Path) -> None:
    application = app()
    store = settings(tmp_path)
    window = MainWindow(store)
    window.language_combo.setCurrentIndex(1)
    application.processEvents()
    assert store.value("language") == "en_US"
    window.close()

    reopened = MainWindow(store)
    assert reopened.language == "en_US"
    assert reopened.merge_button.text() == "Merge PDFs"
    reopened.close()


def test_close_is_blocked_while_merge_is_running(tmp_path: Path, monkeypatch) -> None:
    app()
    window = MainWindow(settings(tmp_path))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.Ok)

    class RunningThread:
        @staticmethod
        def isRunning() -> bool:
            return True

    window.thread = RunningThread()  # type: ignore[assignment]
    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted()
    window.thread = None
    window.close()


from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pdf_merge_guard.core import (
    MergeMode,
    MergeResult,
    PdfMergeError,
    PdfValidationError,
    inspect_pdf,
    merge_pdfs,
    normalized_output_path,
)
from pdf_merge_guard.i18n import text


class MergeWorker(QObject):
    progressed = Signal(int, int, str)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, paths: list[Path], output: Path, mode: MergeMode) -> None:
        super().__init__()
        self.paths = paths
        self.output = output
        self.mode = mode

    @Slot()
    def run(self) -> None:
        try:
            result = merge_pdfs(
                self.paths,
                self.output,
                self.mode,
                overwrite=True,
                progress=lambda current, total, path: self.progressed.emit(current, total, path.name),
            )
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or QSettings("PDF Merge Guard", "PDF Merge Guard")
        self.language = self.settings.value("language", "zh_CN")
        if self.language not in {"zh_CN", "en_US"}:
            self.language = "zh_CN"
        self.output_directory_manual = False
        self.thread: QThread | None = None
        self.worker: MergeWorker | None = None
        self._build_ui()
        self._apply_texts()
        self._refresh_state()

    def tr_key(self, key: str, **values: object) -> str:
        return text(self.language, key, **values)

    def _build_ui(self) -> None:
        self.setMinimumSize(900, 680)
        self.resize(1040, 760)
        central = QWidget(objectName="central")
        root = QVBoxLayout(central)
        root.setContentsMargins(34, 28, 34, 28)
        root.setSpacing(20)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        self.eyebrow = QLabel(objectName="eyebrow")
        self.headline = QLabel(objectName="headline")
        self.subtitle = QLabel(objectName="subtitle")
        title_box.addWidget(self.eyebrow)
        title_box.addWidget(self.headline)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box, 1)
        language_box = QVBoxLayout()
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        self.language_combo.addItem("简体中文", "zh_CN")
        self.language_combo.addItem("English", "en_US")
        self.language_combo.setCurrentIndex(0 if self.language == "zh_CN" else 1)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        language_box.addWidget(self.language_label)
        language_box.addWidget(self.language_combo)
        header.addLayout(language_box)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(18)
        left = QFrame(objectName="card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(20, 18, 20, 20)
        left_layout.setSpacing(12)
        file_header = QHBoxLayout()
        self.files_label = QLabel(objectName="sectionTitle")
        self.drag_hint = QLabel(objectName="muted")
        file_header.addWidget(self.files_label)
        file_header.addStretch()
        file_header.addWidget(self.drag_hint)
        left_layout.addLayout(file_header)

        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.file_list.setDefaultDropAction(Qt.MoveAction)
        self.file_list.setSpacing(3)
        self.file_list.model().rowsMoved.connect(self._order_changed)
        self.file_list.itemSelectionChanged.connect(self._refresh_state)
        left_layout.addWidget(self.file_list, 1)

        self.empty_panel = QFrame(objectName="emptyPanel", parent=self.file_list.viewport())
        empty_layout = QVBoxLayout(self.empty_panel)
        empty_layout.setAlignment(Qt.AlignCenter)
        self.empty_icon = QLabel("PDF", objectName="emptyIcon")
        self.empty_icon.setAlignment(Qt.AlignCenter)
        self.empty_title = QLabel(objectName="emptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_hint = QLabel(objectName="muted")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_icon)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_hint)
        self.file_list.viewport().installEventFilter(self)

        actions = QHBoxLayout()
        self.add_button = QPushButton(objectName="primarySmall")
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button = QPushButton()
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button = QPushButton()
        self.clear_button.clicked.connect(self.clear_files)
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.clear_button)
        actions.addStretch()
        left_layout.addLayout(actions)
        content.addWidget(left, 3)

        right = QFrame(objectName="card")
        right.setFixedWidth(330)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(22, 18, 22, 20)
        right_layout.setSpacing(10)
        self.mode_label = QLabel(objectName="sectionTitle")
        right_layout.addWidget(self.mode_label)
        self.duplex_radio = QRadioButton()
        self.duplex_radio.setChecked(True)
        self.duplex_help = QLabel(objectName="help")
        self.duplex_help.setWordWrap(True)
        self.standard_radio = QRadioButton()
        self.standard_help = QLabel(objectName="help")
        self.standard_help.setWordWrap(True)
        group = QButtonGroup(self)
        group.addButton(self.duplex_radio)
        group.addButton(self.standard_radio)
        right_layout.addWidget(self.duplex_radio)
        right_layout.addWidget(self.duplex_help)
        right_layout.addSpacing(6)
        right_layout.addWidget(self.standard_radio)
        right_layout.addWidget(self.standard_help)
        right_layout.addSpacing(20)

        self.output_label = QLabel(objectName="sectionTitle")
        self.filename_label = QLabel(objectName="fieldLabel")
        self.filename_edit = QLineEdit("合并PDF.pdf")
        self.directory_label = QLabel(objectName="fieldLabel")
        directory_row = QHBoxLayout()
        self.directory_edit = QLineEdit()
        self.directory_edit.textEdited.connect(self._directory_edited)
        self.browse_button = QPushButton()
        self.browse_button.clicked.connect(self._choose_directory)
        directory_row.addWidget(self.directory_edit, 1)
        directory_row.addWidget(self.browse_button)
        right_layout.addWidget(self.output_label)
        right_layout.addWidget(self.filename_label)
        right_layout.addWidget(self.filename_edit)
        right_layout.addWidget(self.directory_label)
        right_layout.addLayout(directory_row)
        right_layout.addStretch()

        self.summary_label = QLabel(objectName="summary")
        self.summary_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.merge_button = QPushButton(objectName="mergeButton")
        self.merge_button.setMinimumHeight(48)
        self.merge_button.clicked.connect(self.start_merge)
        right_layout.addWidget(self.summary_label)
        right_layout.addWidget(self.progress)
        right_layout.addWidget(self.merge_button)
        content.addWidget(right)
        root.addLayout(content, 1)

        self.status_label = QLabel(objectName="status")
        root.addWidget(self.status_label)
        self.setCentralWidget(central)
        self.setStyleSheet(STYLESHEET)

    def eventFilter(self, watched: QObject, event: object) -> bool:
        if watched is self.file_list.viewport() and getattr(event, "type", lambda: None)() in {
            QEvent.Resize,
            QEvent.Show,
        }:
            self.empty_panel.setGeometry(self.file_list.viewport().rect())
        return super().eventFilter(watched, event)

    def _apply_texts(self) -> None:
        self.setWindowTitle(self.tr_key("app_title"))
        self.eyebrow.setText(self.tr_key("eyebrow"))
        self.headline.setText(self.tr_key("headline"))
        self.subtitle.setText(self.tr_key("subtitle"))
        self.language_label.setText(self.tr_key("language"))
        self.add_button.setText("＋  " + self.tr_key("add_files"))
        self.remove_button.setText(self.tr_key("remove"))
        self.clear_button.setText(self.tr_key("clear"))
        self.files_label.setText(self.tr_key("files"))
        self.drag_hint.setText(self.tr_key("drag_hint"))
        self.empty_title.setText(self.tr_key("empty_title"))
        self.empty_hint.setText(self.tr_key("empty_hint"))
        self.mode_label.setText(self.tr_key("mode"))
        self.duplex_radio.setText(self.tr_key("duplex"))
        self.duplex_help.setText(self.tr_key("duplex_help"))
        self.standard_radio.setText(self.tr_key("standard"))
        self.standard_help.setText(self.tr_key("standard_help"))
        self.output_label.setText(self.tr_key("output"))
        self.filename_label.setText(self.tr_key("filename"))
        self.directory_label.setText(self.tr_key("directory"))
        self.browse_button.setText(self.tr_key("browse"))
        self.merge_button.setText(self.tr_key("merge"))
        self._retranslate_items()
        self._refresh_state()

    @Slot()
    def _language_changed(self) -> None:
        self.language = self.language_combo.currentData()
        self.settings.setValue("language", self.language)
        self._apply_texts()

    @Slot()
    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr_key("select_pdfs"), "", "PDF (*.pdf)")
        if paths:
            self.add_paths([Path(path) for path in paths])

    def add_paths(self, paths: list[Path]) -> None:
        existing = {Path(self.file_list.item(i).data(Qt.UserRole)["path"]) for i in range(self.file_list.count())}
        issues: list[str] = []
        for path in paths:
            resolved = path.expanduser().resolve()
            if resolved in existing:
                issues.append(self.tr_key("duplicate_skipped", name=resolved.name))
                continue
            try:
                info = inspect_pdf(resolved)
            except PdfMergeError as exc:
                issues.append(f"{resolved.name} — {self._error_text(str(exc))}")
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, {"path": str(info.path), "pages": info.page_count})
            item.setSizeHint(QSize(100, 60))
            self.file_list.addItem(item)
            existing.add(resolved)
            self._set_item_text(item)
        if self.file_list.count() and not self.output_directory_manual:
            self._update_default_directory()
        if issues:
            QMessageBox.warning(self, self.tr_key("invalid_files"), "\n".join(issues))
        self._refresh_state()

    def _set_item_text(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        path = Path(data["path"])
        item.setText(
            f"{path.name}\n{self.tr_key('pages', count=data['pages'])}  ·  {self.tr_key('ready')}  ·  {path.parent}"
        )
        item.setToolTip(str(path))

    def _retranslate_items(self) -> None:
        for index in range(self.file_list.count()):
            self._set_item_text(self.file_list.item(index))

    @Slot()
    def remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self._order_changed()

    @Slot()
    def clear_files(self) -> None:
        self.file_list.clear()
        if not self.output_directory_manual:
            self.directory_edit.clear()
        self._refresh_state()

    @Slot()
    def _order_changed(self, *_args: object) -> None:
        if not self.output_directory_manual:
            self._update_default_directory()
        self._refresh_state()

    def _update_default_directory(self) -> None:
        value = ""
        if self.file_list.count():
            value = str(Path(self.file_list.item(0).data(Qt.UserRole)["path"]).parent)
        self.directory_edit.setText(value)

    @Slot(str)
    def _directory_edited(self, _value: str) -> None:
        self.output_directory_manual = True

    @Slot()
    def _choose_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, self.tr_key("select_folder"), self.directory_edit.text() or str(Path.home())
        )
        if selected:
            self.output_directory_manual = True
            self.directory_edit.setText(selected)

    def _paths(self) -> list[Path]:
        return [Path(self.file_list.item(i).data(Qt.UserRole)["path"]) for i in range(self.file_list.count())]

    def _refresh_state(self) -> None:
        count = self.file_list.count()
        pages = sum(self.file_list.item(i).data(Qt.UserRole)["pages"] for i in range(count))
        busy = self.thread is not None
        self.empty_panel.setVisible(count == 0)
        self.remove_button.setEnabled(bool(self.file_list.selectedItems()) and not busy)
        self.clear_button.setEnabled(count > 0 and not busy)
        self.merge_button.setEnabled(count >= 2 and not busy)
        self.summary_label.setText(
            self.tr_key("count_summary", files=count, pages=pages) if count else self.tr_key("need_two")
        )
        if not busy:
            self.status_label.setText(self.tr_key("idle") if not count else self.tr_key("count_summary", files=count, pages=pages))

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.file_list,
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.duplex_radio,
            self.standard_radio,
            self.filename_edit,
            self.directory_edit,
            self.browse_button,
            self.language_combo,
        ):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        if not busy:
            self.progress.setValue(0)
        self._refresh_state()

    @Slot()
    def start_merge(self) -> None:
        try:
            output = normalized_output_path(self.directory_edit.text(), self.filename_edit.text())
        except PdfMergeError as exc:
            QMessageBox.warning(self, self.tr_key("validation_failed"), self._error_text(str(exc)))
            return
        if output.exists():
            answer = QMessageBox.question(
                self,
                self.tr_key("confirm_overwrite"),
                self.tr_key("overwrite_question", path=output),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        mode = MergeMode.DUPLEX_GUARD if self.duplex_radio.isChecked() else MergeMode.STANDARD
        self.thread = QThread(self)
        self.worker = MergeWorker(self._paths(), output, mode)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progressed.connect(self._merge_progress)
        self.worker.succeeded.connect(self._merge_succeeded)
        self.worker.failed.connect(self._merge_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._merge_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self._set_busy(True)
        self.status_label.setText(self.tr_key("starting"))
        self.progress.setRange(0, self.file_list.count())
        self.thread.start()

    @Slot(int, int, str)
    def _merge_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.status_label.setText(self.tr_key("working", current=current, total=total, name=name))

    @Slot(object)
    def _merge_succeeded(self, result: MergeResult) -> None:
        QMessageBox.information(
            self,
            self.tr_key("done_title"),
            self.tr_key(
                "done",
                path=result.output_path,
                source=result.source_pages,
                blank=result.blank_pages,
                final=result.final_pages,
            ),
        )

    @Slot(object)
    def _merge_failed(self, exc: Exception) -> None:
        if isinstance(exc, PdfValidationError):
            message = "\n".join(f"{path.name} — {self._error_text(reason)}" for path, reason in exc.issues)
        elif isinstance(exc, PdfMergeError):
            message = self._error_text(str(exc))
        else:
            message = self.tr_key("unknown_error")
        QMessageBox.critical(self, self.tr_key("validation_failed"), message)

    @Slot()
    def _merge_finished(self) -> None:
        self.thread = None
        self.worker = None
        self._set_busy(False)

    def _error_text(self, code: str) -> str:
        return self.tr_key(code) if code in {
            "file_missing", "file_encrypted", "file_unreadable", "file_invalid", "file_empty",
            "file_duplicate", "output_matches_input", "need_two_files", "output_exists",
            "output_directory_missing", "output_permission_denied", "output_write_failed",
            "output_name_empty", "output_name_invalid",
        } else self.tr_key("unknown_error")


STYLESHEET = """
QWidget#central { background: #eef3f7; color: #182633; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; }
QLabel#eyebrow { color: #237a86; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#headline { color: #102a3a; font-size: 28px; font-weight: 700; }
QLabel#subtitle, QLabel#muted, QLabel#help { color: #657682; }
QLabel#help { padding: 0 0 4px 25px; font-size: 12px; }
QLabel#sectionTitle { color: #18364a; font-size: 15px; font-weight: 700; }
QLabel#fieldLabel { color: #465a68; font-size: 12px; font-weight: 600; padding-top: 5px; }
QLabel#summary { background: #e7f3f4; color: #27646b; border-radius: 8px; padding: 10px; }
QLabel#status { color: #657682; padding-left: 3px; }
QFrame#card { background: #ffffff; border: 1px solid #dbe4ea; border-radius: 14px; }
QListWidget#fileList { background: #f8fafb; border: 1px solid #dce5ea; border-radius: 10px; padding: 6px; outline: none; }
QListWidget#fileList::item { background: #ffffff; color: #243846; border: 1px solid #e1e8ec; border-left: 4px solid #70a8ae; border-radius: 7px; padding: 7px 10px; }
QListWidget#fileList::item:selected { background: #e7f3f4; color: #18364a; border-color: #78aeb4; }
QFrame#emptyPanel { background: #f8fafb; border: none; }
QLabel#emptyIcon { color: #80aab0; font-size: 44px; }
QLabel#emptyTitle { color: #2d4656; font-size: 16px; font-weight: 650; }
QPushButton { background: #ffffff; color: #304654; border: 1px solid #cdd9df; border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { background: #f2f7f8; border-color: #8db4ba; }
QPushButton:disabled { color: #9ba8b0; background: #f3f5f6; border-color: #e1e6e9; }
QPushButton#primarySmall, QPushButton#mergeButton { background: #226d78; color: #ffffff; border: none; font-weight: 650; }
QPushButton#primarySmall:hover, QPushButton#mergeButton:hover { background: #185b65; }
QPushButton#mergeButton:disabled { background: #aebfc3; color: #eef3f4; }
QLineEdit, QComboBox { background: #ffffff; color: #203440; border: 1px solid #cad7dd; border-radius: 7px; padding: 7px 9px; }
QLineEdit:focus, QComboBox:focus { border: 2px solid #4f929b; }
QRadioButton { color: #233b49; spacing: 8px; font-weight: 600; }
QRadioButton::indicator { width: 16px; height: 16px; }
QProgressBar { background: #dce8eb; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #3c8992; border-radius: 4px; }
"""


def main() -> int:
    QApplication.setOrganizationName("PDF Merge Guard")
    QApplication.setApplicationName("PDF Merge Guard")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    windows_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if windows_font.is_file():
        QFontDatabase.addApplicationFont(str(windows_font))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())


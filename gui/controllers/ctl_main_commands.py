"""Command and helper mixin for MainWindow.

All user actions (cmd_*) and related helpers are extracted from
ControllerMainWindow to keep the main controller focused on wiring and
composition.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from PySide6.QtCore import Qt, QUrl, QObject, Signal, QThread
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDialog,
    QInputDialog,
    QMessageBox,
    QTreeWidgetItem,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from core.ModelBookmark import Node
from core.util_core import is_valid_url
from core.ServiceStorage import load_bookmarks, save_bookmarks
from core.UtilBackupManager import BackupManager, BackupTargets, BackupError
from core.DatabaseManager import DatabaseManager
from gui.ui_dialogs import (
    AiProgressDialog,
    AiReviewDialog,
    BookmarkEditDialog,
    CustomPromptDialog,
    DomainConsolidationDialog,
    FolderSelectDialog,
    RestoreDialog,
    TagEditDialog,
)
from services.ServiceAiClassifier import AIBookmarkClassifier, BookmarkNode
from services.ServiceAutoTag import AutoTagService
from services.WorkerNetwork import fetch_preview, fix_titles
from services.svc_rules import build_rules_plan
from gui.controllers.ctl_tree_ui import TreeUIController


class MainWindowCommandsMixin:
    """Grouped commands and helpers used by MainWindow."""

    # ------------------------------ window events ----------------------------
    def showEvent(self, event: Any) -> None:
        """Auto-load last bookmarks file on first window show."""
        super().showEvent(event)
        self.session_controller.on_first_show()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._resize_right_pane()

    def _resize_right_pane(self) -> None:
        if not hasattr(self, "right_panel"):
            return
        if not hasattr(self, "actions_container") or not hasattr(self, "detail_panel"):
            return
        available = self.right_panel.height()
        if available <= 0:
            return
        target = max(200, available // 2)
        self.actions_container.setMinimumHeight(target)
        self.detail_panel.setMinimumHeight(target)

    # ------------------------------ tag helpers ----------------------------
    def _on_edit_tags(self, node: Node) -> None:
        """ローカルタグ編集（DB保存）。"""
        if not node or getattr(node, "type", "") != "bookmark":
            return
        if not getattr(node, "bookmark_id", ""):
            try:
                self.bookmark_service.ensure_bookmark_ids(self.root_node)
            except Exception:
                pass
        bid = getattr(node, "bookmark_id", "") or ""
        if not bid:
            QMessageBox.warning(self, "タグ編集", "bookmark_id の付与に失敗しました。")
            return

        try:
            current = self.tag_service.get_tags(bid)
        except Exception:
            current = []

        dlg = TagEditDialog(self, current_tags=current)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self.tag_service.set_tags(bid, dlg.get_tags(), source="manual")
        except Exception as exc:
            QMessageBox.critical(self, "タグ保存失敗", f"タグの保存に失敗しました:\n{exc}")
            return

        try:
            self.detail_panel.set_node(node)
        except Exception:
            pass
        self.statusBar().showMessage("タグを保存しました", 2000)

    # ------------------------------ helpers ----------------------------
    def _open_url(self, url: str) -> None:
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard."""
        if not text:
            return
        clipboard = self.app.clipboard() if hasattr(self, "app") else None
        if clipboard:
            clipboard.setText(text)
            self.statusBar().showMessage("URLをコピーしました", 2000)
        else:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("URLをコピーしました", 2000)

    def refresh_tree(self, select_node: Optional[Node] = None) -> None:
        """Update only the tree display (called when folder structure changes)."""
        if not hasattr(self, "tree_ui"):
            return
        self._apply_dual_tree_visibility()
        self.tree_ui.refresh(select_node=select_node)
        self._restore_tree_expansion_state()

    def refresh_list(self) -> None:
        """Update only the bookmark list display."""
        self._update_workspace_header()
        nodes = self._get_display_nodes(
            current_folder=self.current_folder,
            search_query=self.search_query,
            search_hits=set(self.search_hits or set()),
        )
        self._refresh_list_internal(
            bookmark_list_view=self.bookmark_list_view,
            detail_panel=self.detail_panel,
            preview_cache=self.preview_cache,
            nodes=nodes,
            view_mode=self.view_mode,
            preview_requester=self.bookmark_list_view.request_preview_fetch,
        )

    def refresh_counts(self) -> None:
        """Update only the bookmark count labels."""
        total_all = self._count_bookmarks(self.root_node)
        total_current = self._count_bookmarks(self.current_folder) if self.current_folder else 0
        if getattr(self, "bookmarks_count_label", None) is not None:
            self.bookmarks_count_label.setText(f"{total_all:,}")
        if getattr(self, "workspace_count_label", None) is not None:
            self.workspace_count_label.setText(f"{total_current:,}")

    def _apply_dual_tree_visibility(self) -> None:
        if hasattr(self, "tree_scroll"):
            self.tree_scroll.setVisible(not self.dual_tree_mode)
        if hasattr(self, "dual_tree_splitter"):
            self.dual_tree_splitter.setVisible(self.dual_tree_mode)

    # ----------------------------- Phase 1 Safety Gate ------------------------------
    def _ensure_backup_or_abort(self, operation_name: str) -> bool:
        """3点セットバックアップを作成できなければ操作を中止する。"""
        if not self.current_file:
            QMessageBox.warning(self, "バックアップ不可", f"{operation_name} の前にHTMLを読み込んでください。")
            return False

        project_root = Path(__file__).resolve().parent.parent.parent
        db_path = project_root / "user_data.db"
        config_path = Path(getattr(self.config_manager, "config_path", project_root / "config" / "config.ini"))

        try:
            if not config_path.exists():
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text("", encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "バックアップ失敗", f"{operation_name} を開始できません。\nconfig.ini の準備に失敗しました:\n{exc}")
            return False

        try:
            if not db_path.exists():
                DatabaseManager(project_root=project_root).ensure_ready()
        except Exception as exc:
            QMessageBox.critical(self, "バックアップ失敗", f"{operation_name} を開始できません。\nuser_data.db の準備に失敗しました:\n{exc}")
            return False

        try:
            targets = BackupTargets(
                bookmarks_html=Path(self.current_file),
                user_data_db=db_path,
                config_ini=config_path,
            )
            BackupManager(project_root=project_root, keep_generations=30).create_backup(targets)
            return True
        except (BackupError, Exception) as exc:
            QMessageBox.critical(
                self,
                "バックアップ失敗",
                f"{operation_name} を開始できません。\nバックアップ作成に失敗しました:\n{exc}",
            )
            return False

    def _after_model_changed(self, select_node: Optional[Node] = None, refresh_parts: str = "all") -> None:
        """Unified handler for model changes."""
        if refresh_parts in ("all", "trees"):
            self.refresh_tree(select_node=select_node)
        if refresh_parts in ("all", "list"):
            self.refresh_list()
        self.refresh_counts()

    def _default_rules(self) -> list:
        return []

    # ----------------------------- File Commands ------------------------------
    def cmd_open(self) -> None:
        """Open bookmark HTML file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open HTML", "", "HTML Files (*.html);;All Files (*)"
        )
        if not file_path:
            return

        try:
            project_root = Path(__file__).resolve().parent.parent.parent
            config_path = Path(getattr(self.config_manager, "config_path", project_root / "config" / "config.ini"))
            DatabaseManager(project_root=project_root).migrate_if_needed(
                bookmarks_html=Path(file_path),
                config_ini=config_path,
                keep_generations=30,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"DBマイグレーションに失敗しました:\n{exc}")
            return

        try:
            root, rules, rules_path = load_bookmarks(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{exc}")
            return

        self.set_root_node_state(root)
        try:
            self.bookmark_service.ensure_bookmark_ids(root)
        except Exception:
            pass
        self.set_rules_state(rules, rules_path)
        self.set_current_file_state(file_path)
        self.current_folder = root
        self.selected_node = None

        self.search_service.rebuild(root)
        self.refresh_tree(select_node=root)
        self.refresh_list()
        self.refresh_counts()

        if hasattr(self, "left_panel") and hasattr(self.left_panel, "tree_controls"):
            self.left_panel.tree_controls.setVisible(True)
        if hasattr(self, "left_panel") and hasattr(self.left_panel, "dual_tree_button"):
            try:
                self.left_panel.dual_tree_button.setVisible(True)
            except Exception:
                pass

        self.config_manager.set("Session", "last_bookmarks_file", file_path)
        self.statusBar().showMessage(f"Loaded {file_path}", 4000)

    def cmd_save(self) -> None:
        """Save bookmark HTML file."""
        if not self.current_file:
            self.cmd_save_as()
            return

        try:
            save_bookmarks(self.current_file, self.root_node, self.rules)
            self.statusBar().showMessage(f"Saved to {self.current_file}", 4000)
            self.config_manager.set("Session", "last_bookmarks_file", self.current_file)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{exc}")

    def cmd_save_as(self) -> None:
        """Save bookmark HTML file with new name."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save As", "", "HTML Files (*.html);;All Files (*)"
        )
        if not file_path:
            return

        self.current_file = file_path
        self.cmd_save()
        self.config_manager.set("Session", "last_bookmarks_file", file_path)

    # ----------------------------- Bookmark Commands ------------------------------
    def cmd_new_folder(self) -> None:
        if not self.current_folder or self.current_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Select a folder first.")
            return

        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return

        new_node = Node("folder", name.strip())
        self.current_folder.append(new_node)
        self.refresh_tree(select_node=new_node)
        self.refresh_counts()

    def cmd_new_bookmark(self) -> None:
        if not self.current_folder or self.current_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Select a folder first.")
            return

        url, ok = QInputDialog.getText(self, "New Bookmark", "URL:")
        if not ok or not url.strip():
            return

        if not is_valid_url(url.strip()):
            QMessageBox.warning(self, "Warning", "Enter a valid URL (http/https).")
            return

        title, _ = QInputDialog.getText(self, "New Bookmark", "Title (optional):")
        node = Node("bookmark", title=title.strip() or url.strip(), url=url.strip())
        self.current_folder.append(node)
        self.search_service.add_node(node)
        self.refresh_list()
        self.refresh_counts()
        self._enqueue_preview_fetch(node)

    def cmd_rename(self) -> None:
        if not self.selected_node:
            QMessageBox.information(self, "Info", "Select an item to rename.")
            return

        name, ok = QInputDialog.getText(
            self,
            "Rename",
            "New name:",
            text=self.selected_node.title,
        )
        if not ok or not name.strip():
            return

        self.selected_node.title = name.strip()
        self.search_service.update_node(self.selected_node)
        self.refresh_list()
        self.refresh_counts()

        if self.selected_node.type == "folder":
            self.refresh_tree(select_node=self.selected_node)

    def cmd_edit_url(self) -> None:
        if not self.selected_node or self.selected_node.type != "bookmark":
            QMessageBox.information(self, "Info", "Select a bookmark to edit.")
            return

        url, ok = QInputDialog.getText(
            self,
            "Edit URL",
            "URL:",
            text=self.selected_node.url,
        )
        if not ok or not url.strip():
            return

        if not is_valid_url(url.strip()):
            QMessageBox.warning(self, "Warning", "Enter a valid URL.")
            return

        self.selected_node.url = url.strip()
        self.search_service.update_node(self.selected_node)
        self.refresh_list()
        self.refresh_counts()

    def _on_edit_bookmark(self, node: Node) -> None:
        if not node:
            return
        if node.type != "bookmark":
            self.selected_node = node
            self.cmd_rename()
            return

        dialog = BookmarkEditDialog(self, node)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_title, new_url = dialog.get_data()
        ok = self.bookmark_service.update_node(node, title=new_title, url=new_url)
        if not ok:
            QMessageBox.warning(self, "Error", "更新に失敗しました。")
            return

        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=node.parent or self.current_folder or self.root_node)
        self.refresh_list()
        self.refresh_counts()
        try:
            self.bookmark_list_view.select_node(node)
        except Exception:
            pass
        try:
            self.detail_panel.set_node(node)
        except Exception:
            pass

    def cmd_move_to_folder(self) -> None:
        if not self.selected_node or not self.root_node:
            QMessageBox.information(self, "Info", "Select an item to move.")
            return

        dialog = FolderSelectDialog(self, root_node=self.root_node, exclude_nodes=[self.selected_node])
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result:
            return

        target_folder = dialog.result
        if target_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Target must be a folder.")
            return

        try:
            self.bookmark_service.move(self.selected_node, target_folder)
        except Exception as exc:
            QMessageBox.warning(self, "Warning", f"Move failed: {exc}")
            return

        self.current_folder = target_folder
        self.refresh_tree(select_node=target_folder)
        self.refresh_list()
        self.refresh_counts()

    def cmd_move_up(self) -> None:
        if not self.selected_node or not self.selected_node.parent:
            return
        try:
            self.bookmark_service.move_up(self.selected_node)
        except Exception:
            return
        self.refresh_tree(select_node=self.selected_node)
        self.refresh_list()

    def cmd_delete(self) -> None:
        if not self.selected_node:
            QMessageBox.information(self, "Info", "Select an item to delete.")
            return
        self._delete_node(self.selected_node)

    def _delete_node(self, node: Node) -> None:
        if not node or not node.parent:
            return

        res = QMessageBox.question(self, "Delete", f"Delete '{node.title}'?")
        if res != QMessageBox.StandardButton.Yes:
            return

        parent = node.parent
        if node.type == "bookmark":
            self.search_service.remove_node(node)
        elif node.type == "folder":
            for bm in self._iter_bookmarks(node):
                self.search_service.remove_node(bm)

        parent.remove_child(node)
        self.refresh_tree(select_node=parent)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage(f"Deleted: {node.title}", 2000)

    def _iter_bookmarks(self, node: Node) -> Iterable[Node]:
        for child in getattr(node, "children", []) or []:
            if child.type == "bookmark":
                yield child
            elif child.type == "folder":
                yield from self._iter_bookmarks(child)

    def cmd_delete_duplicates(self) -> None:
        if not self.current_folder:
            return
        if not self._ensure_backup_or_abort("重複削除"):
            return

        project_root = Path(__file__).resolve().parent.parent.parent
        log_path = project_root / "logs" / "cleanup_history.log"

        removed, _details = self.bookmark_service.remove_duplicates(
            self.current_folder,
            log_file_path=log_path,
        )

        if removed > 0:
            QMessageBox.information(
                self,
                "重複削除完了",
                f"{removed} 件の重複ブックマークを削除しました。\n詳細はログ（{log_path}）を確認してください。",
            )
        else:
            QMessageBox.information(self, "完了", "重複したブックマークは見つかりませんでした。")

        self.search_service.rebuild(self.root_node)
        self.refresh_list()
        self.refresh_tree(select_node=self.current_folder)
        self.refresh_counts()
        self.statusBar().showMessage(f"Removed {removed} duplicate bookmarks", 3000)

    def cmd_merge_duplicate_folders(self) -> None:
        if not self.current_folder:
            return
        if not self._ensure_backup_or_abort("重複フォルダの統合"):
            return

        removed = self.bookmark_service.merge_duplicate_folders(self.current_folder)
        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=self.current_folder)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage(f"Merged {removed} duplicate folders", 3000)

    def cmd_consolidate_domain(self) -> None:
        if not self.root_node:
            return

        stats = self.bookmark_service.get_domain_statistics(self.root_node)
        if not stats:
            QMessageBox.information(self, "Info", "ドメイン統計が空です。")
            return

        dialog = DomainConsolidationDialog(stats, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
            return

        domain, folder_name = dialog.result_data
        if not self._ensure_backup_or_abort(f"ドメイン統合（{domain}）"):
            return
        moved = self.bookmark_service.consolidate_by_domain(self.root_node, domain, folder_name)
        if moved <= 0:
            QMessageBox.information(self, "完了", f"{domain} の対象ブックマークは見つかりませんでした。")
            return

        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=self.current_folder or self.root_node)
        self.refresh_list()
        self.refresh_counts()
        QMessageBox.information(self, "完了", f"{domain} のブックマークを {moved} 件統合しました。")

    # ----------------------------- Tree Commands ------------------------------
    def cmd_expand_all(self) -> None:
        trees_to_update = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, "folder_tree_left") and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, "folder_tree_right") and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            if hasattr(self, "folder_tree") and self.folder_tree:
                trees_to_update.append(self.folder_tree)

        for tree in trees_to_update:
            tree.expandAll()
        if trees_to_update:
            self._save_tree_expansion_state(trees_to_update[0])

    def cmd_collapse_all(self) -> None:
        trees_to_update = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, "folder_tree_left") and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, "folder_tree_right") and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            if hasattr(self, "folder_tree") and self.folder_tree:
                trees_to_update.append(self.folder_tree)

        for tree in trees_to_update:
            tree.collapseAll()
        if trees_to_update:
            self._save_tree_expansion_state(trees_to_update[0])

    def cmd_expand_current(self) -> None:
        current_folder = self.current_folder
        if not current_folder or current_folder.type != "folder":
            return

        trees_to_update = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, "folder_tree_left") and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, "folder_tree_right") and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            if hasattr(self, "folder_tree") and self.folder_tree:
                trees_to_update.append(self.folder_tree)

        for tree in trees_to_update:
            item = self._find_tree_item_by_node(tree, current_folder)
            if item:
                tree.expandItem(item)

    def cmd_collapse_current(self) -> None:
        current_folder = self.current_folder
        if not current_folder or current_folder.type != "folder":
            return

        trees_to_update = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, "folder_tree_left") and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, "folder_tree_right") and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            if hasattr(self, "folder_tree") and self.folder_tree:
                trees_to_update.append(self.folder_tree)

        for tree in trees_to_update:
            item = self._find_tree_item_by_node(tree, current_folder)
            if item:
                tree.collapseItem(item)

    def _find_tree_item_by_node(self, tree, node: Node) -> Optional[Any]:
        def walk(item: QTreeWidgetItem) -> Optional[QTreeWidgetItem]:
            item_node = item.data(0, Qt.ItemDataRole.UserRole)
            if item_node is node:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
            return None

        for i in range(tree.topLevelItemCount()):
            found = walk(tree.topLevelItem(i))
            if found:
                return found
        return None

    def _get_folder_path(self, node: Node) -> str:
        path_parts = []
        current = node
        while current and current.parent:
            path_parts.insert(0, current.title or "Untitled")
            current = current.parent
        return "/".join(path_parts) if path_parts else ""

    def _save_tree_expansion_state(self, tree) -> None:
        import json

        expanded_paths: List[str] = []

        def collect_expanded(item: QTreeWidgetItem):
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node and node.type == "folder" and item.isExpanded():
                path = self._get_folder_path(node)
                if path:
                    expanded_paths.append(path)
            for i in range(item.childCount()):
                collect_expanded(item.child(i))

        for i in range(tree.topLevelItemCount()):
            collect_expanded(tree.topLevelItem(i))

        expanded_json = json.dumps(expanded_paths, ensure_ascii=False)
        self.config_manager.set("Session", "tree_expanded_paths", expanded_json)
        self.logger.debug(f"Saved tree expansion state: {len(expanded_paths)} folders")

    def _restore_tree_expansion_state(self) -> None:
        import json

        expanded_json = self.config_manager.get("Session", "tree_expanded_paths", "")
        if not expanded_json:
            return

        try:
            expanded_paths = json.loads(expanded_json)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning("Failed to parse tree expansion state")
            return

        if not expanded_paths:
            return

        trees_to_restore = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, "folder_tree_left") and self.folder_tree_left:
                trees_to_restore.append(self.folder_tree_left)
            if hasattr(self, "folder_tree_right") and self.folder_tree_right:
                trees_to_restore.append(self.folder_tree_right)
        else:
            if hasattr(self, "folder_tree") and self.folder_tree:
                trees_to_restore.append(self.folder_tree)

        for tree in trees_to_restore:
            self._apply_expansion_state_to_tree(tree, expanded_paths)

    def _apply_expansion_state_to_tree(self, tree, expanded_paths: List[str]) -> None:
        path_to_node = {}

        def build_path_map(node: Node, current_path: str = ""):
            if node.type == "folder":
                if current_path:
                    path_to_node[current_path] = node
                for child in node.children:
                    if child.type == "folder":
                        child_path = (
                            f"{current_path}/{child.title or 'Untitled'}"
                            if current_path
                            else (child.title or "Untitled")
                        )
                        build_path_map(child, child_path)

        build_path_map(self.root_node)
        expanded_set = set(expanded_paths)

        def expand_items(item: QTreeWidgetItem):
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node and node.type == "folder":
                path = self._get_folder_path(node)
                if path in expanded_set:
                    tree.expandItem(item)
            for i in range(item.childCount()):
                expand_items(item.child(i))

        for i in range(tree.topLevelItemCount()):
            expand_items(tree.topLevelItem(i))

    # ----------------------------- Classification Commands ------------------------------
    def cmd_show_classify_preview(self) -> None:
        base = self.current_folder if self.current_folder else self.root_node
        plan = build_rules_plan(base, self.rules or {})
        if not plan:
            QMessageBox.information(self, "Classify", "No rules or matching bookmarks.")
            return

        lines = [f"{folder}: {len(nodes)}" for folder, nodes in plan.items()]
        preview = "\n".join(lines)
        res = QMessageBox.question(self, "Rule-based Classification", preview + "\n\nApply this plan?")
        if res != QMessageBox.StandardButton.Yes:
            return

        if not self._ensure_backup_or_abort("ルールベース分類"):
            return

        for folder_name, nodes in plan.items():
            target = self.bookmark_service.find_or_create_folder(base, folder_name)
            for node in nodes:
                try:
                    self.bookmark_service.move_to_folder(node, target)
                except ValueError as e:
                    self.logger.warning(f"Failed to move {node.title}: {e}")

        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=base)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage("Rule-based classification applied", 4000)

    def cmd_smart_classify(self) -> None:
        base = self.current_folder if self.current_folder else self.root_node
        nodes = list(self.bookmark_service.iter_bookmarks(base))
        if not nodes:
            QMessageBox.information(self, "Classify", "No bookmarks to classify.")
            return

        dialog = CustomPromptDialog(self, title="追加指示（任意）", previous_prompts=[])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            additional_prompt = None
        else:
            additional_prompt = dialog.result or None

        try:
            classifier = AIBookmarkClassifier(config_path=str(self.config_manager.config_path))
            priority_terms = self.config_manager.get_priority_terms()
            node_map: Dict[BookmarkNode, Node] = {}
            items: List[BookmarkNode] = []

            for node in nodes:
                bn = BookmarkNode(title=node.title or "", url=node.url or "")
                items.append(bn)
                node_map[bn] = node

            model_name = self.config_manager.get("AI", "model", fallback="gemini-1.5-flash")
            chunk_size = int(self.config_manager.get("AI", "chunk_size", fallback="40") or 40)
            sanitize_urls = str(self.config_manager.get("AI", "sanitize_urls", fallback="true")).lower() in (
                "1",
                "true",
                "yes",
                "on",
            )

            estimate = classifier.estimate_cost(
                items,
                priority_terms=priority_terms,
                additional_prompt=additional_prompt,
                chunk_size=chunk_size,
                model_name=model_name,
                sanitize_urls=sanitize_urls,
            )
            if estimate.input_cost_usd_est <= 0 or estimate.output_cost_usd_est_range[0] < 0:
                QMessageBox.critical(
                    self,
                    "AI実行不可（単価未設定）",
                    "Phase 2 Safety仕様により、AI実行前にコスト提示と承認が必須です。\n"
                    "config/config.ini の [AI] input_cost_per_1m_tokens / output_cost_per_1m_tokens を設定してください。",
                )
                return

            msg = (
                "AI分類を実行しますか？\n\n"
                f"- モデル: {estimate.model}\n"
                f"- 対象: {estimate.items} 件（{estimate.chunks} チャンク）\n"
                f"- 推定入力: {estimate.input_tokens_est:,} tokens / ${estimate.input_cost_usd_est:.6f}\n"
                f"- 推定出力: {estimate.output_tokens_est_range[0]:,}〜{estimate.output_tokens_est_range[1]:,} tokens "
                f"/ ${estimate.output_cost_usd_est_range[0]:.6f}〜${estimate.output_cost_usd_est_range[1]:.6f}\n"
            )
            res = QMessageBox.question(self, "AIコスト承認", msg)
            if res != QMessageBox.StandardButton.Yes:
                return

            if not self._ensure_backup_or_abort("AI分類"):
                return

            cancel_flag = {"cancelled": False}
            progress_dialog = AiProgressDialog(self, title="AI分類", total=len(items))
            try:
                progress_dialog.cancel_btn.clicked.connect(lambda: cancel_flag.__setitem__("cancelled", True))
            except Exception:
                pass

            class _AiWorker(QObject):
                progress = Signal(int, int, int, int)
                finished = Signal(object, object)

                def run(self):
                    try:
                        classifier.set_progress_callback(lambda a, b, c, d: self.progress.emit(a, b, c, d))
                        r = classifier.classify_bookmarks(
                            items,
                            priority_terms=priority_terms,
                            max_items=self.max_smart_items,
                            additional_prompt=additional_prompt,
                            chunk_size=chunk_size,
                            model_name=model_name,
                            sanitize_urls=sanitize_urls,
                            cancel_checker=lambda: cancel_flag.get("cancelled", False),
                        )
                        self.finished.emit(r, None)
                    except Exception as e:
                        self.finished.emit(None, e)

            thread = QThread(self)
            worker = _AiWorker()
            worker.moveToThread(thread)
            worker.progress.connect(progress_dialog.update_progress)

            result_holder = {"result": None, "error": None}

            def _on_finished(r, e):
                result_holder["result"] = r
                result_holder["error"] = e
                progress_dialog.accept()

            worker.finished.connect(_on_finished)
            thread.started.connect(worker.run)
            thread.start()

            if progress_dialog.exec() != QDialog.DialogCode.Accepted:
                cancel_flag["cancelled"] = True
                try:
                    classifier.cancel()
                except Exception:
                    pass
                thread.quit()
                thread.wait(1000)
                return

            thread.quit()
            thread.wait(1000)

            if result_holder["error"] is not None:
                raise result_holder["error"]

            result = result_holder["result"]
        except Exception as exc:
            QMessageBox.critical(self, "AI Classify", f"AI分類に失敗しました:\n{exc}")
            return

        if not result.plan:
            QMessageBox.information(self, "AI Classify", "分類結果が空でした。")
            return

        review_rows = []
        for item, folder, conf, reason in getattr(result, "decisions", []) or []:
            node = node_map.get(item)
            if not node:
                continue
            try:
                from_folder = self._get_folder_path(node.parent) if node.parent else ""
            except Exception:
                from_folder = ""
            review_rows.append(
                {
                    "node": node,
                    "from_folder": from_folder,
                    "to_folder": folder,
                    "title": node.title or "",
                    "url": node.url or "",
                    "confidence": conf,
                    "reason": reason,
                }
            )

        dlg = AiReviewDialog(self, rows=review_rows)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected_rows()
        if not selected:
            QMessageBox.information(self, "AI Classify", "適用する項目がありません。")
            return

        ai_root = self.bookmark_service.get_or_create_ai_root(self.root_node)
        review_folder = self.bookmark_service.get_or_create_ai_review_folder(self.root_node)
        selected_set = set(id(r.get("node")) for r in selected if r.get("node") is not None)

        for row in selected:
            node = row.get("node")
            folder_name = str(row.get("to_folder") or "Unsorted")
            if not node:
                continue
            target = self.bookmark_service.ai_find_or_create_folder(self.root_node, folder_name)
            try:
                self.bookmark_service.move_to_folder(node, target)
            except ValueError as e:
                self.logger.warning(f"Failed to move {getattr(node, 'title', '')}: {e}")

        if dlg.should_send_excluded_to_review():
            for row in review_rows:
                node = row.get("node")
                if not node:
                    continue
                if id(node) in selected_set:
                    continue
                try:
                    self.bookmark_service.move_to_folder(node, review_folder)
                except Exception:
                    pass

        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=base)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage("AI classification completed", 4000)

    # ----------------------------- Restore / Undo ------------------------------
    def _restart_app(self) -> None:
        python = sys.executable
        args = [python] + sys.argv
        os.execv(python, args)

    def _get_backup_paths(self):
        project_root = Path(__file__).resolve().parent.parent.parent
        db_path = project_root / "user_data.db"
        config_path = Path(getattr(self.config_manager, "config_path", project_root / "config" / "config.ini"))
        return project_root, db_path, config_path

    def cmd_undo_latest_backup(self) -> None:
        if not self.current_file:
            QMessageBox.warning(self, "Undo不可", "先にHTMLを読み込んでください。")
            return
        project_root, db_path, config_path = self._get_backup_paths()
        bm = BackupManager(project_root=project_root, keep_generations=30)
        backups = bm.list_backups()
        if not backups:
            QMessageBox.information(self, "Undo", "バックアップが見つかりません。")
            return
        try:
            bm.restore_backup(
                backup_dir=backups[0],
                targets=BackupTargets(
                    bookmarks_html=Path(self.current_file),
                    user_data_db=db_path,
                    config_ini=config_path,
                ),
            )
        except Exception as e:
            QMessageBox.critical(self, "復元失敗", f"復元に失敗しました:\n{e}")
            return
        QMessageBox.information(self, "復元完了", "復元が完了しました。アプリを再起動します。")
        self._restart_app()

    def cmd_restore_from_backup(self) -> None:
        if not self.current_file:
            QMessageBox.warning(self, "復元不可", "先にHTMLを読み込んでください。")
            return
        project_root, db_path, config_path = self._get_backup_paths()
        bm = BackupManager(project_root=project_root, keep_generations=30)
        backups = bm.list_backups()
        if not backups:
            QMessageBox.information(self, "復元", "バックアップが見つかりません。")
            return
        names = [p.name for p in backups]
        dlg = RestoreDialog(self, backups=names)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected_backup:
            return
        backup_dir = project_root / "backups" / dlg.selected_backup
        try:
            bm.restore_backup(
                backup_dir=backup_dir,
                targets=BackupTargets(
                    bookmarks_html=Path(self.current_file),
                    user_data_db=db_path,
                    config_ini=config_path,
                ),
            )
        except Exception as e:
            QMessageBox.critical(self, "復元失敗", f"復元に失敗しました:\n{e}")
            return
        QMessageBox.information(self, "復元完了", "復元が完了しました。アプリを再起動します。")
        self._restart_app()

    # ----------------------------- Local Auto-Tag ------------------------------
    def _run_local_auto_tag(self, *, allow_network: bool) -> None:
        base = self.root_node
        if not base:
            return
        assigned = 0
        try:
            assigned = self.bookmark_service.ensure_bookmark_ids(base)
        except Exception:
            assigned = 0

        nodes = list(self.bookmark_service.iter_bookmarks(base))
        if not nodes:
            QMessageBox.information(self, "ローカル自動タグ", "対象ブックマークがありません。")
            return

        if not self._ensure_backup_or_abort("ローカル自動タグ（rule）"):
            return

        proxy_info = None
        if allow_network:
            proxy_info = self.config_manager.get_proxies_for_requests(use_proxy=self.use_proxy)

        try:
            auto = AutoTagService(project_root=Path(__file__).resolve().parent.parent.parent)
            r = auto.auto_tag(nodes=nodes, allow_network=allow_network, proxy_info=proxy_info)
        except Exception as exc:
            QMessageBox.critical(self, "ローカル自動タグ", f"実行に失敗しました:\n{exc}")
            return

        QMessageBox.information(
            self,
            "ローカル自動タグ",
            "完了:\n"
            f"- タグ保存: {r.tagged}/{r.processed} 件（scrape={r.scraped}）\n"
            f"- bookmark_id 未付与でスキップ: {r.missing_id} 件\n"
            f"- DB保存失敗: {r.save_failed} 件\n"
            + (f"\n※ bookmark_id を {assigned} 件に付与しました。永続化のためHTMLを保存してください。" if assigned else ""),
        )
        try:
            if self.selected_node:
                self.detail_panel.set_node(self.selected_node)
        except Exception:
            pass

    def cmd_local_auto_tag_offline(self) -> None:
        self._run_local_auto_tag(allow_network=False)

    def cmd_local_auto_tag_online(self) -> None:
        if not self.network_updates_enabled:
            ans = QMessageBox.question(
                self,
                "ネットワーク無効",
                "オンライン自動タグ分類にはネットワーク取得の許可が必要です。\n"
                "ネットワーク取得を有効化しますか？",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            self.network_updates_enabled = True
        self._run_local_auto_tag(allow_network=True)

    # ----------------------------- Network Commands ------------------------------
    def cmd_check_proxy(self) -> None:
        settings = self.config_manager.get_proxy_settings()
        if not settings:
            QMessageBox.information(self, "Proxy", "Proxy is disabled or not configured.")
            return
        summary = settings.get("url", "")
        QMessageBox.information(self, "Proxy", f"Using proxy: {summary}")

    def cmd_fix_titles_from_url(self) -> None:
        if not self._ensure_backup_or_abort("タイトル取得（URLから更新）"):
            return

        self._enable_network_updates("タイトル取得")
        nodes = list(self.bookmark_service.iter_bookmarks(self.current_folder)) if self.current_folder else []
        if not nodes:
            QMessageBox.information(self, "Info", "No bookmarks to update.")
            return

        self._titlefix_nodes = nodes
        proxy_info = self.config_manager.get_proxies_for_requests(use_proxy=self.use_proxy)
        self.statusBar().showMessage("Starting title fix...", 2000)
        self.worker_bus.submit(
            fix_titles,
            nodes,
            self.worker_bus.ui_queue,
            proxy_info,
            self.fetch_timeout,
            None,
            None,
        )

    def cmd_fetch_preview(self) -> None:
        if not self.selected_node or self.selected_node.type != "bookmark":
            QMessageBox.information(self, "Info", "プレビュー取得はブックマークを選択してください。")
            return

        self._enable_network_updates("プレビュー取得")
        self._enqueue_preview_fetch(self.selected_node)

    def _enable_network_updates(self, reason: str) -> None:
        if not self.network_updates_enabled:
            self.network_updates_enabled = True
            self.statusBar().showMessage(f"ネットワーク更新を有効化: {reason}", 3000)

    def _enqueue_preview_fetch(self, node) -> None:
        if not node or not getattr(node, "url", None):
            return
        if not self.network_updates_enabled:
            return

        proxy_info = self.config_manager.get_proxies_for_requests(use_proxy=self.use_proxy)
        self.worker_bus.submit(
            fetch_preview,
            node.url,
            self.worker_bus.ui_queue,
            proxy_info,
            self.fetch_timeout,
        )

    # ----------------------------- View Commands ------------------------------
    def cmd_set_view_mode(self, mode: str) -> None:
        if mode not in ("card", "list"):
            return

        self.view_mode = mode

        if hasattr(self, "card_mode_action"):
            self.card_mode_action.setChecked(mode == "card")
        if hasattr(self, "list_mode_action"):
            self.list_mode_action.setChecked(mode == "list")

        if hasattr(self, "topbar") and self.topbar is not None:
            self.topbar.set_view_mode(mode)
        elif hasattr(self, "mode_chip"):
            display_text = "Card" if mode == "card" else "List"
            self.mode_chip.setText(f"表示: {display_text}")

        if hasattr(self, "view_buttons"):
            for key, btn in self.view_buttons.items():
                btn.setObjectName("tonalButton" if key == mode else "ghostButton")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()

        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage(f"Switched to {mode.title()} Mode", 2000)

    def _set_dual_tree_mode(self, enabled: bool) -> None:
        self.dual_tree_mode = bool(enabled)
        if hasattr(self, "dual_tree_action"):
            self.dual_tree_action.setChecked(self.dual_tree_mode)
        if hasattr(self, "dual_tree_button"):
            self.dual_tree_button.setChecked(self.dual_tree_mode)
            try:
                self.dual_tree_button.setText("1画面" if self.dual_tree_mode else "2画面")
            except Exception:
                pass
        self.refresh_tree(select_node=self.current_folder or self.root_node)

    def _apply_sort(self, sort_by: str) -> None:
        if not self.current_folder:
            return

        ok = self.bookmark_service.sort_bookmarks(sort_by, parent_node=self.current_folder)
        if not ok:
            return
        self.statusBar().showMessage(f"Sorted by {sort_by}", 2000)
        self.refresh_tree(select_node=self.current_folder)
        self.refresh_list()

    def _post_ui_built(self) -> None:
        self.tree_ui = TreeUIController(
            tree_controller=self.tree_controller,
            get_root=lambda: self.root_node,
            get_current_folder=lambda: self.current_folder,
            get_search_hits=lambda: self.search_hits,
            get_search_query=lambda: self.search_query,
            get_dual_tree_mode=lambda: self.dual_tree_mode,
            get_trees=self._get_visible_trees,
            get_all_trees=self._get_all_trees,
        )

    def _get_visible_trees(self):
        trees = [self.folder_tree]
        if self.dual_tree_mode:
            trees.extend([self.folder_tree_left, self.folder_tree_right])
        return trees

    def _get_all_trees(self):
        return [self.folder_tree, self.folder_tree_left, self.folder_tree_right]

    def _install_main_layout(self) -> None:
        from PySide6.QtWidgets import QSplitter

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.topbar)

        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        content_layout.addWidget(splitter)

        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.right_panel)

        splitter.setSizes([600, 300])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(content_widget, 1)

    def _get_display_nodes(
        self,
        *,
        current_folder: Optional[Node],
        search_query: str,
        search_hits: Set[Node],
    ) -> List[Node]:
        if not current_folder:
            return []

        base_nodes = [ch for ch in current_folder.children if ch.type == "bookmark"]
        if not search_query:
            return base_nodes

        filtered: List[Node] = []
        for node in search_hits:
            if self._is_descendant_of(node, current_folder):
                filtered.append(node)
        return filtered

    def _is_descendant_of(self, node: Node, folder: Node) -> bool:
        cur = node.parent
        while cur:
            if cur is folder:
                return True
            cur = cur.parent
        return False

    def _count_bookmarks(self, root_node: Optional[Node]) -> int:
        if not root_node:
            return 0
        return sum(1 for _ in self._iter_bookmarks(root_node))

    def _refresh_list_internal(
        self,
        *,
        bookmark_list_view,
        detail_panel,
        preview_cache,
        nodes: List[Node],
        view_mode: str,
        preview_requester,
    ) -> None:
        bookmark_list_view.set_items(nodes, view_mode=view_mode)

        for node in nodes:
            if node.url and node.url not in preview_cache:
                preview_cache[node.url] = True
                preview_requester(node)

        if not nodes:
            detail_panel.clear()

    def _update_workspace_header(self) -> None:
        label = getattr(self, "workspace_title_label", None)
        if label is None:
            return
        folder = self.current_folder or self.root_node
        label.setText(self._format_folder_path(folder))

    def _format_folder_path(self, folder: Node) -> str:
        parts = []
        cur = folder
        while cur is not None:
            if getattr(cur, "type", "") == "folder":
                parts.append(cur.title or "Untitled")
            cur = getattr(cur, "parent", None)
        parts = list(reversed(parts)) if parts else ["Workspace"]
        return " / ".join(parts)


__all__ = ["MainWindowCommandsMixin"]

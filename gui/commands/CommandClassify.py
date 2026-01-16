"""
Bookmark classification commands.
Handles rule-based and AI-based classification.
"""

from typing import Dict, List

from PySide6.QtWidgets import QMessageBox

from core.ModelBookmark import Node
from gui.layout.LayoutDialogs import CustomPromptDialog
from services.legacy.ServiceAiClassifierLegacy import AIBookmarkClassifier, BookmarkNode
from services.ServicePlans import build_rules_plan


class ClassifyCommands:
    """Commands for bookmark classification."""

    def __init__(self, window):
        """
        Initialize with main window reference.
        
        Args:
            window: MainWindow instance
        """
        self.window = window

    def rule_classify(self) -> None:
        """Classify bookmarks using predefined rules."""
        base = self.window.current_folder if self.window.current_folder else self.window.root_node
        plan = build_rules_plan(base, self.window.rules or {})
        if not plan:
            QMessageBox.information(self.window, "Classify", "No rules or matching bookmarks.")
            return
        
        lines = [f"{folder}: {len(nodes)}" for folder, nodes in plan.items()]
        preview = "\n".join(lines)
        res = QMessageBox.question(
            self.window,
            "Rule-based Classification",
            preview + "\n\nApply this plan?"
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        
        for folder_name, nodes in plan.items():
            target = self.window.bookmark_service.find_or_create_folder(base, folder_name)
            for node in nodes:
                try:
                    self.window.bookmark_service.move_to_folder(node, target)
                except ValueError as e:
                    self.window.logger.warning(f"Failed to move {node.title}: {e}")
        
        # Structure changed, rebuild search and refresh
        self.window.search_service.rebuild(self.window.root_node)
        self.window.refresh_tree(select_node=base)
        self.window.refresh_list()
        self.window.refresh_counts()
        self.window.statusBar().showMessage("Rule-based classification applied", 4000)

    def ai_classify(self) -> None:
        """Classify bookmarks using AI."""
        base = self.window.current_folder if self.window.current_folder else self.window.root_node
        nodes = list(self.window.bookmark_service.iter_bookmarks(base))
        if not nodes:
            QMessageBox.information(self.window, "Classify", "No bookmarks to classify.")
            return

        # Get additional prompt from user
        dialog = CustomPromptDialog(self.window, title="追加指示（任意）", previous_prompts=[])
        if dialog.exec() != dialog.Accepted:
            additional_prompt = None
        else:
            additional_prompt = dialog.result or None

        try:
            classifier = AIBookmarkClassifier(
                config_path=str(self.window.config_manager.config_path)
            )
            priority_terms = self.window.config_manager.get_priority_terms()
            node_map: Dict[BookmarkNode, Node] = {}
            items: List[BookmarkNode] = []
            
            for node in nodes:
                bn = BookmarkNode(title=node.title or "", url=node.url or "")
                items.append(bn)
                node_map[bn] = node
            
            result = classifier.classify_bookmarks(
                items,
                priority_terms=priority_terms,
                max_items=self.window.max_smart_items,
                additional_prompt=additional_prompt,
            )
        except Exception as exc:
            QMessageBox.critical(self.window, "AI Classify", f"AI分類に失敗しました:\n{exc}")
            return

        if not result.plan:
            QMessageBox.information(self.window, "AI Classify", "分類結果が空でした。")
            return

        # Apply classification
        for folder_name, items in result.plan.items():
            target = self.window.bookmark_service.find_or_create_folder(base, folder_name)
            for item in items:
                node = node_map.get(item)
                if not node:
                    continue
                try:
                    self.window.bookmark_service.move_to_folder(node, target)
                except ValueError as e:
                    self.window.logger.warning(f"Failed to move {node.title}: {e}")

        # Structure changed, rebuild search and refresh
        self.window.search_service.rebuild(self.window.root_node)
        self.window.refresh_tree(select_node=base)
        self.window.refresh_list()
        self.window.refresh_counts()
        self.window.statusBar().showMessage("AI classification completed", 4000)

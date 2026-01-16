"""View-related commands (view mode, sorting)."""


class ViewCommands:
    """Commands for changing view and simple list ordering."""

    def __init__(self, window):
        self.window = window

    def set_view_mode(self, mode: str) -> None:
        if mode not in ("card", "list"):
            return

        self.window.view_mode = mode

        # Update checkboxes
        if hasattr(self.window, "card_mode_action"):
            self.window.card_mode_action.setChecked(mode == "card")
        if hasattr(self.window, "list_mode_action"):
            self.window.list_mode_action.setChecked(mode == "list")

        # Update top bar chip
        if hasattr(self.window, "topbar") and self.window.topbar is not None:
            self.window.topbar.set_view_mode(mode)
        elif hasattr(self.window, "mode_chip"):
            display_text = "Card" if mode == "card" else "List"
            self.window.mode_chip.setText(f"表示: {display_text}")

        # Update view toggle button styles
        if hasattr(self.window, "view_buttons"):
            for key, btn in self.window.view_buttons.items():
                btn.setObjectName("tonalButton" if key == mode else "ghostButton")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()

        # Refresh only list/counts (tree doesn't depend on view_mode)
        self.window.refresh_list()
        self.window.refresh_counts()
        self.window.statusBar().showMessage(f"Switched to {mode.title()} Mode", 2000)

    def sort(self, sort_by: str) -> None:
        if not self.window.current_folder:
            return

        if sort_by == "title":
            self.window.bookmark_service.sort_children(self.window.current_folder, "title")
            self.window.statusBar().showMessage("Sorted by title", 2000)
        elif sort_by == "domain":
            self.window.bookmark_service.sort_children(self.window.current_folder, "url")
            self.window.statusBar().showMessage("Sorted by domain", 2000)
        else:
            return

        self.window.refresh_list()

import tkinter as tk
from tkinter import simpledialog
import customtkinter as ctk
from gui.theme import Colors, Fonts

class CustomPromptDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, previous_prompts=None):
        self.previous_prompts = previous_prompts or []
        super().__init__(parent, title)

    def body(self, master):
        self.result = None
        # Using customtkinter widgets inside the dialog
        if self.previous_prompts:
            ctk.CTkLabel(master, text="現在の指示:", font=("", 12, "bold"), text_color=Colors.TEXT_SECONDARY).pack(anchor="w", padx=5, pady=(5, 0))
            
            # Use CTkTextbox for read-only history if possible, or standard Text with styling
            # Standard Text is easier to fit in simpledialog geometry management sometimes, but let's try CTk
            history_text = ctk.CTkTextbox(master, height=80, width=400, border_width=1)
            history_text.pack(padx=5, pady=2, fill="x", expand=True)
            display_str = "\n".join([f"- {p}" for p in self.previous_prompts])
            history_text.insert("1.0", display_str)
            history_text.configure(state="disabled", fg_color=Colors.BACKGROUND, text_color=Colors.TEXT_PRIMARY)
        
        ctk.CTkLabel(master, text="追加の指示を入力:", font=("", 12, "bold"), text_color=Colors.TEXT_PRIMARY).pack(anchor="w", padx=5, pady=(10, 0))
        self.text_widget = ctk.CTkTextbox(master, height=100, width=400, border_width=1)
        self.text_widget.pack(padx=5, pady=5, fill="both", expand=True)
        
        # simpledialog expects the initial focus widget return
        return self.text_widget

    def apply(self):
        self.result = self.text_widget.get("1.0", "end-1c").strip()

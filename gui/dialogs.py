import tkinter as tk
from tkinter import simpledialog
import ttkbootstrap as tb

class CustomPromptDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, previous_prompts=None):
        self.previous_prompts = previous_prompts or []
        super().__init__(parent, title)

    def body(self, master):
        self.result = None
        if self.previous_prompts:
            tb.Label(master, text="現在の指示:", font=("", 10, "bold"), bootstyle="info").pack(anchor="w", padx=5, pady=(5, 0))
            history_text = tk.Text(master, height=4, width=60, wrap="word", relief="flat", borderwidth=1)
            history_text.pack(padx=5, pady=2, fill="x", expand=True)
            display_str = "\n".join([f"- {p}" for p in self.previous_prompts])
            history_text.insert("1.0", display_str)
            history_text.config(state="disabled", background="#f0f0f0")
        
        tb.Label(master, text="追加の指示を入力:", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(10, 0))
        self.text_widget = tk.Text(master, height=8, width=60, wrap="word") 
        self.text_widget.pack(padx=5, pady=5, fill="both", expand=True)
        return self.text_widget

    def apply(self):
        self.result = self.text_widget.get("1.0", "end-1c").strip()

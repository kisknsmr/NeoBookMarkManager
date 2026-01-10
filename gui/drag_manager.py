import tkinter as tk
import customtkinter as ctk
from typing import Optional, Callable, List, Any, Tuple
from core.logger import logger
from gui.theme import Colors, Fonts, Dims

class DragManager:
    """
    Manages interactive drag-and-drop operations with 'ghost' visual feedback.
    Mimics web-like drag behavior.
    """
    
    def __init__(self, root: ctk.CTk, on_drop: Optional[Callable[[Any, Any], None]] = None):
        """
        Args:
            root: Root window/widget
            on_drop: Callback function (source_item, target_item) -> None
        """
        self.root = root
        self.on_drop = on_drop
        
        self.dragging = False
        self.drag_data = None
        self.ghost_window: Optional[ctk.CTkToplevel] = None
        self.source_widget = None
        
        # Registry of potential drop targets: list of (widget, data)
        self.drop_targets: List[Tuple[tk.Widget, Any]] = []
        
        self.current_highlight: Optional[tk.Widget] = None
        
        # Offset to center the ghost or keep it relative to click
        self.offset_x = 0
        self.offset_y = 0
        
        # ドラッグ開始の閾値（ピクセル）
        self.drag_threshold = 10
        self.start_x = 0
        self.start_y = 0
        self.drag_started = False
        
        # グローバルなButtonRelease-1をbind（どこで離してもend_dragが呼ばれる）
        root.bind_all("<ButtonRelease-1>", self._global_end_drag)

    def register_target(self, widget: tk.Widget, data: Any):
        """Registers a widget as a potential drop target."""
        self.drop_targets.append((widget, data))

    def clear_targets(self):
        """Clears all registered drop targets."""
        self.drop_targets.clear()

    def start_drag(self, widget: tk.Widget, data: Any, event):
        """Initiates the drag operation (準備のみ、実際の開始は閾値を超えてから)."""
        if self.dragging:
            return

        self.source_widget = widget
        self.drag_data = data
        
        # 開始位置を記録
        self.start_x = event.x_root
        self.start_y = event.y_root
        self.offset_x = event.x
        self.offset_y = event.y
        self.drag_started = False
        self.dragging = True  # ドラッグモードに入る（ただしゴーストはまだ作成しない）

    def _create_ghost(self, source_widget):
        """Creates the semi-transparent ghost window."""
        self.ghost_window = ctk.CTkToplevel(self.root)
        self.ghost_window.overrideredirect(True) # Remove title bar/borders
        self.ghost_window.attributes("-alpha", 0.7) # Transparency
        self.ghost_window.attributes("-topmost", True)
        
        # Prevent ghost from stealing focus
        self.ghost_window.transient(self.root)
        
        # Create a visual representation inside the ghost
        # Ideally we take a screenshot or clone the widget visuals.
        # For performance/simplicity, we create a simplified label with same text.
        
        # Try to get text from widget if possible
        text = "Dragging..."
        if hasattr(source_widget, "node") and source_widget.node:
             text = source_widget.node.title
        elif hasattr(source_widget, "cget"):
            try:
                text = source_widget.cget("text")
            except:
                pass
        
        frame = ctk.CTkFrame(self.ghost_window, fg_color=Colors.PRIMARY, corner_radius=Dims.RADIUS_S)
        frame.pack(fill="both", expand=True)
        
        label = ctk.CTkLabel(frame, text=text, text_color="white", font=(Fonts.FAMILY, Fonts.SIZE_S))
        label.pack(padx=10, pady=5)
        
        # Force update to calculate size
        self.ghost_window.update_idletasks()
        
        # Make drag window ignore mouse events (click-through) is hard in pure Tkinter 
        # without platform specific hacks. 
        # Instead, we offset the window slightly so it's not DIRECTLY under cursor 
        # if we wanted to use winfo_containing, but since we use AABB check manually, 
        # it doesn't matter if ghost covers the target.

    def update_drag(self, event):
        """Updates ghost position and checks for drop targets."""
        if not self.dragging:
            return
        
        # 閾値を超えた場合にゴーストを作成
        if not self.drag_started:
            dx = abs(event.x_root - self.start_x)
            dy = abs(event.y_root - self.start_y)
            if dx > self.drag_threshold or dy > self.drag_threshold:
                self.drag_started = True
                self._create_ghost(self.source_widget)
                logger.debug(f"Drag started for {self.drag_data}")
            else:
                return
        
        if not self.ghost_window:
            return
            
        self._update_ghost_position(event.x_root, event.y_root)
        self._check_targets(event.x_root, event.y_root)

    def _update_ghost_position(self, x_root, y_root):
        # Move window
        # Place ghost exactly relative to the grab point
        new_x = x_root - self.offset_x
        new_y = y_root - self.offset_y
        self.ghost_window.geometry(f"+{new_x}+{new_y}")

    def _check_targets(self, x_root, y_root):
        """Hit test against registered targets."""
        found_target = None
        
        # Iterate targets to find overlap
        # Check in reverse order (topmost first usually) if relying on z-order, 
        # but here we just list check.
        for widget, data in self.drop_targets:
            if widget == self.source_widget:
                continue
            
            try:
                if not widget.winfo_exists() or not widget.winfo_viewable():
                    continue
                    
                wx = widget.winfo_rootx()
                wy = widget.winfo_rooty()
                ww = widget.winfo_width()
                wh = widget.winfo_height()
                
                if wx <= x_root <= wx + ww and wy <= y_root <= wy + wh:
                    found_target = widget
                    break
            except Exception:
                continue

        # Handle Highlight
        if found_target != self.current_highlight:
            # Unhighlight old
            if self.current_highlight:
                self._unhighlight(self.current_highlight)
            
            # Highlight new
            if found_target:
                self._highlight(found_target)
            
            self.current_highlight = found_target

    def _highlight(self, widget):
        """Apply highlight effect."""
        try:
            # Store original color to restore later if needed
            if not hasattr(widget, "_original_bg"):
                widget._original_bg = widget.cget("fg_color")
            
            # Apple-like drop highlight (Blue border or background)
            if hasattr(widget, "configure"):
                widget.configure(border_color=Colors.DROP_INDICATOR, border_width=2)
        except Exception as e:
            logger.debug(f"Highlight failed: {e}")

    def _unhighlight(self, widget):
        """Remove highlight effect."""
        try:
            # Restore
            if hasattr(widget, "configure"):
                 # Default border color for cards/rows
                 # Ideally we should read this from constants or store it
                 widget.configure(border_color=Colors.BORDER, border_width=1) # COLOR_BORDER assumption
        except Exception as e:
            logger.debug(f"Unhighlight failed: {e}")

    def _global_end_drag(self, event):
        """グローバルなButtonRelease-1ハンドラ（ドラッグ中の場合のみ処理）"""
        if self.dragging:
            self.end_drag(event)
    
    def end_drag(self, event):
        """Finishes the drag operation."""
        if not self.dragging:
            return
        
        was_dragging = self.drag_started
        self.dragging = False
        self.drag_started = False
        
        if self.ghost_window:
            self.ghost_window.destroy()
            self.ghost_window = None
            
        # ドラッグが実際に開始された場合のみドロップを処理
        if was_dragging and self.current_highlight:
            self._unhighlight(self.current_highlight)
            
            # Perform drop
            target_widget = self.current_highlight
            self.current_highlight = None
            
            if target_widget:
                # Find data for this widget
                target_data = next((d for w, d in self.drop_targets if w == target_widget), None)
                if self.on_drop and target_data:
                    self.on_drop(self.drag_data, target_data)
        elif self.current_highlight:
            self._unhighlight(self.current_highlight)
            self.current_highlight = None
        
        self.source_widget = None
        self.drag_data = None

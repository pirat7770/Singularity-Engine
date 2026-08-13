import tkinter as tk

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind('<Enter>', self.show_tip)
        widget.bind('<Leave>', self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify="left",
                         background="#ffffe0", foreground="#000000",
                         relief="solid", borderwidth=1, font=("Arial", 9))
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


def show_notification(root, title, message, theme, duration=5000):
    """Показывает всплывающее уведомление в правом нижнем углу."""
    try:
        notif = tk.Toplevel(root)
        notif.overrideredirect(True)
        notif.attributes("-topmost", True)

        # Цвета из темы
        bg = theme.get("menu_bg", "#2b2b2b")
        fg = theme.get("menu_fg", "#00cc66")
        highlight = theme.get("menu_highlight", "#008844")

        frame = tk.Frame(notif, bg=bg, highlightthickness=1, highlightbackground=highlight)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=title, bg=bg, fg=fg,
                 font=("Arial", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(frame, text=message, bg=bg, fg=fg,
                 font=("Arial", 9)).pack(anchor="w", padx=10, pady=(2, 8))

        # Позиционируем в правом нижнем углу
        notif.update_idletasks()
        w = notif.winfo_reqwidth()
        h = notif.winfo_reqheight()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = screen_w - w - 20
        y = screen_h - h - 40
        notif.geometry(f"+{x}+{y}")

        # Автоматическое закрытие
        notif.after(duration, notif.destroy)
    except Exception:
        pass
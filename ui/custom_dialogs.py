# ui/custom_dialogs.py
import tkinter as tk
import tkinter.messagebox as messagebox

_ROOT = None


def _get_theme():
    """Возвращает палитру текущей темы из главного окна."""
    if _ROOT is not None and hasattr(_ROOT, "THEMES") and hasattr(_ROOT, "settings"):
        theme_name = _ROOT.settings.get("theme", "Стандартная")
        return _ROOT.THEMES.get(theme_name, _ROOT.THEMES["Стандартная"])
    # Фолбэк, если root ещё не готов
    return {
        "bg": "#2b2b2b", "fg": "#d0ffd0",
        "menu_bg": "#2b2b2b", "menu_fg": "#00cc66", "menu_active_bg": "#4a4d50",
        "menu_active_fg": "#00ff88", "menu_highlight": "#008844",
        "btn_default_bg": "#4a4d50", "btn_default_fg": "#aaffaa",
        "btn_danger_bg": "#8a3a3a", "btn_danger_fg": "#ff8888",
        "btn_accent_bg": "#4a6d4a", "btn_accent_fg": "#66ff66",
        "tree_bg": "#1e1e1e", "tree_fg": "#c0ffc0",
        "tree_sel_bg": "#2d4a3a",
        "tree_heading_bg": "#2b2b2b", "tree_heading_fg": "#66ff66",
        "tree_frame_highlight": "#008844",
    }


class _CustomDialog:
    """Базовое кастомное модальное окно."""

    def __init__(self, parent, title, message, kind="info"):
        self.parent = parent if parent is not None else _ROOT
        self.kind = kind
        self.result = None

        t = _get_theme()
        self.t = t

        self.win = tk.Toplevel(self.parent)
        self.win.overrideredirect(True)
        self.win.configure(bg=t["bg"])
        self.win.grab_set()          # модальность
        self.win.focus_force()

        # Рамка окна
        outer = tk.Frame(self.win, bg=t["menu_highlight"], bd=2, relief="flat")
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        inner = tk.Frame(outer, bg=t["bg"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Заголовок
        title_bar = tk.Frame(inner, bg=t["menu_bg"], height=32)
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)
        tk.Label(title_bar, text=title, bg=t["menu_bg"], fg=t["menu_fg"],
                 font=("Arial", 10, "bold")).pack(side="left", padx=8, pady=4)

        # Кнопка закрытия (крестик) – для простоты тоже покажем, но можно не давать закрывать если только кнопки
        close_btn = tk.Label(title_bar, text="✕", bg=t["menu_bg"], fg=t["menu_fg"],
                             font=("Arial", 11, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=8)
        close_btn.bind("<Button-1>", lambda e: self._close_cancel())

        # Сообщение
        msg_frame = tk.Frame(inner, bg=t["bg"])
        msg_frame.pack(fill="both", expand=True, padx=16, pady=12)
        tk.Label(msg_frame, text=message, bg=t["bg"], fg=t["fg"],
                 justify="left", wraplength=400, font=("Arial", 10)).pack(anchor="w")

        # Кнопки
        btn_frame = tk.Frame(inner, bg=t["bg"])
        btn_frame.pack(pady=(0, 10))

        self._add_buttons(btn_frame)

        # Центрирование
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        if self.parent:
            px = self.parent.winfo_rootx()
            py = self.parent.winfo_rooty()
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 3
        else:
            x = (self.win.winfo_screenwidth() - w) // 2
            y = (self.win.winfo_screenheight() - h) // 3
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        # Ожидание закрытия
        self.win.wait_window()

    def _add_buttons(self, frame):
        if self.kind == "yesno":
            btn_yes = tk.Button(frame, text="Да", bg=self.t["btn_accent_bg"],
                                fg=self.t["btn_accent_fg"],
                                activebackground=self.t["menu_active_bg"],
                                activeforeground=self.t["menu_active_fg"],
                                command=lambda: self._close_result(True),
                                width=8, font=("Arial", 9))
            btn_yes.pack(side="left", padx=6)
            btn_no = tk.Button(frame, text="Нет", bg=self.t["btn_default_bg"],
                               fg=self.t["btn_default_fg"],
                               activebackground=self.t["menu_active_bg"],
                               activeforeground=self.t["menu_active_fg"],
                               command=lambda: self._close_result(False),
                               width=8, font=("Arial", 9))
            btn_no.pack(side="left", padx=6)
        elif self.kind == "yesnocancel":
            btn_yes = tk.Button(frame, text="Да", bg=self.t["btn_accent_bg"],
                                fg=self.t["btn_accent_fg"],
                                activebackground=self.t["menu_active_bg"],
                                activeforeground=self.t["menu_active_fg"],
                                command=lambda: self._close_result(True),
                                width=8, font=("Arial", 9))
            btn_yes.pack(side="left", padx=4)
            btn_no = tk.Button(frame, text="Нет", bg=self.t["btn_default_bg"],
                               fg=self.t["btn_default_fg"],
                               activebackground=self.t["menu_active_bg"],
                               activeforeground=self.t["menu_active_fg"],
                               command=lambda: self._close_result(False),
                               width=8, font=("Arial", 9))
            btn_no.pack(side="left", padx=4)
            btn_cancel = tk.Button(frame, text="Отмена", bg=self.t["btn_default_bg"],
                                   fg=self.t["btn_default_fg"],
                                   activebackground=self.t["menu_active_bg"],
                                   activeforeground=self.t["menu_active_fg"],
                                   command=lambda: self._close_result(None),
                                   width=8, font=("Arial", 9))
            btn_cancel.pack(side="left", padx=4)
        else:  # info/warning/error
            btn_ok = tk.Button(frame, text="ОК", bg=self.t["btn_accent_bg"],
                               fg=self.t["btn_accent_fg"],
                               activebackground=self.t["menu_active_bg"],
                               activeforeground=self.t["menu_active_fg"],
                               command=lambda: self._close_result(True),
                               width=10, font=("Arial", 9))
            btn_ok.pack()

    def _close_result(self, value):
        self.result = value
        self.win.destroy()

    def _close_cancel(self):
        self.result = None if self.kind == "yesnocancel" else False
        self.win.destroy()


def install_custom_messageboxes(root):
    """Заменяет стандартные messagebox на кастомные."""
    global _ROOT
    _ROOT = root

    def showinfo(title, message, **options):
        d = _CustomDialog(options.get("parent", root), title, message, "info")
        return d.result

    def showwarning(title, message, **options):
        d = _CustomDialog(options.get("parent", root), title, message, "warning")
        return d.result

    def showerror(title, message, **options):
        d = _CustomDialog(options.get("parent", root), title, message, "error")
        return d.result

    def askyesno(title, message, **options):
        d = _CustomDialog(options.get("parent", root), title, message, "yesno")
        return d.result

    def askyesnocancel(title, message, **options):
        d = _CustomDialog(options.get("parent", root), title, message, "yesnocancel")
        return d.result

    def askquestion(title, message, **options):
        # Для совместимости возвращаем 'yes'/'no'
        d = _CustomDialog(options.get("parent", root), title, message, "yesno")
        return "yes" if d.result else "no"

    messagebox.showinfo = showinfo
    messagebox.showwarning = showwarning
    messagebox.showerror = showerror
    messagebox.askyesno = askyesno
    messagebox.askyesnocancel = askyesnocancel
    messagebox.askquestion = askquestion
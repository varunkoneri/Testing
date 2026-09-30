#!/usr/bin/env python3
"""
Easy Browser - Python (tkinter) port of the original HTML app.

Features kept: login (password / phone OTP tabs, guest mode), welcome splash,
home screen (stats, search bar, voice search, quick access, recent sites),
persistent history, five colour themes, profile picture, software update check.

Optional packages:
    pip install pillow              # profile picture from gallery
    pip install SpeechRecognition pyaudio   # voice search
"""
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageDraw, ImageTk
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

try:
    import speech_recognition as sr
    HAVE_SR = True
except ImportError:
    HAVE_SR = False

APP_VERSION = "1.0.0"  # bump this and publish the file to "release" an update
# Raw URL of the published copy of this script (e.g. a GitHub raw link).
UPDATE_URL = ""

DATA_DIR = os.path.join(os.path.expanduser("~"), ".easy_browser")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

THEMES = {
    "blue":   {"bg": "#0a1a33", "accent": "#6496e6"},
    "purple": {"bg": "#1c0f33", "accent": "#a878e0"},
    "green":  {"bg": "#04140f", "accent": "#3cc896"},
    "red":    {"bg": "#22060c", "accent": "#e05a6e"},
    "gold":   {"bg": "#1a1206", "accent": "#e0b46e"},
}

TEXT = "#eef3fb"
MUTED = "#8fa0c2"
PANEL = "#101f3c"
PANEL2 = "#17294a"
FIELD_BG = "#1b2a47"
DARK_TXT = "#04150f"

SITE_SHORTCUTS = {
    "claude": "https://claude.ai", "chatgpt": "https://chat.openai.com",
    "whatsapp": "https://web.whatsapp.com", "youtube": "https://youtube.com",
    "google": "https://google.com", "wikipedia": "https://wikipedia.org",
    "facebook": "https://facebook.com", "instagram": "https://instagram.com",
    "twitter": "https://x.com", "x": "https://x.com",
    "github": "https://github.com", "amazon": "https://amazon.com",
    "netflix": "https://netflix.com", "spotify": "https://open.spotify.com",
    "gmail": "https://mail.google.com", "maps": "https://maps.google.com",
    "translate": "https://translate.google.com", "reddit": "https://reddit.com",
    "linkedin": "https://linkedin.com", "telegram": "https://web.telegram.org",
    "canva": "https://canva.com", "codepen": "https://codepen.io",
}

QUICK = [
    ("YouTube", "https://youtube.com", "youtube.com"),
    ("Google", "https://google.com", "google.com"),
    ("ChatGPT", "https://chat.openai.com", "chat.openai.com"),
    ("Wikipedia", "https://wikipedia.org", "wikipedia.org"),
]

DEFAULT_RECENT = ["github.com", "codepen.io", "canva.com", "claude.ai"]


# ----------------------------------------------------------------- storage
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def relative_time(ts):
    minutes = int(max(0, time.time() - ts) // 60)
    if minutes < 1:
        return "Just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return "Yesterday" if days == 1 else f"{days} days ago"


# ----------------------------------------------------------------- widgets
def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class PlaceholderEntry(tk.Entry):
    def __init__(self, parent, placeholder="", secret=False, **kw):
        super().__init__(parent, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT,
                         relief="flat", highlightthickness=1,
                         highlightbackground="#33415f", highlightcolor=MUTED,
                         font=("Segoe UI", 10), **kw)
        self.placeholder = placeholder
        self.secret = secret
        self.showing_placeholder = False
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._focus_out()

    def _focus_in(self, _e=None):
        if self.showing_placeholder:
            self.delete(0, "end")
            self.config(fg=TEXT, show="*" if self.secret else "")
            self.showing_placeholder = False

    def _focus_out(self, _e=None):
        if not super().get():
            self.showing_placeholder = True
            self.config(fg=MUTED, show="")
            self.insert(0, self.placeholder)

    def value(self):
        return "" if self.showing_placeholder else super().get()

    def set_secret_visible(self, visible):
        self.secret = not visible
        if not self.showing_placeholder:
            self.config(show="" if visible else "*")


class ScrollFrame(tk.Frame):
    """Vertically scrollable frame."""

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.canvas.pack(fill="both", expand=True)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="n")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(seq, self._wheel)

    def _resize(self, e):
        self.canvas.itemconfigure(self.win, width=min(e.width, 480))
        self.canvas.coords(self.win, e.width // 2, 0)

    def _wheel(self, e):
        try:
            if not self.canvas.winfo_exists():
                return
            if e.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif e.num == 5:
                self.canvas.yview_scroll(1, "units")
            else:
                self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")
        except tk.TclError:
            pass


# --------------------------------------------------------------------- app
class EasyBrowser(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Easy Browser")
        self.geometry("480x860")
        self.minsize(420, 640)

        settings = load_json(SETTINGS_FILE, {})
        self.theme_key = settings.get("theme", "blue")
        if self.theme_key not in THEMES:
            self.theme_key = "blue"
        self.user_name = ""
        self.avatar_img = None  # PIL image of profile picture
        self._avatar_tk = None
        self.last_screen = "login"
        self.history = load_json(HISTORY_FILE, [])
        self.pending_update = None

        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)
        self.show("login")

    # ------------------------------------------------------------ theme
    @property
    def bg(self):
        return THEMES[self.theme_key]["bg"]

    @property
    def accent(self):
        return THEMES[self.theme_key]["accent"]

    def set_theme(self, key):
        self.theme_key = key
        save_json(SETTINGS_FILE, {"theme": key})
        self.show("settings")

    # -------------------------------------------------------- navigation
    def show(self, name):
        for w in self.container.winfo_children():
            w.destroy()
        self.configure(bg=self.bg)
        self.container.configure(bg=self.bg)
        getattr(self, f"build_{name}")()
        self.current = name

    def open_settings(self, came_from):
        self.last_screen = came_from
        self.show("settings")

    # ----------------------------------------------------------- helpers
    def draw_logo(self, parent, size, bg=None):
        c = tk.Canvas(parent, width=size, height=size, bg=bg or self.bg,
                      highlightthickness=0)
        rounded_rect(c, 1, 1, size - 1, size - 1, size // 5, fill=self.accent, outline="")
        rounded_rect(c, size * .12, size * .12, size * .88, size * .88, size // 6,
                     fill=THEMES[self.theme_key]["bg"], outline="")
        c.create_text(size / 2, size / 2, text="E", fill=self.accent,
                      font=("Segoe UI", int(size * .42), "bold"))
        return c

    def brand(self, parent, size=84):
        box = tk.Frame(parent, bg=self.bg)
        box.pack(pady=(0, 18))
        self.draw_logo(box, size).pack(pady=(0, 8))
        tk.Label(box, text="Easy Browser", bg=self.bg, fg=TEXT,
                 font=("Segoe UI", 18, "bold")).pack()
        tk.Label(box, text="Fast · Smart · Secure", bg=self.bg, fg=MUTED,
                 font=("Segoe UI", 9)).pack()

    def button(self, parent, text, cmd, bg=None, fg=DARK_TXT, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=bg or self.accent, fg=fg,
                         activebackground=bg or self.accent, activeforeground=fg,
                         relief="flat", bd=0, cursor="hand2", pady=9,
                         font=("Segoe UI", 10, "bold"), **kw)

    def icon_button(self, parent, text, cmd, bg=None):
        return tk.Button(parent, text=text, command=cmd, bg="#1c2b47" if bg is None else bg,
                         fg=TEXT, activebackground="#26375a", activeforeground=TEXT,
                         relief="flat", bd=0, width=3, cursor="hand2",
                         font=("Segoe UI", 12))

    def label(self, parent, text, size=10, color=TEXT, bold=False, bg=None, **kw):
        return tk.Label(parent, text=text, bg=bg or self.bg, fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    # -------------------------------------------------------- history
    def log_history(self, site):
        self.history.insert(0, {"site": site, "time": time.time()})
        self.history = self.history[:200]
        save_json(HISTORY_FILE, self.history)

    def open_url(self, url, log_as):
        self.log_history(log_as)
        webbrowser.open(url)

    # ---------------------------------------------------------- LOGIN
    def build_login(self):
        top = tk.Frame(self.container, bg=self.bg)
        top.pack(fill="x", padx=16, pady=(10, 0))
        self.icon_button(top, "⚙", lambda: self.open_settings("login")).pack(side="right")

        sf = ScrollFrame(self.container, self.bg)
        sf.pack(fill="both", expand=True)
        f = sf.inner
        wrap = tk.Frame(f, bg=self.bg)
        wrap.pack(fill="x", padx=20, pady=10)
        self.brand(wrap)

        card = tk.Frame(wrap, bg=PANEL, padx=24, pady=22)
        card.pack(fill="x")
        self.label(card, "Welcome back", 14, bold=True, bg=PANEL).pack()
        self.label(card, "Log in to continue to Easy Browser", 9, MUTED, bg=PANEL).pack(pady=(2, 16))

        tabs = tk.Frame(card, bg=PANEL2, padx=4, pady=4)
        tabs.pack(fill="x", pady=(0, 16))
        tab_pw = tk.Label(tabs, text="Password", pady=6, font=("Segoe UI", 10, "bold"), cursor="hand2")
        tab_otp = tk.Label(tabs, text="Phone OTP", pady=6, font=("Segoe UI", 10, "bold"), cursor="hand2")
        tab_pw.pack(side="left", expand=True, fill="x")
        tab_otp.pack(side="left", expand=True, fill="x")

        pane_pw = tk.Frame(card, bg=PANEL)
        pane_otp = tk.Frame(card, bg=PANEL)

        def switch(which):
            pane_pw.pack_forget()
            pane_otp.pack_forget()
            for t, active in ((tab_pw, which == "pw"), (tab_otp, which == "otp")):
                t.config(bg=self.accent if active else PANEL2,
                         fg=DARK_TXT if active else MUTED)
            (pane_pw if which == "pw" else pane_otp).pack(fill="x")

        tab_pw.bind("<Button-1>", lambda e: switch("pw"))
        tab_otp.bind("<Button-1>", lambda e: switch("otp"))

        # password pane
        self.label(pane_pw, "Full name or email", 9, MUTED, bg=PANEL, anchor="w").pack(fill="x")
        name_in = PlaceholderEntry(pane_pw, "Enter your username")
        name_in.pack(fill="x", ipady=7, pady=(4, 12))
        self.label(pane_pw, "Password", 9, MUTED, bg=PANEL, anchor="w").pack(fill="x")
        pw_row = tk.Frame(pane_pw, bg=PANEL)
        pw_row.pack(fill="x", pady=(4, 12))
        pw_in = PlaceholderEntry(pw_row, "Enter your passcode", secret=True)
        pw_in.pack(side="left", fill="x", expand=True, ipady=7)
        shown = {"v": False}

        def toggle_eye():
            shown["v"] = not shown["v"]
            pw_in.set_secret_visible(shown["v"])
            eye.config(text="🙈" if shown["v"] else "👁")

        eye = tk.Button(pw_row, text="👁", command=toggle_eye, bg=PANEL, fg=MUTED,
                        relief="flat", bd=0, cursor="hand2", activebackground=PANEL)
        eye.pack(side="left", padx=(6, 0))

        row = tk.Frame(pane_pw, bg=PANEL)
        row.pack(fill="x", pady=(0, 14))
        tk.Checkbutton(row, text="Remember me", bg=PANEL, fg=MUTED, selectcolor=PANEL2,
                       activebackground=PANEL, activeforeground=MUTED,
                       font=("Segoe UI", 9)).pack(side="left")
        forgot = tk.Label(row, text="Forgot password?", bg=PANEL, fg=self.accent,
                          font=("Segoe UI", 9, "bold"), cursor="hand2")
        forgot.pack(side="right")
        forgot.bind("<Button-1>", lambda e: messagebox.showinfo(
            "Easy Browser", "Password reset isn't available in this version."))

        def do_login():
            n, p = name_in.value(), pw_in.value()
            self.log_in_as(n if (n or p) else "")

        self.button(pane_pw, "Log in", do_login).pack(fill="x", pady=(0, 6))

        # OTP pane
        self.label(pane_otp, "Full name", 9, MUTED, bg=PANEL, anchor="w").pack(fill="x")
        name_otp = PlaceholderEntry(pane_otp, "Enter your username")
        name_otp.pack(fill="x", ipady=7, pady=(4, 12))
        self.label(pane_otp, "Phone number", 9, MUTED, bg=PANEL, anchor="w").pack(fill="x")
        PlaceholderEntry(pane_otp, "+91 00000 00000").pack(fill="x", ipady=7, pady=(4, 12))
        self.button(pane_otp, "Send OTP", lambda: messagebox.showinfo(
            "Easy Browser", "Sending OTPs isn't implemented in this demo.")).pack(fill="x", pady=(0, 12))
        self.label(pane_otp, "Enter OTP", 9, MUTED, bg=PANEL, anchor="w").pack(fill="x")
        PlaceholderEntry(pane_otp, "• • • • • •").pack(fill="x", ipady=7, pady=(4, 12))
        self.button(pane_otp, "Verify & log in",
                    lambda: self.log_in_as(name_otp.value())).pack(fill="x", pady=(0, 6))

        switch("pw")

        div = tk.Frame(card, bg=PANEL)
        div.pack(fill="x", pady=10)
        tk.Frame(div, bg="#33415f", height=1).pack(side="left", fill="x", expand=True)
        self.label(div, "  or continue with  ", 8, MUTED, bg=PANEL).pack(side="left")
        tk.Frame(div, bg="#33415f", height=1).pack(side="left", fill="x", expand=True)

        su = tk.Frame(card, bg=PANEL)
        su.pack()
        self.label(su, "Don't have an account? ", 9, MUTED, bg=PANEL).pack(side="left")
        l = tk.Label(su, text="Sign up", bg=PANEL, fg=self.accent, cursor="hand2",
                     font=("Segoe UI", 9, "bold"))
        l.pack(side="left")
        l.bind("<Button-1>", lambda e: messagebox.showinfo(
            "Easy Browser", "Sign-up isn't available in this version."))

        feats = tk.Frame(card, bg=PANEL)
        feats.pack(fill="x", pady=(18, 0))
        for icon, text in (("⚡", "Lightning fast"), ("🛡", "Super secure"),
                           ("☁", "Cloud sync"), ("🔖", "Bookmarks & more")):
            col = tk.Frame(feats, bg=PANEL)
            col.pack(side="left", expand=True)
            tk.Label(col, text=icon, bg=PANEL2, fg=self.accent, width=3,
                     font=("Segoe UI", 12)).pack()
            self.label(col, text, 7, MUTED, bg=PANEL).pack(pady=(4, 0))

    def log_in_as(self, name):
        self.user_name = (name or "").strip()
        self.show("splash")

    # --------------------------------------------------------- SPLASH
    def build_splash(self):
        box = tk.Frame(self.container, bg=self.bg)
        box.place(relx=.5, rely=.45, anchor="center")
        self.draw_logo(box, 96).pack(pady=(0, 16))
        msg = (f"Hi {self.user_name}, Easy Browser welcomes you!" if self.user_name
               else "Hi Guest, Easy Browser welcomes you!")
        self.label(box, msg, 12, bold=True).pack()
        self.after(3000, lambda: self.show("home") if self.current == "splash" else None)

    # ----------------------------------------------------------- HOME
    def build_home(self):
        sf = ScrollFrame(self.container, self.bg)
        sf.pack(fill="both", expand=True)
        f = tk.Frame(sf.inner, bg=self.bg)
        f.pack(fill="x", padx=20, pady=16)

        # top bar
        bar = tk.Frame(f, bg=self.bg)
        bar.pack(fill="x", pady=(0, 16))
        self.icon_button(bar, "⚙", lambda: self.open_settings("home")).pack(side="left")
        pill = tk.Frame(bar, bg="#1c2b47", padx=8, pady=5)
        pill.pack(side="right")
        self.avatar_canvas = tk.Canvas(pill, width=28, height=28, bg="#1c2b47",
                                       highlightthickness=0, cursor="hand2")
        self.avatar_canvas.pack(side="left")
        self.avatar_canvas.bind("<Button-1>", lambda e: self.pick_avatar())
        self.draw_avatar()
        self.label(pill, self.user_name or "Guest", 9, bg="#1c2b47").pack(side="left", padx=8)
        out = tk.Label(pill, text="Log out", bg="#1c2b47", fg=MUTED, cursor="hand2",
                       font=("Segoe UI", 9))
        out.pack(side="left")
        out.bind("<Button-1>", lambda e: self.logout())

        self.brand(f)

        # stats
        stats = tk.Frame(f, bg=self.bg)
        stats.pack(pady=10)
        for label, num, sub in (("WEBSITES", "150+", "Available"), ("BOOKMARKS", "24", "Saved"),
                                ("HISTORY", str(len(self.history)), "Visited")):
            s = tk.Frame(stats, bg=self.bg)
            s.pack(side="left", padx=18)
            self.label(s, label, 7, MUTED, bold=True).pack()
            self.label(s, num, 16, bold=True).pack()
            self.label(s, sub, 8, MUTED).pack()

        # search
        sbox = tk.Frame(f, bg=FIELD_BG, highlightthickness=1, highlightbackground="#33415f")
        sbox.pack(fill="x", pady=14)
        tk.Label(sbox, text="🔍", bg=FIELD_BG, fg=MUTED).pack(side="left", padx=(12, 4))
        self.search_var = tk.StringVar()
        entry = tk.Entry(sbox, textvariable=self.search_var, bg=FIELD_BG, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, ipady=9)
        entry.bind("<Return>", lambda e: self.do_search())
        self.mic_btn = tk.Button(sbox, text="🎤", command=self.voice_search, bg=FIELD_BG,
                                 fg=MUTED, relief="flat", bd=0, cursor="hand2",
                                 activebackground=FIELD_BG)
        self.mic_btn.pack(side="right", padx=8)
        tk.Label(sbox, text="Search or enter website", bg=FIELD_BG, fg=MUTED,
                 font=("Segoe UI", 9)).place_forget()
        entry.focus_set()

        # quick access
        self.section_head(f, "Quick Access", "View All ›", lambda: None)
        grid = tk.Frame(f, bg=self.bg)
        grid.pack(fill="x")
        for i, (name, href, domain) in enumerate(QUICK):
            grid.columnconfigure(i, weight=1)
            cell = tk.Frame(grid, bg=self.bg, cursor="hand2")
            cell.grid(row=0, column=i, padx=4)
            badge = tk.Label(cell, text=name[0], bg=PANEL2, fg=self.accent, width=3, height=1,
                             font=("Segoe UI", 16, "bold"))
            badge.pack()
            cap = self.label(cell, name, 8)
            cap.pack(pady=(4, 0))
            for w in (cell, badge, cap):
                w.bind("<Button-1>", lambda e, h=href, d=domain: self.open_url(h, d))

        # banner
        ban = tk.Frame(f, bg=self.accent, padx=16, pady=14)
        ban.pack(fill="x", pady=18)
        txt = tk.Frame(ban, bg=self.accent)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text="Explore the web faster and smarter", bg=self.accent, fg=DARK_TXT,
                 font=("Segoe UI", 10, "bold"), anchor="w", wraplength=240,
                 justify="left").pack(anchor="w")
        tk.Label(txt, text="Your all-in-one browser for everything you need.", bg=self.accent,
                 fg=DARK_TXT, font=("Segoe UI", 8), anchor="w", wraplength=240,
                 justify="left").pack(anchor="w")
        tk.Button(ban, text="Explore ›", bg="white", fg="#0a1a33", relief="flat", bd=0,
                  padx=12, pady=5, cursor="hand2", font=("Segoe UI", 9, "bold"),
                  command=lambda: self.open_url("https://google.com", "google.com")
                  ).pack(side="right")

        # recent websites
        self.section_head(f, "Recent Websites", "Clear All", self.clear_history)
        recent = []
        for h in self.history:
            s = h["site"]
            if not s.startswith("Search:") and s not in recent:
                recent.append(s)
            if len(recent) == 4:
                break
        for d in DEFAULT_RECENT:
            if len(recent) < 4 and d not in recent:
                recent.append(d)
        chips = tk.Frame(f, bg=self.bg)
        chips.pack(fill="x")
        for site in recent:
            c = tk.Label(chips, text=site, bg=PANEL2, fg=TEXT, padx=10, pady=5,
                         font=("Segoe UI", 8), cursor="hand2")
            c.pack(side="left", padx=(0, 6))
            c.bind("<Button-1>", lambda e, s=site: self.open_url("https://" + s, s))

        # bottom nav
        nav = tk.Frame(f, bg=self.bg, highlightthickness=0)
        nav.pack(fill="x", pady=(28, 0))
        tk.Frame(nav, bg="#22314f", height=1).pack(fill="x", pady=(0, 10))
        row = tk.Frame(nav, bg=self.bg)
        row.pack(fill="x")

        def nav_item(text, cmd, active=False):
            b = tk.Button(row, text=text, command=cmd, bg=self.bg,
                          fg=self.accent if active else MUTED, relief="flat", bd=0,
                          activebackground=self.bg, cursor="hand2", font=("Segoe UI", 9))
            b.pack(side="left", expand=True)

        soon = lambda: messagebox.showinfo("Easy Browser", "Coming soon.")
        nav_item("🏠 Home", lambda: None, True)
        nav_item("🔖 Bookmarks", soon)
        self.draw_logo(row, 44).pack(side="left", expand=True)
        nav_item("🕘 History", lambda: self.open_history("home"))
        nav_item("▦ Apps", soon)

    def section_head(self, parent, title, action, cmd):
        row = tk.Frame(parent, bg=self.bg)
        row.pack(fill="x", pady=(16, 10))
        self.label(row, title, 11, bold=True).pack(side="left")
        a = tk.Label(row, text=action, bg=self.bg, fg=self.accent, cursor="hand2",
                     font=("Segoe UI", 9, "bold"))
        a.pack(side="right")
        a.bind("<Button-1>", lambda e: cmd())

    def draw_avatar(self):
        c = self.avatar_canvas
        c.delete("all")
        if self.avatar_img is not None and HAVE_PIL:
            img = self.avatar_img.resize((28, 28))
            mask = Image.new("L", (28, 28), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 27, 27), fill=255)
            img.putalpha(mask)
            self._avatar_tk = ImageTk.PhotoImage(img)
            c.create_image(14, 14, image=self._avatar_tk)
        else:
            c.create_oval(1, 1, 27, 27, fill=self.accent, outline="")
            c.create_text(14, 14, text=(self.user_name[:1].upper() or "G"),
                          fill=DARK_TXT, font=("Segoe UI", 10, "bold"))

    def pick_avatar(self):
        if not HAVE_PIL:
            messagebox.showinfo("Easy Browser", "Install Pillow to set a profile picture:\n\npip install pillow")
            return
        path = filedialog.askopenfilename(
            title="Choose a profile picture",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp")])
        if path:
            try:
                self.avatar_img = Image.open(path).convert("RGBA")
                self.draw_avatar()
            except Exception as exc:
                messagebox.showerror("Easy Browser", f"Couldn't open that image.\n{exc}")

    def logout(self):
        self.user_name = ""
        self.avatar_img = None
        self.show("login")

    def clear_history(self):
        if messagebox.askyesno("Easy Browser", "Clear all history?"):
            self.history = []
            save_json(HISTORY_FILE, self.history)
            self.show("home")

    # --------------------------------------------------------- search
    def do_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        key = q.lower()
        if key in SITE_SHORTCUTS:
            url = SITE_SHORTCUTS[key]
            log = urllib.parse.urlparse(url).netloc.replace("www.", "")
        else:
            looks_like_url = bool(re.match(r"^[\w-]+(\.[\w-]+)+([/?#].*)?$", q)
                                  or re.match(r"^https?://", q))
            if looks_like_url:
                url = q if re.match(r"^https?://", q) else f"https://{q}"
                log = re.sub(r"^https?://", "", q)
            else:
                url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)
                log = f"Search: {q}"
        self.open_url(url, log)
        self.search_var.set("")

    def voice_search(self):
        if not HAVE_SR:
            messagebox.showinfo(
                "Easy Browser",
                "Voice search needs extra packages:\n\npip install SpeechRecognition pyaudio")
            return
        self.mic_btn.config(fg=self.accent)

        def listen():
            text, err = None, None
            try:
                rec = sr.Recognizer()
                with sr.Microphone() as source:
                    audio = rec.listen(source, timeout=6, phrase_time_limit=8)
                text = rec.recognize_google(audio, language="en-US")
            except Exception as exc:
                err = exc
            self.after(0, lambda: self._voice_done(text, err))

        threading.Thread(target=listen, daemon=True).start()

    def _voice_done(self, text, err):
        try:
            self.mic_btn.config(fg=MUTED)
        except tk.TclError:
            return
        if text:
            self.search_var.set(text)
            self.do_search()
        elif err is not None:
            messagebox.showinfo("Easy Browser", "Couldn't understand that. Please try again.")

    # -------------------------------------------------------- HISTORY
    def open_history(self, came_from):
        self.last_screen = came_from
        self.show("history")

    def build_history(self):
        head = tk.Frame(self.container, bg=self.bg)
        head.pack(fill="x", padx=20, pady=(16, 10))
        self.icon_button(head, "‹", lambda: self.show(self.last_screen)).pack(side="left")
        self.label(head, "  History", 14, bold=True).pack(side="left")

        sf = ScrollFrame(self.container, self.bg)
        sf.pack(fill="both", expand=True)
        body = tk.Frame(sf.inner, bg=self.bg)
        body.pack(fill="x", padx=20, pady=6)
        if not self.history:
            self.label(body, "Nothing searched yet — sites you visit from the search bar "
                       "or Quick Access will show up here.", 9, MUTED,
                       wraplength=400, justify="left").pack(anchor="w")
            return
        for h in self.history:
            row = tk.Frame(body, bg=PANEL2, padx=14, pady=10, cursor="hand2")
            row.pack(fill="x", pady=4)
            site = h["site"]
            l1 = tk.Label(row, text=site, bg=PANEL2, fg=TEXT, font=("Segoe UI", 10, "bold"))
            l2 = tk.Label(row, text=relative_time(h["time"]), bg=PANEL2, fg=MUTED,
                          font=("Segoe UI", 8))
            l1.pack(side="left")
            l2.pack(side="right")
            if site.startswith("Search:"):
                url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(site[7:].strip())
            else:
                url = site if site.startswith("http") else "https://" + site
            for w in (row, l1, l2):
                w.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

    # ------------------------------------------------------- SETTINGS
    def build_settings(self):
        head = tk.Frame(self.container, bg=self.bg)
        head.pack(fill="x", padx=20, pady=(16, 10))
        self.icon_button(head, "‹", lambda: self.show(self.last_screen)).pack(side="left")
        self.label(head, "  Settings", 14, bold=True).pack(side="left")

        body = tk.Frame(self.container, bg=self.bg)
        body.pack(fill="x", padx=20, pady=10)

        self.label(body, "APPEARANCE", 8, MUTED, bold=True).pack(anchor="w", pady=(0, 10))
        row = tk.Frame(body, bg=self.bg)
        row.pack(anchor="w")
        for key, t in THEMES.items():
            col = tk.Frame(row, bg=self.bg, cursor="hand2")
            col.pack(side="left", padx=(0, 12))
            sw = tk.Canvas(col, width=54, height=54, bg=self.bg, highlightthickness=0)
            rounded_rect(sw, 2, 2, 52, 52, 12, fill=t["bg"],
                         outline="white" if key == self.theme_key else t["accent"],
                         width=2)
            sw.create_oval(17, 17, 37, 37, fill=t["accent"], outline="")
            sw.pack()
            cap = self.label(col, key.capitalize(), 8, MUTED)
            cap.pack(pady=(4, 0))
            for w in (col, sw, cap):
                w.bind("<Button-1>", lambda e, k=key: self.set_theme(k))

        self.label(body, "SOFTWARE UPDATE", 8, MUTED, bold=True).pack(anchor="w", pady=(26, 10))
        card = tk.Frame(body, bg=PANEL2, padx=16, pady=16)
        card.pack(fill="x")
        r = tk.Frame(card, bg=PANEL2)
        r.pack(fill="x")
        self.label(r, "Easy Browser version", 10, bg=PANEL2).pack(side="left")
        self.label(r, APP_VERSION, 10, self.accent, bold=True, bg=PANEL2).pack(side="right")

        self.update_status = tk.Label(card, text="", bg=PANEL2, fg=MUTED, wraplength=380,
                                      justify="left", font=("Segoe UI", 9))
        self.install_btn = self.button(card, "Download & Restart", self.install_update)
        self.button(card, "Check for Updates", self.check_update).pack(fill="x", pady=(12, 0))
        self.update_status.pack(anchor="w", pady=(10, 0))
        self.label(card, "Updates are published by replacing the script at UPDATE_URL — only "
                   "whoever controls that location can release one.", 8, MUTED, bg=PANEL2,
                   wraplength=380, justify="left").pack(anchor="w", pady=(12, 0))

    def check_update(self):
        self.install_btn.pack_forget()
        if not UPDATE_URL:
            self.update_status.config(text="No update URL configured (set UPDATE_URL in the script).")
            return
        self.update_status.config(text="Checking for updates…")

        def work():
            try:
                req = urllib.request.Request(UPDATE_URL + ("&" if "?" in UPDATE_URL else "?")
                                             + f"_={int(time.time())}",
                                             headers={"Cache-Control": "no-cache"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    text = resp.read().decode("utf-8")
                m = re.search(r"APP_VERSION\s*=\s*['\"]([\d.]+)['\"]", text)
                self.after(0, lambda: self._update_result(m.group(1) if m else None, text))
            except Exception:
                self.after(0, lambda: self.update_status.config(
                    text="Couldn't check for updates — check your connection."))

        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, latest, source):
        if latest is None:
            self.update_status.config(text="Couldn't read the live version.")
        elif latest == APP_VERSION:
            self.update_status.config(text="You're up to date.")
        else:
            self.pending_update = source
            self.update_status.config(text=f"Update available: version {latest}")
            self.install_btn.pack(fill="x", pady=(10, 0))

    def install_update(self):
        if not self.pending_update:
            return
        path = os.path.abspath(sys.argv[0])
        if not messagebox.askyesno("Easy Browser",
                                   "Replace this script with the new version and restart?\n"
                                   "A backup (.bak) will be kept."):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                old = f.read()
            with open(path + ".bak", "w", encoding="utf-8") as f:
                f.write(old)
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.pending_update)
        except OSError as exc:
            messagebox.showerror("Easy Browser", f"Couldn't write the update.\n{exc}")
            return
        os.execv(sys.executable, [sys.executable, path])


if __name__ == "__main__":
    EasyBrowser().mainloop()

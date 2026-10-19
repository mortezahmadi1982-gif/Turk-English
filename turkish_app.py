import asyncio
import os
import ssl
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import certifi
import edge_tts

EDGE_VOICES = {
    "Türkçe": ["tr-TR-EmelNeural", "tr-TR-AhmetNeural"],
    "English": ["en-US-GuyNeural", "en-US-JennyNeural"],
}
MAC_SAY_VOICES = {
    "Türkçe": "Yelda",
    "English": "Samantha",
}

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def source_lang_code(lang):
    return "tr" if "Türkçe" in (lang or "") or lang == "tr" else "en"


def _http_get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8"))


def _split_for_translate(text, max_len=1800):
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        piece = remaining[:max_len]
        cut = max(piece.rfind("\n"), piece.rfind(". "), piece.rfind("! "), piece.rfind("? "), piece.rfind(" "))
        if cut < 200:
            cut = max_len
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return [c for c in chunks if c]


def translate_to_persian(text, src_lang="tr"):
    text = (text or "").strip()
    if not text:
        return ""

    lang_code = "tr" if "tr" in src_lang else "en"
    parts = []
    last_error = None

    for chunk in _split_for_translate(text):
        encoded = urllib.parse.quote(chunk)
        try:
            url = (
                "https://translate.googleapis.com/translate_a/single"
                f"?client=gtx&sl={lang_code}&tl=fa&dt=t&q={encoded}"
            )
            data = _http_get_json(url)
            translated = "".join(item[0] for item in data[0] if item and item[0])
            parts.append(translated)
            continue
        except Exception as exc:
            last_error = exc

        try:
            url = (
                "https://api.mymemory.translated.net/get"
                f"?q={encoded}&langpair={lang_code}|fa"
            )
            data = _http_get_json(url)
            translated = (data.get("responseData") or {}).get("translatedText") or ""
            if translated:
                parts.append(translated)
                continue
            last_error = RuntimeError(str(data))
        except Exception as exc:
            last_error = exc

    if parts:
        return "\n".join(parts).strip()
    raise RuntimeError(f"ترجمه انجام نشد: {last_error}")


class PerfectInteractiveApp:
    def __init__(self, root):
        self.root = root
        self.root.title("آموزش پیشرفته زبان - طبیعی، ترجمه آنی و ذخیره استاندارد صدا")
        self._translate_job = None
        self._last_full_source = None
        self._word_meanings = {}
        self._splits_applied = False

        try:
            self.root.state("zoomed")
        except Exception:
            self.root.attributes("-fullscreen", True)

        self.root.configure(bg="#F4F6F9")
        self.root.bind("<Escape>", lambda event: self.root.attributes("-fullscreen", False))

        top_frame = tk.Frame(root, bg="#F4F6F9")
        top_frame.pack(fill="x", padx=25, pady=(15, 10))

        tk.Label(top_frame, text="🌐 زبان متن:", font=("Tahoma", 13, "bold"), bg="#F4F6F9", fg="#2C3E50").pack(side="left", padx=(0, 10))

        self.lang_var = tk.StringVar(value="Türkçe (ترکی)")
        self.lang_combo = ttk.Combobox(
            top_frame,
            textvariable=self.lang_var,
            values=["Türkçe (ترکی)", "English (انگلیسی)"],
            state="readonly",
            font=("Tahoma", 12),
            width=18,
        )
        self.lang_combo.pack(side="left", padx=(0, 20))
        self.lang_combo.bind("<<ComboboxSelected>>", lambda e: self.schedule_full_translate())

        tk.Label(top_frame, text="⏱ سرعت کل متن:", font=("Tahoma", 11, "bold"), bg="#F4F6F9").pack(side="left", padx=(10, 5))
        self.speed_scale = tk.Scale(top_frame, from_=-50, to=20, orient="horizontal", length=180, bg="#F4F6F9", highlightthickness=0)
        self.speed_scale.set(-25)
        self.speed_scale.pack(side="left")

        btn_save = tk.Button(top_frame, text="💾 ذخیره صوت استاندارد", bg="#2980B9", fg="white", font=("Tahoma", 11, "bold"), command=self.save_audio_file)
        btn_save.pack(side="right", padx=5)

        btn_play_all = tk.Button(top_frame, text="🔊 پخش کل متن", bg="#27AE60", fg="white", font=("Tahoma", 11, "bold"), command=self.generate_and_play_all)
        btn_play_all.pack(side="right", padx=5)

        btn_translate = tk.Button(top_frame, text="🌍 ترجمه کل متن", bg="#8E44AD", fg="white", font=("Tahoma", 11, "bold"), command=self.translate_full_text)
        btn_translate.pack(side="right", padx=5)

        self.main_paned = tk.PanedWindow(root, orient="horizontal", sashwidth=8, bg="#D5D8DC")
        self.main_paned.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        left_wrap = tk.Frame(self.main_paned, bg="#F4F6F9")
        self.left_paned = tk.PanedWindow(left_wrap, orient="vertical", sashwidth=8, bg="#D5D8DC")
        self.left_paned.pack(fill="both", expand=True)

        source_wrap = tk.Frame(self.left_paned, bg="#F4F6F9")
        tk.Label(source_wrap, text="📖 متن اصلی (روی هر کلمه کلیک کنید):", font=("Tahoma", 13, "bold"), bg="#F4F6F9", fg="#2C3E50").pack(anchor="w", pady=(0, 5))
        text_container = tk.Frame(source_wrap)
        text_container.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(text_container)
        scrollbar.pack(side="right", fill="y")
        self.txt_main = tk.Text(
            text_container,
            font=("Calibri", 20),
            wrap="word",
            bg="#FFFFFF",
            fg="#1B2631",
            relief="groove",
            bd=2,
            yscrollcommand=scrollbar.set,
        )
        self.txt_main.pack(fill="both", expand=True)
        scrollbar.config(command=self.txt_main.yview)
        self.left_paned.add(source_wrap, minsize=140)

        trans_wrap = tk.Frame(self.left_paned, bg="#F4F6F9")
        tk.Label(trans_wrap, text="🇮🇷 معنی کل متن به فارسی:", font=("Tahoma", 13, "bold"), bg="#F4F6F9", fg="#2C3E50").pack(anchor="w", pady=(6, 5))
        trans_container = tk.Frame(trans_wrap)
        trans_container.pack(fill="both", expand=True)
        trans_scroll = tk.Scrollbar(trans_container)
        trans_scroll.pack(side="right", fill="y")
        self.txt_translation = tk.Text(
            trans_container,
            font=("Tahoma", 15),
            wrap="word",
            bg="#FBFCFC",
            fg="#1A5276",
            relief="groove",
            bd=2,
            yscrollcommand=trans_scroll.set,
        )
        self.txt_translation.pack(fill="both", expand=True)
        trans_scroll.config(command=self.txt_translation.yview)
        self.txt_translation.insert("1.0", "معنی فارسی کل متن اینجا نمایش داده می‌شود.")
        self.left_paned.add(trans_wrap, minsize=120)

        self.main_paned.add(left_wrap, minsize=420)

        vocab_wrap = tk.Frame(self.main_paned, bg="#FDEDEC", bd=1, relief="groove")
        vocab_header = tk.Frame(vocab_wrap, bg="#FDEDEC")
        vocab_header.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(vocab_header, text="📚 معنی واژه‌ها", font=("Tahoma", 14, "bold"), bg="#FDEDEC", fg="#7B241C").pack(side="left")
        tk.Button(vocab_header, text="پاک کردن", font=("Tahoma", 10), command=self.clear_vocab).pack(side="right")

        self.lbl_word = tk.Label(vocab_wrap, text="روی یک کلمه کلیک کنید", font=("Tahoma", 13, "bold"), bg="#FDEDEC", fg="#C0392B", wraplength=280, justify="right", anchor="e")
        self.lbl_word.pack(fill="x", padx=12, pady=(2, 2))
        self.lbl_meaning = tk.Label(vocab_wrap, text="", font=("Tahoma", 13), bg="#FDEDEC", fg="#1A5276", wraplength=280, justify="right", anchor="e")
        self.lbl_meaning.pack(fill="x", padx=12, pady=(0, 8))

        vocab_container = tk.Frame(vocab_wrap)
        vocab_container.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        vocab_scroll = tk.Scrollbar(vocab_container)
        vocab_scroll.pack(side="right", fill="y")
        self.txt_vocab = tk.Text(
            vocab_container,
            font=("Tahoma", 13),
            wrap="word",
            bg="#FFFFFF",
            fg="#1B2631",
            relief="groove",
            bd=2,
            yscrollcommand=vocab_scroll.set,
        )
        self.txt_vocab.pack(fill="both", expand=True)
        vocab_scroll.config(command=self.txt_vocab.yview)
        self.txt_vocab.tag_configure("word", font=("Tahoma", 13, "bold"), foreground="#922B21")
        self.txt_vocab.tag_configure("meaning", foreground="#1A5276")
        self.txt_vocab.tag_configure("current", background="#F9E79F")
        self.txt_vocab.insert("1.0", "معنی هر کلمه‌ای که کلیک کنید اینجا جمع می‌شود.")
        self.txt_vocab.config(state="disabled")
        self.main_paned.add(vocab_wrap, minsize=240)

        self.txt_main.bind("<KeyRelease>", self.on_source_changed)
        self.txt_main.bind("<<Paste>>", self.on_source_changed)
        self.txt_main.bind("<ButtonRelease-1>", self.make_words_interactive)
        self.root.after(250, self._apply_splits)

    def _lang_key(self, lang):
        return "Türkçe" if "Türkçe" in lang else "English"

    def _apply_splits(self):
        if self._splits_applied:
            return
        self.root.update_idletasks()
        width = self.main_paned.winfo_width()
        height = self.left_paned.winfo_height()
        if width < 200 or height < 120:
            self.root.after(200, self._apply_splits)
            return
        self.main_paned.sash_place(0, int(width * 2 / 3), 0)
        self.left_paned.sash_place(0, 0, int(height / 2))
        self._splits_applied = True

    def clear_vocab(self):
        self._word_meanings.clear()
        self.lbl_word.config(text="روی یک کلمه کلیک کنید")
        self.lbl_meaning.config(text="")
        self.txt_vocab.config(state="normal")
        self.txt_vocab.delete("1.0", tk.END)
        self.txt_vocab.insert("1.0", "معنی هر کلمه‌ای که کلیک کنید اینجا جمع می‌شود.")
        self.txt_vocab.config(state="disabled")

    def add_vocab_entry(self, word, meaning):
        self._word_meanings[word] = meaning
        self.lbl_word.config(text=word)
        self.lbl_meaning.config(text=meaning)
        self.txt_vocab.config(state="normal")
        self.txt_vocab.delete("1.0", tk.END)
        for item, item_meaning in reversed(list(self._word_meanings.items())):
            start = self.txt_vocab.index("end-1c")
            self.txt_vocab.insert("end", f"{item}\n")
            self.txt_vocab.tag_add("word", start, "end-1c")
            if item == word:
                self.txt_vocab.tag_add("current", start, "end-1c")
            mean_start = self.txt_vocab.index("end-1c")
            self.txt_vocab.insert("end", f"{item_meaning}\n\n")
            self.txt_vocab.tag_add("meaning", mean_start, "end-1c")
        self.txt_vocab.see("1.0")
        self.txt_vocab.config(state="disabled")

    def on_source_changed(self, event=None):
        self.make_words_interactive()
        self.schedule_full_translate()

    def schedule_full_translate(self, event=None):
        if self._translate_job:
            self.root.after_cancel(self._translate_job)
        self._translate_job = self.root.after(900, self.translate_full_text)

    def set_translation_text(self, text):
        self.txt_translation.delete("1.0", tk.END)
        self.txt_translation.insert("1.0", text)

    def translate_full_text(self):
        text = self.txt_main.get("1.0", tk.END).strip()
        lang = self.lang_var.get()
        if not text:
            self.set_translation_text("معنی فارسی کل متن اینجا نمایش داده می‌شود.")
            return
        if text == self._last_full_source and self.txt_translation.get("1.0", tk.END).strip():
            current = self.txt_translation.get("1.0", tk.END).strip()
            if current and not current.startswith("⏳") and not current.startswith("ترجمه انجام نشد"):
                return

        self._last_full_source = text
        self.set_translation_text("⏳ در حال ترجمه کل متن...")

        def worker():
            try:
                meaning = translate_to_persian(text, source_lang_code(lang))
            except Exception as exc:
                meaning = f"ترجمه انجام نشد: {exc}"
            self.root.after(0, lambda: self.set_translation_text(meaning))

        threading.Thread(target=worker, daemon=True).start()

    async def create_audio_async(self, text, speed, lang, filename):
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except OSError:
                pass

        rate_str = f"{speed:+d}%"
        last_error = None
        for voice in EDGE_VOICES[self._lang_key(lang)]:
            try:
                communicate = edge_tts.Communicate(text, voice, rate=rate_str)
                await communicate.save(filename)
                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    return filename
            except Exception as exc:
                last_error = exc

        say_voice = MAC_SAY_VOICES[self._lang_key(lang)]
        say_rate = max(90, min(280, int(175 * (1 + speed / 100.0))))
        aiff_path = filename if filename.lower().endswith(".aiff") else filename + ".aiff"
        result = subprocess.run(
            ["say", "-v", say_voice, "-r", str(say_rate), "-o", aiff_path, text],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not os.path.exists(aiff_path) or os.path.getsize(aiff_path) == 0:
            detail = (result.stderr or str(last_error) or "خطای نامشخص").strip()
            raise RuntimeError(f"ساخت صدا ناموفق بود: {detail}")
        return aiff_path

    def _play_file(self, path):
        subprocess.run(["afplay", path], check=False)

    def _run_speech(self, work):
        def runner():
            try:
                work()
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("خطای خواندن", str(exc)))

        threading.Thread(target=runner, daemon=True).start()

    def make_words_interactive(self, event=None):
        for tag in self.txt_main.tag_names():
            if tag.startswith("word_"):
                self.txt_main.tag_delete(tag)

        full_text = self.txt_main.get("1.0", tk.END)
        lines = full_text.splitlines()

        for line_idx, line in enumerate(lines, start=1):
            words = line.split()
            col = 0
            for word in words:
                clean_word = word.strip(".,!?()[]{}\"':;-–—")
                start_col = line.find(word, col)
                if start_col < 0:
                    continue
                end_col = start_col + len(word)
                col = end_col

                if clean_word:
                    tag_name = f"word_{line_idx}_{start_col}"
                    start_pos = f"{line_idx}.{start_col}"
                    end_pos = f"{line_idx}.{end_col}"

                    self.txt_main.tag_add(tag_name, start_pos, end_pos)
                    self.txt_main.tag_config(tag_name, foreground="#2980B9", underline=True)
                    self.txt_main.tag_bind(
                        tag_name,
                        "<Button-1>",
                        lambda e, w=clean_word: self.on_word_click(w),
                    )

    def on_word_click(self, word):
        lang = self.lang_var.get()
        cached = self._word_meanings.get(word)
        self.lbl_word.config(text=word)
        self.lbl_meaning.config(text=cached or "⏳ در حال ترجمه...")

        def worker():
            meaning = cached
            if not meaning:
                try:
                    meaning = translate_to_persian(word, source_lang_code(lang))
                except Exception as extra:
                    meaning = f"ترجمه انجام نشد: {extra}"
            self.root.after(0, lambda m=meaning: self.add_vocab_entry(word, m))

            try:
                output_file = os.path.join(tempfile.gettempdir(), "single_word.mp3")
                path = asyncio.run(self.create_audio_async(word, -20, lang, output_file))
                self._play_file(path)
            except Exception as extra:
                self.root.after(0, lambda: messagebox.showerror("خطای خواندن", str(extra)))

        threading.Thread(target=worker, daemon=True).start()

    def generate_and_play_all(self):
        text = self.txt_main.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("هشدار", "لطفاً ابتدا متنی وارد کنید!")
            return
        self.translate_full_text()
        lang = self.lang_var.get()
        speed = self.speed_scale.get()

        def speak_all():
            output_file = os.path.join(tempfile.gettempdir(), "full_output.mp3")
            path = asyncio.run(self.create_audio_async(text, speed, lang, output_file))
            self._play_file(path)

        self._run_speech(speak_all)

    def save_audio_file(self):
        text = self.txt_main.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("هشدار", "لطفاً ابتدا متنی وارد کنید!")
            return
        lang = self.lang_var.get()
        speed = self.speed_scale.get()

        file_path = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3 Audio", "*.mp3")],
            title="ذخیره فایل صوتی در مک",
        )
        if file_path:
            try:
                saved = asyncio.run(self.create_audio_async(text, speed, lang, file_path))
                if saved != file_path:
                    messagebox.showinfo("موفقیت", f"فایل صوتی ذخیره شد:\n{saved}")
                else:
                    messagebox.showinfo("موفقیت", "فایل صوتی با موفقیت ذخیره شد.")
            except Exception as exc:
                messagebox.showerror("خطای ذخیره", str(exc))


if __name__ == "__main__":
    root = tk.Tk()
    app = PerfectInteractiveApp(root)
    root.mainloop()

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import librosa
import soundfile as sf
import numpy as np
import threading
import os
import shutil
import subprocess
import sys

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from scenedetect import open_video, SceneManager, AdaptiveDetector
except ImportError:
    open_video = None
    SceneManager = None
    AdaptiveDetector = None


def _add_bundled_ffmpeg():
    base_dir = getattr(sys, "_MEIPASS", "")
    candidate_dirs = []
    if base_dir:
        candidate_dirs.append(os.path.join(base_dir, "ffmpeg"))
        candidate_dirs.append(base_dir)
    candidate_dirs.append(os.path.dirname(sys.executable))

    for folder in candidate_dirs:
        if not folder:
            continue
        ffmpeg_path = os.path.join(folder, "ffmpeg.exe")
        if os.path.isfile(ffmpeg_path):
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            break


_add_bundled_ffmpeg()

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


class ConsoleRedirector:
    def __init__(self, widget, root, max_lines=500, flush_interval_ms=80):
        self.widget = widget
        self.root = root
        self.max_lines = max_lines
        self.flush_interval_ms = flush_interval_ms
        self._buffer = []
        self._lock = threading.Lock()
        self._flush_scheduled = False

    def write(self, message):
        if not message:
            return
        with self._lock:
            self._buffer.append(message)
            if not self._flush_scheduled:
                self._flush_scheduled = True
                self.root.after(self.flush_interval_ms, self._flush)

    def _flush(self):
        with self._lock:
            text = "".join(self._buffer)
            self._buffer = []
            self._flush_scheduled = False

        if not text:
            return

        self.widget.configure(state="normal")

        parts = text.split("\r")
        for i, chunk in enumerate(parts):
            if i > 0:
                line_start = self.widget.index("end-1c linestart")
                self.widget.delete(line_start, "end-1c")
            if chunk:
                self.widget.insert(tk.END, chunk)

        line_count = int(self.widget.index("end-1c").split(".")[0])
        if line_count > self.max_lines:
            self.widget.delete("1.0", f"{line_count - self.max_lines}.0")

        self.widget.see(tk.END)
        self.widget.configure(state="disabled")

    def flush(self):
        pass

    def isatty(self):
        return False


class BeatMarkerApp:
    def __init__(self, root):
        self.root = root
        root.title("Utility")
        self._apply_windows11_style()

        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.beat_tab = ttk.Frame(self.notebook, padding=12)
        self.download_tab = ttk.Frame(self.notebook, padding=12)
        self.clip_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.download_tab, text="Download")
        self.notebook.add(self.beat_tab, text="Marker")
        self.notebook.add(self.clip_tab, text="Clips")

        self.default_download_folder = self._get_downloads_folder()
        self.selected_output = None
        self.selected_download_folder = self.default_download_folder
        self.last_download_folder = self.default_download_folder
        self.selected_clip_folder = self.default_download_folder
        self.last_clip_folder = self.default_download_folder
        self._cute_frames = ["(=^.^=)", "(=^.^=)>", "<(=^.^=)", "(=^.^=)~"]
        self._anim_jobs = {"beat": None, "download": None, "clip": None}
        self.console_visible = True

        self._build_beat_tab()
        self._build_download_tab()
        self._build_clip_tab()

    def _apply_windows11_style(self):
        style = ttk.Style(self.root)
        for theme_name in ("vista", "xpnative"):
            if theme_name in style.theme_names():
                style.theme_use(theme_name)
                break

        self.root.option_add("*Font", ("Segoe UI", 10))
        style.configure("TNotebook.Tab", padding=(12, 6))
        style.configure("TButton", padding=(12, 6))
        style.configure("TEntry", padding=(6, 4))
        style.configure("TCombobox", padding=(6, 3))
        style.configure("Horizontal.TProgressbar", thickness=10)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 6))

    def _build_beat_tab(self):
        for i in range(3):
            self.beat_tab.columnconfigure(i, weight=1)

        ttk.Label(self.beat_tab, text="Song:").grid(row=0, column=0, padx=8, pady=8, sticky="e")
        self.input_entry = ttk.Entry(self.beat_tab, width=60)
        self.input_entry.grid(row=0, column=1, padx=8, pady=8, sticky="we")
        ttk.Button(self.beat_tab, text="Search", command=self.select_input).grid(row=0, column=2, padx=8, pady=8)

        ttk.Label(self.beat_tab, text="Click Duration (s):").grid(row=1, column=0, padx=8, pady=4, sticky="e")
        self.duration_entry = ttk.Entry(self.beat_tab, width=12)
        self.duration_entry.insert(0, "0.001")
        self.duration_entry.grid(row=1, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(self.beat_tab, text="Amplitude (0-1):").grid(row=2, column=0, padx=8, pady=4, sticky="e")
        self.amplitude_entry = ttk.Entry(self.beat_tab, width=12)
        self.amplitude_entry.insert(0, "0.99")
        self.amplitude_entry.grid(row=2, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(self.beat_tab, text="Format:").grid(row=3, column=0, padx=8, pady=4, sticky="e")
        self.format_combo = ttk.Combobox(self.beat_tab, values=["flac", "wav"], state="readonly", width=10)
        self.format_combo.set("flac")
        self.format_combo.grid(row=3, column=1, padx=8, pady=4, sticky="w")

        self.output_button = ttk.Button(self.beat_tab, text="Save As...", command=self.select_output)
        self.output_button.grid(row=3, column=2, padx=8, pady=4)

        self.process_button = ttk.Button(self.beat_tab, text="Generate Beat Markers", command=self.process, style="Accent.TButton")
        self.process_button.grid(row=4, column=1, padx=8, pady=12)

        self.progress_frame = ttk.Frame(self.beat_tab)
        self.progress_frame.grid(row=5, column=0, columnspan=3, padx=8, pady=6, sticky="we")
        self.progress_frame.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(self.progress_frame, mode="indeterminate")
        self.progress.grid(row=0, column=0, sticky="we")
        self.beat_anim_label = ttk.Label(self.progress_frame, text="", width=12, anchor="w")
        self.beat_anim_label.grid(row=0, column=1, padx=(8, 0))

        self.status_label = ttk.Label(self.beat_tab, text="Ready")
        self.status_label.grid(row=6, column=0, columnspan=2, padx=8, pady=6, sticky="w")

        self.open_folder_button = ttk.Button(self.beat_tab, text="Open Folder", command=self.open_output_folder, state=tk.DISABLED)
        self.open_folder_button.grid(row=6, column=2, padx=8, pady=6, sticky="e")

    def _build_download_tab(self):
        for i in range(3):
            self.download_tab.columnconfigure(i, weight=1)

        ttk.Label(self.download_tab, text="Video Link:").grid(row=0, column=0, padx=8, pady=8, sticky="e")
        self.download_url_entry = ttk.Entry(self.download_tab, width=60)
        self.download_url_entry.grid(row=0, column=1, padx=8, pady=8, sticky="we")

        ttk.Label(self.download_tab, text="Edit Preset:").grid(row=1, column=0, padx=8, pady=4, sticky="e")
        self.download_preset_combo = ttk.Combobox(
            self.download_tab,
            values=[
                "FLAC (lossless)",
                "WAV (uncompressed)",
                "M4A (high quality)",
                "MP3 320k",
                "Best original",
            ],
            state="readonly",
            width=18,
        )
        self.download_preset_combo.set("FLAC (lossless)")
        self.download_preset_combo.grid(row=1, column=1, padx=8, pady=4, sticky="w")

        self.download_folder_button = ttk.Button(self.download_tab, text="Target Folder...", command=self.select_download_folder)
        self.download_folder_button.grid(row=1, column=2, padx=8, pady=4)

        self.create_marker_var = tk.BooleanVar(value=False)
        self.create_marker_check = ttk.Checkbutton(
            self.download_tab,
            text="Also create Beat Marker",
            variable=self.create_marker_var,
        )
        self.create_marker_check.grid(row=2, column=0, columnspan=2, padx=8, pady=4, sticky="w")

        ttk.Label(self.download_tab, text="Marker Format:").grid(row=2, column=2, padx=8, pady=4, sticky="e")
        self.marker_format_combo = ttk.Combobox(self.download_tab, values=["flac", "wav"], state="readonly", width=10)
        self.marker_format_combo.set("flac")
        self.marker_format_combo.grid(row=2, column=2, padx=(110, 8), pady=4, sticky="w")

        self.download_button = ttk.Button(self.download_tab, text="Download Audio", command=self.download_audio, style="Accent.TButton")
        self.download_button.grid(row=3, column=1, padx=8, pady=12)

        self.download_progress_frame = ttk.Frame(self.download_tab)
        self.download_progress_frame.grid(row=4, column=0, columnspan=3, padx=8, pady=6, sticky="we")
        self.download_progress_frame.columnconfigure(0, weight=1)

        self.download_progress = ttk.Progressbar(self.download_progress_frame, mode="indeterminate")
        self.download_progress.grid(row=0, column=0, sticky="we")
        self.download_anim_label = ttk.Label(self.download_progress_frame, text="", width=12, anchor="w")
        self.download_anim_label.grid(row=0, column=1, padx=(8, 0))

        self.download_status_label = ttk.Label(self.download_tab, text="Ready")
        self.download_status_label.grid(row=5, column=0, columnspan=2, padx=8, pady=6, sticky="w")

        self.open_download_folder_button = ttk.Button(self.download_tab, text="Open Folder", command=self.open_download_folder, state=tk.DISABLED)
        self.open_download_folder_button.grid(row=5, column=2, padx=8, pady=6, sticky="e")

    def _build_clip_tab(self):
        for i in range(3):
            self.clip_tab.columnconfigure(i, weight=1)

        ttk.Label(self.clip_tab, text="Video Link:").grid(row=0, column=0, padx=8, pady=8, sticky="e")
        self.clip_url_entry = ttk.Entry(self.clip_tab, width=60)
        self.clip_url_entry.grid(row=0, column=1, padx=8, pady=8, sticky="we")

        ttk.Label(self.clip_tab, text="Output Folder:").grid(row=1, column=0, padx=8, pady=4, sticky="e")
        self.clip_folder_label = ttk.Label(self.clip_tab, text=self.selected_clip_folder, anchor="w")
        self.clip_folder_label.grid(row=1, column=1, padx=8, pady=4, sticky="we")
        self.clip_folder_button = ttk.Button(self.clip_tab, text="Choose Folder...", command=self.select_clip_folder)
        self.clip_folder_button.grid(row=1, column=2, padx=8, pady=4)

        ttk.Label(self.clip_tab, text="Scene Threshold:").grid(row=2, column=0, padx=8, pady=4, sticky="e")
        self.clip_threshold_entry = ttk.Entry(self.clip_tab, width=12)
        self.clip_threshold_entry.insert(0, "3.0")
        self.clip_threshold_entry.grid(row=2, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(self.clip_tab, text="Minimum Clip Length (s):").grid(row=3, column=0, padx=8, pady=4, sticky="e")
        self.clip_min_length_entry = ttk.Entry(self.clip_tab, width=12)
        self.clip_min_length_entry.insert(0, "3.0")
        self.clip_min_length_entry.grid(row=3, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(self.clip_tab, text="Maximum Clips:").grid(row=4, column=0, padx=8, pady=4, sticky="e")
        self.clip_max_clips_entry = ttk.Entry(self.clip_tab, width=12)
        self.clip_max_clips_entry.insert(0, "30")
        self.clip_max_clips_entry.grid(row=4, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(self.clip_tab, text="Frame Skip:").grid(row=5, column=0, padx=8, pady=4, sticky="e")
        self.clip_frame_skip_entry = ttk.Entry(self.clip_tab, width=12)
        self.clip_frame_skip_entry.insert(0, "1")
        self.clip_frame_skip_entry.grid(row=5, column=1, padx=8, pady=4, sticky="w")

        self.clip_button = ttk.Button(self.clip_tab, text="Extract Clips", command=self.extract_video_clips, style="Accent.TButton")
        self.clip_button.grid(row=6, column=1, padx=8, pady=12)

        self.clip_progress_frame = ttk.Frame(self.clip_tab)
        self.clip_progress_frame.grid(row=7, column=0, columnspan=3, padx=8, pady=6, sticky="we")
        self.clip_progress_frame.columnconfigure(0, weight=1)

        self.clip_progress = ttk.Progressbar(self.clip_progress_frame, mode="indeterminate")
        self.clip_progress.grid(row=0, column=0, sticky="we")
        self.clip_anim_label = ttk.Label(self.clip_progress_frame, text="", width=12, anchor="w")
        self.clip_anim_label.grid(row=0, column=1, padx=(8, 0))

        self.clip_status_label = ttk.Label(self.clip_tab, text="Ready")
        self.clip_status_label.grid(row=8, column=0, columnspan=2, padx=8, pady=6, sticky="w")

        self.open_clip_folder_button = ttk.Button(self.clip_tab, text="Open Folder", command=self.open_clip_folder, state=tk.DISABLED)
        self.open_clip_folder_button.grid(row=8, column=2, padx=8, pady=6, sticky="e")

        self.console_toggle_button = ttk.Button(
            self.clip_tab, text="▼ Console Output", command=self._toggle_console
        )
        self.console_toggle_button.grid(row=9, column=0, columnspan=3, padx=8, pady=(10, 2), sticky="w")

        self.clip_console = scrolledtext.ScrolledText(
            self.clip_tab, height=10, state="disabled", font=("Consolas", 9), wrap="word"
        )
        self.clip_console.grid(row=10, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="nsew")
        self.clip_tab.rowconfigure(10, weight=1)

        self.clip_console_redirector = ConsoleRedirector(self.clip_console, self.root)

    def _toggle_console(self):
        if self.console_visible:
            self.clip_console.grid_remove()
            self.clip_tab.rowconfigure(10, weight=0)
            self.console_toggle_button.config(text="▶ Console Output")
        else:
            self.clip_console.grid()
            self.clip_tab.rowconfigure(10, weight=1)
            self.console_toggle_button.config(text="▼ Console Output")
        self.console_visible = not self.console_visible

    def select_input(self):
        file_path = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav *.flac *.ogg"), ("All Files", "*.*")])
        if file_path:
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, file_path)

    def select_output(self):
        inp = self.input_entry.get()
        if not inp:
            messagebox.showwarning("Warning", "Please select an input file first.")
            return
        base = os.path.splitext(inp)[0]
        fmt = self.format_combo.get()
        default = f"{base}_beats.{fmt}"
        out = filedialog.asksaveasfilename(defaultextension=f".{fmt}", initialfile=os.path.basename(default), filetypes=[(fmt.upper(), f"*.{fmt}"), ("All Files", "*.*")])
        if out:
            self.selected_output = out

    def select_download_folder(self):
        folder = filedialog.askdirectory(initialdir=self.default_download_folder)
        if folder:
            self.selected_download_folder = folder
            self.download_status_label.config(text=f"Target folder: {folder}")

    def _get_downloads_folder(self):
        downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")
        if os.path.isdir(downloads_folder):
            return downloads_folder
        home_folder = os.path.expanduser("~")
        os.makedirs(home_folder, exist_ok=True)
        return home_folder

    def _start_cute_animation(self, key, label):
        self._stop_cute_animation(key)
        self._animate_label(key, label, 0)

    def _animate_label(self, key, label, index):
        label.config(text=self._cute_frames[index])
        next_index = (index + 1) % len(self._cute_frames)
        self._anim_jobs[key] = self.root.after(180, lambda: self._animate_label(key, label, next_index))

    def _stop_cute_animation(self, key):
        job = self._anim_jobs.get(key)
        if job:
            self.root.after_cancel(job)
        self._anim_jobs[key] = None
        if key == "beat":
            self.beat_anim_label.config(text="")
        elif key == "download":
            self.download_anim_label.config(text="")
        elif key == "clip":
            self.clip_anim_label.config(text="")

    def _yt_dlp_progress_hook(self, d, progress_bar):
        if d['status'] == 'downloading':
            try:
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes', 0)
                if total_bytes and total_bytes > 0:
                    percentage = (downloaded / total_bytes) * 100
                    self.root.after(0, lambda: progress_bar.config(mode="determinate", maximum=100, value=percentage))
            except Exception:
                pass
        elif d['status'] == 'finished':
            self.root.after(0, lambda: progress_bar.config(mode="indeterminate"))
            self.root.after(0, lambda: progress_bar.start(10))

    def process(self):
        input_path = self.input_entry.get()

        if not input_path:
            messagebox.showerror("Error", "Please select an input file.")
            return

        try:
            click_duration = float(self.duration_entry.get())
            click_amplitude = float(self.amplitude_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid duration or amplitude value.")
            return

        if not (0 < click_amplitude <= 1):
            messagebox.showerror("Error", "Amplitude must be between 0 and 1.")
            return

        if not (0 < click_duration <= 1):
            messagebox.showerror("Error", "Duration must be between 0 and 1 second.")
            return

        if self.selected_output:
            output_path = self.selected_output
        else:
            fmt = self.format_combo.get() or "flac"
            output_path = os.path.splitext(input_path)[0] + f"_beats.{fmt}"

        self.status_label.config(text="Processing...")
        self.process_button.config(state=tk.DISABLED)
        self.open_folder_button.config(state=tk.DISABLED)
        self.progress.start(10)
        self._start_cute_animation("beat", self.beat_anim_label)
        self.root.update()

        threading.Thread(target=self._process_thread, args=(input_path, output_path, click_duration, click_amplitude), daemon=True).start()

    def _process_thread(self, input_path, output_path, click_duration, click_amplitude):
        try:
            self._create_beat_marker(input_path, output_path, click_duration, click_amplitude)
            self.root.after(0, lambda: self._on_done(output_path))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self._on_finish())

    def _on_done(self, output_path):
        self.progress.stop()
        self._stop_cute_animation("beat")
        self.status_label.config(text=f"Done! Saved: {output_path}")
        self.process_button.config(state=tk.NORMAL)
        self.open_folder_button.config(state=tk.NORMAL)
        self.selected_output = output_path

    def _on_finish(self):
        self.progress.stop()
        self._stop_cute_animation("beat")
        self.process_button.config(state=tk.NORMAL)

    def open_output_folder(self):
        if not self.selected_output:
            return
        folder = os.path.dirname(self.selected_output)
        try:
            if os.name == 'nt':
                os.startfile(folder)
            else:
                import webbrowser
                webbrowser.open(folder)
        except Exception:
            messagebox.showwarning("Warning", "Folder could not be opened.")

    def open_download_folder(self):
        folder = self.last_download_folder or self.default_download_folder
        if not folder:
            return
        try:
            if os.name == 'nt':
                os.startfile(folder)
            else:
                import webbrowser
                webbrowser.open(folder)
        except Exception:
            messagebox.showwarning("Warning", "Folder could not be opened.")

    def select_clip_folder(self):
        folder = filedialog.askdirectory(initialdir=self.selected_clip_folder or self.default_download_folder)
        if folder:
            self.selected_clip_folder = folder
            self.clip_folder_label.config(text=folder)

    def open_clip_folder(self):
        folder = self.last_clip_folder or self.selected_clip_folder or self.default_download_folder
        if not folder:
            return
        try:
            if os.name == 'nt':
                os.startfile(folder)
            else:
                import webbrowser
                webbrowser.open(folder)
        except Exception:
            messagebox.showwarning("Warning", "Folder could not be opened.")

    def extract_video_clips(self):
        if yt_dlp is None:
            messagebox.showerror("Error", "yt-dlp is not installed. Please install it first.")
            return

        if open_video is None or SceneManager is None or AdaptiveDetector is None:
            messagebox.showerror("Error", "scenedetect is not installed. Please install it first.")
            return

        if shutil.which("ffmpeg") is None:
            messagebox.showerror("Error", "FFmpeg is required for video download and clip extraction.")
            return

        url = self.clip_url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a video link.")
            return

        try:
            threshold = float(self.clip_threshold_entry.get())
            min_length = float(self.clip_min_length_entry.get())
            max_clips = int(self.clip_max_clips_entry.get())
            frame_skip = int(self.clip_frame_skip_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid threshold, length, clip count, or frame skip value.")
            return

        if threshold <= 0:
            messagebox.showerror("Error", "Scene threshold must be greater than 0.")
            return

        if min_length <= 0:
            messagebox.showerror("Error", "Minimum clip length must be greater than 0.")
            return

        if max_clips <= 0:
            messagebox.showerror("Error", "Maximum clips must be greater than 0.")
            return

        if frame_skip < 1:
            messagebox.showerror("Error", "Frame skip must be at least 1.")
            return

        target_folder = self.selected_clip_folder or self.default_download_folder
        os.makedirs(target_folder, exist_ok=True)

        self.clip_console.configure(state="normal")
        self.clip_console.delete("1.0", tk.END)
        self.clip_console.configure(state="disabled")

        self.clip_status_label.config(text="Downloading video...")
        self.clip_button.config(state=tk.DISABLED)
        self.open_clip_folder_button.config(state=tk.DISABLED)
        self.clip_progress.config(mode="indeterminate")
        self.clip_progress.start(10)
        self._start_cute_animation("clip", self.clip_anim_label)
        self.root.update()

        threading.Thread(
            target=self._extract_video_clips_thread,
            args=(url, target_folder, threshold, min_length, max_clips, frame_skip),
            daemon=True,
        ).start()

    def _extract_video_clips_thread(self, url, target_folder, threshold, min_length, max_clips, frame_skip):
        input_highres = os.path.join(os.getcwd(), "input_highres.mp4")
        input_proxy = os.path.join(os.getcwd(), "input_proxy.mp4")

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = self.clip_console_redirector
        sys.stderr = self.clip_console_redirector

        try:
            self._download_clip_source(url, input_highres)
            
            self.root.after(0, lambda: self.clip_progress.config(mode="indeterminate"))
            self.root.after(0, lambda: self.clip_progress.start(10))
            self.root.after(0, lambda: self.clip_status_label.config(text="Creating proxy for analysis..."))
            self._create_proxy(input_highres, input_proxy)

            self.root.after(0, lambda: self.clip_status_label.config(text="Starting scene analysis..."))
            scene_list = self._detect_scenes(input_proxy, threshold, frame_skip)

            self.root.after(0, lambda: self._set_clip_progress_determinate(len(scene_list)))
            self.root.after(0, lambda: self.clip_status_label.config(text=f"{len(scene_list)} potential scenes found. Extracting clips..."))
            clips_created = self._extract_clips(input_highres, target_folder, scene_list, min_length, max_clips)

            self.root.after(0, lambda: self._on_clip_done(target_folder, clips_created, len(scene_list)))
        except Exception as e:
            error_message = str(e)
            self.root.after(0, lambda message=error_message: messagebox.showerror("Error", message))
            self.root.after(0, lambda: self._on_clip_finish())
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            self._safe_remove_file(input_proxy)

    def _download_clip_source(self, url, output_file):
        options = {
            "outtmpl": output_file,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [lambda d: self._yt_dlp_progress_hook(d, self.clip_progress)],
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)

        if not os.path.exists(output_file):
            raise RuntimeError("Video download failed.")

    def _run_ffmpeg(self, cmd, error_message):
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        for line in process.stdout:
            sys.stdout.write(line)
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(error_message)

    def _create_proxy(self, input_file, proxy_file):
        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-vf", "scale=-2:360",
            "-an",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            proxy_file,
        ]

        self._run_ffmpeg(cmd, "Proxy creation failed.")
        if not os.path.exists(proxy_file):
            raise RuntimeError("Proxy creation failed.")

    def _detect_scenes(self, proxy_file, threshold, frame_skip):
        video = None
        try:
            video = open_video(proxy_file)
            scene_manager = SceneManager()
            scene_manager.add_detector(AdaptiveDetector(adaptive_threshold=threshold))
            scene_manager.detect_scenes(video, frame_skip=frame_skip, show_progress=True)
            return scene_manager.get_scene_list()
        except Exception as e:
            raise RuntimeError(f"Error during scene analysis: {e}") from e
        finally:
            if video is not None:
                del video

    def _extract_clips(self, input_file, output_folder, scene_list, min_length, max_clips):
        os.makedirs(output_folder, exist_ok=True)

        clips_created = 0
        total_scenes = len(scene_list)

        for index, scene in enumerate(scene_list, start=1):
            if clips_created >= max_clips:
                break

            start = scene[0].get_seconds()
            end = scene[1].get_seconds()
            duration = end - start

            if duration >= min_length:
                output_file = os.path.join(output_folder, f"clip_{clips_created + 1}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-ss", str(start), "-i", input_file,
                    "-t", str(duration), "-c", "copy", output_file,
                ]
                self._run_ffmpeg(cmd, f"Clip extraction failed for scene starting at {start:.2f}s.")
                clips_created += 1

            self.root.after(0, lambda i=index, total=total_scenes, current=clips_created:
                self._update_clip_progress(i, total, current))

        return clips_created

    def _update_clip_progress(self, scenes_done, total_scenes, clips_created):
        self.clip_progress["value"] = scenes_done
        self.clip_status_label.config(
            text=f"Scene {scenes_done}/{total_scenes} analyzed – {clips_created} clip(s) extracted."
        )

    def _set_clip_progress_determinate(self, maximum):
        self.clip_progress.stop()
        self.clip_progress.config(mode="determinate", maximum=max(maximum, 1), value=0)

    def _safe_remove_file(self, file_path):
        if not os.path.exists(file_path):
            return

        try:
            os.remove(file_path)
        except Exception as e:
            warning_message = f"Warning: temporary file could not be deleted: {e}"
            self.root.after(0, lambda message=warning_message: self.clip_status_label.config(text=message))

    def _on_clip_done(self, output_folder, clips_created, scene_count):
        self.clip_progress.stop()
        self.clip_progress.config(mode="indeterminate", value=0)
        self._stop_cute_animation("clip")
        self.clip_status_label.config(text=f"Done! {clips_created} clips saved from {scene_count} scenes.")
        self.clip_button.config(state=tk.NORMAL)
        self.open_clip_folder_button.config(state=tk.NORMAL)
        self.last_clip_folder = output_folder

    def _on_clip_finish(self):
        self.clip_progress.stop()
        self.clip_progress.config(mode="indeterminate", value=0)
        self._stop_cute_animation("clip")
        self.clip_button.config(state=tk.NORMAL)

    def download_audio(self):
        if yt_dlp is None:
            messagebox.showerror("Error", "yt-dlp is not installed. Please install it first.")
            return

        url = self.download_url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a video link.")
            return

        preset = self.download_preset_combo.get() or "FLAC (lossless)"
        preset_key = self._preset_to_key(preset)
        create_marker = self.create_marker_var.get()
        click_duration = 0.001
        click_amplitude = 0.99

        if create_marker:
            try:
                click_duration = float(self.duration_entry.get())
                click_amplitude = float(self.amplitude_entry.get())
            except ValueError:
                messagebox.showerror("Error", "Invalid duration or amplitude value for the Beat Marker.")
                return

            if not (0 < click_amplitude <= 1):
                messagebox.showerror("Error", "Amplitude must be between 0 and 1.")
                return

            if not (0 < click_duration <= 1):
                messagebox.showerror("Error", "Duration must be between 0 and 1 second.")
                return

        if preset_key in {"flac", "wav", "m4a", "mp3"} and shutil.which("ffmpeg") is None:
            messagebox.showerror("Error", "FFmpeg is required for FLAC, WAV, M4A, and MP3 presets.")
            return

        target_folder = self.selected_download_folder or self.default_download_folder
        os.makedirs(target_folder, exist_ok=True)

        self.download_status_label.config(text=f"Downloading {preset}...")
        self.download_button.config(state=tk.DISABLED)
        self.open_download_folder_button.config(state=tk.DISABLED)
        self.download_progress.start(10)
        self._start_cute_animation("download", self.download_anim_label)
        self.root.update()

        threading.Thread(
            target=self._download_thread,
            args=(url, preset_key, target_folder, create_marker, self.marker_format_combo.get() or "flac", click_duration, click_amplitude),
            daemon=True,
        ).start()

    def _download_thread(self, url, preset_key, target_folder, create_marker, marker_format, click_duration, click_amplitude):
        try:
            output_path = self._download_audio_file(url, preset_key, target_folder, self.download_progress)
            marker_path = None
            if create_marker:
                marker_path = self._build_marker_output_path(output_path, marker_format)
                self._create_beat_marker(output_path, marker_path, click_duration, click_amplitude)
            self.root.after(0, lambda: self._on_download_done(output_path, marker_path))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self._on_download_finish())

    def _on_download_done(self, output_path, marker_path=None):
        self.download_progress.stop()
        self._stop_cute_animation("download")
        if marker_path:
            self.download_status_label.config(text=f"Done! Saved: {output_path} | Marker: {marker_path}")
        else:
            self.download_status_label.config(text=f"Done! Saved: {output_path}")
        self.download_button.config(state=tk.NORMAL)
        self.open_download_folder_button.config(state=tk.NORMAL)
        self.last_download_folder = os.path.dirname(output_path)
        self.selected_download_folder = self.default_download_folder

    def _on_download_finish(self):
        self.download_progress.stop()
        self._stop_cute_animation("download")
        self.download_button.config(state=tk.NORMAL)
        self.selected_download_folder = self.default_download_folder

    def _preset_to_key(self, preset):
        mapping = {
            "FLAC (lossless)": "flac",
            "WAV (uncompressed)": "wav",
            "M4A (high quality)": "m4a",
            "MP3 320k": "mp3",
            "Best original": "best",
        }
        return mapping.get(preset, "flac")

    def _download_audio_file(self, url, preset_key, target_folder, progress_bar):
        options = {
            "outtmpl": os.path.join(target_folder, "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [lambda d: self._yt_dlp_progress_hook(d, progress_bar)],
        }

        if preset_key == "best":
            options["format"] = "bestaudio/best"
        else:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": preset_key,
                    "preferredquality": "0" if preset_key == "flac" else "320",
                }
            ]

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            base_path = ydl.prepare_filename(info)

        if preset_key == "best":
            return base_path

        return os.path.splitext(base_path)[0] + f".{preset_key}"

    def _build_marker_output_path(self, audio_path, marker_format):
        base_name = os.path.splitext(audio_path)[0]
        return f"{base_name}_beats.{marker_format}"

    def _create_beat_marker(self, input_path, output_path, click_duration, click_amplitude):
        y, sr = librosa.load(input_path, sr=None, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_samples = librosa.frames_to_samples(beat_frames)

        self.root.after(0, lambda: self.status_label.config(text=f"Tempo detected: {float(tempo):.1f} BPM, {len(beat_samples)} Beats"))

        marker_audio = np.zeros_like(y)

        for sample in beat_samples:
            start = sample
            end = min(start + int(click_duration * sr), len(y))
            marker_audio[start:end] = click_amplitude

        fmt = os.path.splitext(output_path)[1].lstrip('.').lower()
        sf.write(output_path, marker_audio, sr, format=fmt if fmt in ('flac', 'wav', 'ogg') else None)


if __name__ == "__main__":
    root = tk.Tk()
    app = BeatMarkerApp(root)
    root.mainloop()
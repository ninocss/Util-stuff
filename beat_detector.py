import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import librosa
import soundfile as sf
import numpy as np
import threading
import os
import shutil
import sys

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


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


class BeatMarkerApp:
    def __init__(self, root):
        self.root = root
        root.title("util stuff")
        self._apply_windows11_style()

        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.beat_tab = ttk.Frame(self.notebook, padding=12)
        self.download_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.beat_tab, text="Beat Marker")
        self.notebook.add(self.download_tab, text="Audio Download")

        self.default_download_folder = self._get_downloads_folder()
        self.selected_output = None
        self.selected_download_folder = self.default_download_folder
        self.last_download_folder = self.default_download_folder
        self._cute_frames = ["(=^.^=)", "(=^.^=)>", "<(=^.^=)", "(=^.^=)~"]
        self._anim_jobs = {"beat": None, "download": None}

        self._build_beat_tab()
        self._build_download_tab()

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
            output_path = self._download_audio_file(url, preset_key, target_folder)
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

    def _download_audio_file(self, url, preset_key, target_folder):
        options = {
            "outtmpl": os.path.join(target_folder, "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
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
        # soundfile infers format from extension for common cases
        sf.write(output_path, marker_audio, sr, format=fmt if fmt in ('FLAC', 'WAV', 'OGG') else None)

if __name__ == "__main__":
    root = tk.Tk()
    app = BeatMarkerApp(root)
    root.mainloop()
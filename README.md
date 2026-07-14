Beats Finder
============

Kurz: Ein kleines Tool zum Extrahieren von Audio aus Videos und automatisches Erzeugen von Beat-Marker-Audios.

Wichtiges
---------
- Dieses Repository enthält das Python-Skript `beat_detector.py`.
- Abhängigkeiten stehen in `requirements.txt`.
- Zum Erzeugen einer portablen Windows-EXE benutze `build_exe.bat` (benötigt `PyInstaller`).
- Für FLAC/WAV/M4A/MP3-Presets wird `ffmpeg` benötigt. Lege `ffmpeg.exe` und `ffprobe.exe` in `vendor\ffmpeg\` oder ins Projektverzeichnis.
- Der Tab `Video Clips` benötigt zusätzlich `scenedetect` für die Scene-Erkennung.

Schnellstart (Windows)
----------------------
1. Virtuelle Umgebung erstellen (optional empfohlen):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Abhängigkeiten installieren:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. EXE bauen (legt `dist\BeatsFinder.exe` an):

```powershell
.\build_exe.bat
```

Hinweis: Lege `ffmpeg.exe` in `vendor\ffmpeg\` falls das Build-Skript diese mitpacken soll.

Aufräumen
---------
Es gibt ein Skript `clean_project.bat`, das generierte Ordner entfernt (`build`, `dist`, `__pycache__`) und alte Spec-Dateien löscht.

Anpassungen
-----------
- UI: Windows-11-inspiriertes Look & Feel, Sekundär-Tab für Audio-Download mit Presets.
- Optional: Automatische Beat-Marker-Erstellung nach Download (Checkbox im Download-Tab).
- Neuer Tab: Video-Link eingeben, Proxy-Analyse starten und bis zu `max_clips` Clips aus den erkannten Szenen extrahieren.

Lizenz & Haftung
----------------
Nutze das Tool verantwortungsvoll. Für das Herunterladen von Inhalten richte dich nach den jeweiligen Plattformbedingungen und Urheberrechtsgesetzen.

Viel Spaß!

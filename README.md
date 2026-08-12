# NovaDL

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="License: AGPL-3.0">
</p>

NovaDL is a high-performance, command-line media downloader built on top of **yt-dlp** and **spotdl**. It fully automates downloading, metadata tagging, and playlist processing across multiple platforms while managing external dependencies and fallback mechanisms automatically.

---

## 🚀 Features

⚡ **Multithreaded Processing**
Downloads multiple items from playlists or albums concurrently using `ThreadPoolExecutor` to drastically reduce overall processing time.

📦 **Self-Bootstrapping Environment**
Automatically fetches required portable binaries (`yt-dlp`, `Deno`) and updates core Python packages (`spotdl`) inside an isolated local `tools/` directory, minimizing manual setup.

🔄 **Smart Fallback Mechanisms**
Automatically switches to alternative extraction clients, engines, or scrape methods if the primary API request fails.

🌐 **Aria2c Integration**
Detects and utilizes `aria2c` as an external downloader for high-speed concurrent file fragment downloading.

💻 **Interactive CLI**
Provides a minimal, intuitive console interface for selecting audio/video formats (`MP3`, `WAV`, `MP4`) and managing destination download directories.

---

## 🎵 Supported Platforms

📹 **YouTube** — Videos, Playlists, Channels, Audio
🎧 **Spotify** — Tracks, Albums, Playlists
☁️ **SoundCloud** — Tracks, Sets

---

## 🛠️ Prerequisites

💻 **OS**: Windows 10/11 (fully automated local dependency management). Linux/macOS are supported if `yt-dlp`, `deno`, and `ffmpeg` are already available in your system PATH.

🐍 **Python**: Version 3.8 or higher.

🎬 **FFmpeg**: Required for media merging, post-processing, and conversion. On Windows, NovaDL automatically checks standard `winget` installation paths. If missing, install it via:

```bash
winget install ffmpeg
```
---

## 💻 Usage

Run the following command in your terminal to clone the repository and start the interactive CLI setup immediately:

```bash
git clone https://github.com/W3rzzzy/NovaDL.git && cd NovaDL && python NovaDL.py
```

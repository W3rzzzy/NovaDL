import os
import sys
import subprocess
import re
import io
import glob
import zipfile
import hashlib
import urllib.request
from urllib.parse import urlparse, parse_qs
import json
import time
import shutil
import threading
import importlib.util
from concurrent.futures import ThreadPoolExecutor

if os.name == 'nt':
    import msvcrt
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    os.system('')

# Директория для портативных зависимостей (yt-dlp, deno).
# Позволяет избежать проблем с установкой через pip и отсутствием MSVC на Windows.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
YTDLP_EXE = os.path.join(TOOLS_DIR, "yt-dlp.exe")
DENO_EXE = os.path.join(TOOLS_DIR, "deno.exe")
CONFIG_FILE = os.path.join(TOOLS_DIR, "config.json")
LOG_FILE = os.path.join(TOOLS_DIR, "novadl.log")

def _load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_config(cfg):
    try:
        os.makedirs(TOOLS_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

_config = _load_config()

USER_HOME = os.path.expanduser("~")
SAVE_PATH = os.environ.get("NOVADL_SAVE_PATH") or _config.get("save_path") or os.path.join(USER_HOME, "Downloads", "NovaDL")
COOKIES_PATH = os.environ.get("NOVADL_COOKIES_PATH", os.path.join(USER_HOME, "Downloads", "cookies.txt"))

CLR = "\033[0m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
WHITE = "\033[97m"
BOLD = "\033[1m"

_log_lock = threading.Lock()

def log_line(text):
    """Пишет строку в лог-файл (для последующей отладки/issue на GitHub). Никогда не бросает исключений наружу."""
    try:
        with _log_lock:
            os.makedirs(TOOLS_DIR, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────
# FFmpeg: поиск без привязки к конкретной версии winget-пакета
# ──────────────────────────────────────────────────────────────────────────

def _find_ffmpeg_dir():
    """Ищет директорию с ffmpeg в порядке приоритета, без жёсткой привязки к версии пакета."""
    exe_name = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"

    env_dir = os.environ.get("NOVADL_FFMPEG_DIR")
    if env_dir and os.path.isfile(os.path.join(env_dir, exe_name)):
        return env_dir

    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return os.path.dirname(os.path.abspath(ffmpeg_in_path))

    if os.name == 'nt':
        winget_packages = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"
        )
        try:
            candidates = glob.glob(os.path.join(winget_packages, "Gyan.FFmpeg*", "*", "bin", "ffmpeg.exe"))
            candidates += glob.glob(os.path.join(winget_packages, "Gyan.FFmpeg*", "bin", "ffmpeg.exe"))
            if candidates:
                # Берём самую свежую версию: сортировка по имени папки (обычно содержит версию)
                candidates.sort(reverse=True)
                return os.path.dirname(candidates[0])
        except Exception:
            pass

        portable = os.path.join(TOOLS_DIR, "ffmpeg", "bin")
        if os.path.isfile(os.path.join(portable, "ffmpeg.exe")):
            return portable

    return ""

FFMPEG_DIR = _find_ffmpeg_dir()

if FFMPEG_DIR and FFMPEG_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

def ensure_ffmpeg():
    """Проверяет наличие FFmpeg и, если это Windows с winget, пытается доустановить его."""
    global FFMPEG_DIR

    exe_name = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"
    if FFMPEG_DIR and os.path.isfile(os.path.join(FFMPEG_DIR, exe_name)):
        return

    if os.name != 'nt' or not shutil.which("winget"):
        print(f"{RED}[-] FFmpeg не найден в системе.{CLR}")
        print(f"{YELLOW}[~] Установите FFmpeg вручную (https://ffmpeg.org/download.html) "
              f"или укажите путь через переменную NOVADL_FFMPEG_DIR.{CLR}")
        log_line("FFmpeg не найден, автоустановка недоступна (нет winget или не Windows)")
        return

    print(f"{CYAN}[*] FFmpeg не найден, устанавливаю через winget...{CLR}")
    try:
        subprocess.run(
            ["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180
        )
    except Exception as e:
        print(f"{RED}[-] Не удалось установить FFmpeg автоматически: {e}{CLR}")
        log_line(f"Ошибка автоустановки FFmpeg: {e}")
        return

    FFMPEG_DIR = _find_ffmpeg_dir()
    if FFMPEG_DIR:
        if FFMPEG_DIR not in os.environ.get("PATH", ""):
            os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")
        print(f"{GREEN}[+] FFmpeg установлен: {FFMPEG_DIR}{CLR}")
    else:
        print(f"{RED}[-] FFmpeg всё ещё не найден после установки. "
              f"Проверьте PATH или переменную NOVADL_FFMPEG_DIR.{CLR}")
        log_line("FFmpeg не найден после попытки автоустановки через winget")

YTDLP_RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
YTDLP_SHA256SUMS_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
DENO_RELEASE_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
DENO_SHA256SUM_URL = DENO_RELEASE_URL + ".sha256sum"

UPDATE_STATE_FILE = os.path.join(TOOLS_DIR, "update_state.json")
UPDATE_INTERVAL_SECONDS = 12 * 60 * 60

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def ensure_save_directory():
    if not os.path.exists(SAVE_PATH):
        os.makedirs(SAVE_PATH)
    return SAVE_PATH

def prompt_change_save_directory():
    global SAVE_PATH
    print(f"\n{WHITE}Текущая директория:{CLR} {YELLOW}{SAVE_PATH}{CLR}")
    new_path = input(f"{WHITE}Новая директория (Enter - отмена):{CLR} ").strip().strip('"')
    if not new_path:
        print(f"{YELLOW}[~] Операция отменена.{CLR}")
        return

    try:
        os.makedirs(new_path, exist_ok=True)
    except Exception as e:
        print(f"{RED}[-] Не удалось использовать данную директорию: {e}{CLR}")
        return

    if os.environ.get("NOVADL_SAVE_PATH"):
        print(f"{YELLOW}[~] Внимание: переменная окружения NOVADL_SAVE_PATH переопределит эту настройку при следующем запуске.{CLR}")

    SAVE_PATH = new_path
    cfg = _load_config()
    cfg["save_path"] = new_path
    if _save_config(cfg):
        print(f"{GREEN}[+] Директория сохранена:{CLR} {WHITE}{new_path}{CLR}")
    else:
        print(f"{YELLOW}[~] Директория изменена только для текущей сессии (сбой сохранения конфига).{CLR}")

def _with_retries(fn, attempts=3, delay=2):
    last_err = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < attempts - 1:
                time.sleep(delay)
    raise last_err

def _fetch_url_bytes(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()

def _verify_sha256(data, expected_hex):
    return hashlib.sha256(data).hexdigest().lower() == expected_hex.strip().lower()

def _extract_hash_for_file(sums_text, filename):
    """Разбирает файл контрольных сумм формата 'hash  filename' или содержащий только hash."""
    for line in sums_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0]
        if len(parts) == 1 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            # Файл сумм содержит только хеш (без имени файла) - характерно для *.sha256sum
            return parts[0]
    return None

def ensure_ytdlp():
    if os.name != 'nt':
        return "yt-dlp"

    if os.path.exists(YTDLP_EXE):
        return YTDLP_EXE

    os.makedirs(TOOLS_DIR, exist_ok=True)
    print(f"{CYAN}[*] Загрузка портативной версии yt-dlp...{CLR}")
    try:
        data = _with_retries(lambda: _fetch_url_bytes(YTDLP_RELEASE_URL, timeout=60))

        try:
            sums_text = _fetch_url_bytes(YTDLP_SHA256SUMS_URL, timeout=15).decode("utf-8", errors="ignore")
            expected = _extract_hash_for_file(sums_text, "yt-dlp.exe")
        except Exception:
            expected = None

        if expected:
            if not _verify_sha256(data, expected):
                raise ValueError("Контрольная сумма yt-dlp.exe не совпадает с ожидаемой — загрузка отменена")
        else:
            print(f"{YELLOW}[~] Не удалось получить контрольную сумму yt-dlp.exe, проверка пропущена.{CLR}")

        with open(YTDLP_EXE, "wb") as f:
            f.write(data)
        return YTDLP_EXE
    except Exception as e:
        print(f"{RED}[-] Ошибка загрузки yt-dlp: {e}{CLR}")
        print(f"{YELLOW}[~] Попытка использовать системный yt-dlp из PATH.{CLR}")
        log_line(f"Ошибка загрузки yt-dlp: {e}")
        return "yt-dlp"

def ensure_deno():
    """Deno требуется yt-dlp как JS-runtime для прохождения защиты YouTube."""
    if os.name != 'nt':
        return

    if os.path.exists(DENO_EXE):
        if TOOLS_DIR not in os.environ.get("PATH", ""):
            os.environ["PATH"] = TOOLS_DIR + os.pathsep + os.environ.get("PATH", "")
        return

    os.makedirs(TOOLS_DIR, exist_ok=True)
    print(f"{CYAN}[*] Загрузка Deno (JS-runtime)...{CLR}")
    try:
        zip_bytes = _with_retries(lambda: _fetch_url_bytes(DENO_RELEASE_URL, timeout=30))

        try:
            sum_text = _fetch_url_bytes(DENO_SHA256SUM_URL, timeout=15).decode("utf-8", errors="ignore")
            expected = _extract_hash_for_file(sum_text, "deno-x86_64-pc-windows-msvc.zip")
        except Exception:
            expected = None

        if expected:
            if not _verify_sha256(zip_bytes, expected):
                raise ValueError("Контрольная сумма архива Deno не совпадает с ожидаемой — установка отменена")
        else:
            print(f"{YELLOW}[~] Не удалось получить контрольную сумму Deno, проверка пропущена.{CLR}")

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            z.extract("deno.exe", TOOLS_DIR)
        os.environ["PATH"] = TOOLS_DIR + os.pathsep + os.environ.get("PATH", "")
    except Exception as e:
        print(f"{RED}[-] Ошибка загрузки Deno: {e}{CLR}")
        print(f"{YELLOW}[~] Без JS-runtime возможны ошибки 'Requested format is not available'.{CLR}")
        log_line(f"Ошибка загрузки Deno: {e}")

_UPDATE_STATE_LOCK = threading.Lock()

def load_update_state():
    try:
        with open(UPDATE_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_update_state(state):
    try:
        os.makedirs(TOOLS_DIR, exist_ok=True)
        with open(UPDATE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

def check_should_update(state, key):
    last = state.get(key, 0)
    return (time.time() - last) > UPDATE_INTERVAL_SECONDS

def update_tools(ytdlp_bin):
    with _UPDATE_STATE_LOCK:
        state = load_update_state()
        if not check_should_update(state, "ytdlp"):
            return
        state["ytdlp"] = time.time()
        save_update_state(state)

    print(f"{CYAN}[*] Проверка обновлений yt-dlp...{CLR}")
    try:
        subprocess.run([ytdlp_bin, "-U"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────
# spotdl: устанавливается синхронно и ЛЕНИВО (только при первом реальном
# использовании), чтобы не гоняться наперегонки с пользователем, который
# может выбрать Spotify-ссылку раньше, чем фоновая установка завершится.
# ──────────────────────────────────────────────────────────────────────────

_spotdl_lock = threading.Lock()
_spotdl_ready = False

def _spotdl_importable():
    try:
        return importlib.util.find_spec("spotdl") is not None
    except Exception:
        return False

def ensure_spotdl_installed():
    """Блокирующая проверка/установка spotdl. Вызывается непосредственно перед первой загрузкой со Spotify."""
    global _spotdl_ready
    with _spotdl_lock:
        if _spotdl_ready:
            return True

        if _spotdl_importable():
            _spotdl_ready = True
            return True

        print(f"{CYAN}[*] spotdl не найден, устанавливаю зависимости (первый запуск, может занять минуту)...{CLR}")
        for pkg in ("yt-dlp", "yt-dlp-ejs", "spotdl"):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-U", "--no-input", pkg],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
                )
            except Exception as e:
                print(f"{RED}[-] Ошибка установки пакета {pkg}: {e}{CLR}")
                log_line(f"Ошибка установки {pkg}: {e}")

        _spotdl_ready = _spotdl_importable()
        if _spotdl_ready:
            print(f"{GREEN}[+] spotdl готов к работе.{CLR}")
        else:
            print(f"{RED}[-] Не удалось установить spotdl. Проверьте подключение к интернету и права на запись в окружение Python.{CLR}")
        return _spotdl_ready

def update_spotdl_dependencies_background():
    """Фоновое периодическое обновление УЖЕ установленного spotdl. Не устанавливает его с нуля."""
    with _UPDATE_STATE_LOCK:
        state = load_update_state()
        if not check_should_update(state, "spotdl_deps"):
            return
        state["spotdl_deps"] = time.time()
        save_update_state(state)

    if not _spotdl_importable():
        return  # первая установка выполняется лениво и синхронно в ensure_spotdl_installed()

    print(f"{CYAN}[*] Проверка обновлений spotdl...{CLR}")
    for pkg in ("yt-dlp", "yt-dlp-ejs", "spotdl"):
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "--no-input", pkg],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45
            )
        except Exception:
            pass

# ──────────────────────────────────────────────────────────────────────────
# Параллелизм: дефолты снижены, чтобы не провоцировать троттлинг/баны
# со стороны YouTube/SoundCloud при плейлистах.
# ──────────────────────────────────────────────────────────────────────────

CONCURRENT_FRAGMENTS = int(os.environ.get("NOVADL_CONCURRENT_FRAGMENTS", "8"))
SPOTDL_THREADS = os.environ.get("NOVADL_SPOTDL_THREADS", "4")
HTTP_CHUNK_SIZE = os.environ.get("NOVADL_HTTP_CHUNK_SIZE", "10M")
PLAYLIST_WORKERS = max(1, int(os.environ.get("NOVADL_PLAYLIST_WORKERS", "2")))
ARIA2_CONNECTIONS = os.environ.get("NOVADL_ARIA2_CONNECTIONS", "8")

_ARIA2C_PATH = shutil.which("aria2c")

def ensure_aria2c_background():
    global _ARIA2C_PATH
    if os.name != 'nt' or _ARIA2C_PATH or not shutil.which("winget"):
        return
    try:
        subprocess.run(
            ["winget", "install", "--id", "aria2.aria2", "-e", "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45
        )
        _ARIA2C_PATH = shutil.which("aria2c")
    except Exception:
        pass

def get_speed_args():
    if _ARIA2C_PATH:
        return [
            "--downloader", "aria2c",
            "--downloader-args", f"aria2c:-x {ARIA2_CONNECTIONS} -s {ARIA2_CONNECTIONS} -k 1M",
        ]
    return [
        "--concurrent-fragments", str(CONCURRENT_FRAGMENTS),
        "--http-chunk-size", HTTP_CHUNK_SIZE,
    ]

# ──────────────────────────────────────────────────────────────────────────
# Cookies: файл cookies.txt в приоритете, браузер — только как фолбэк.
# Извлечение cookies из открытого Chrome может падать из-за заблокированной
# SQLite-базы — мы не можем это надёжно предсказать заранее на всех ОС,
# поэтому предупреждаем один раз до попытки и даём понятную подсказку,
# если после неудачной загрузки в логе обнаружатся характерные признаки.
# ──────────────────────────────────────────────────────────────────────────

_cookie_warning_shown = False

def get_cookies_args():
    global _cookie_warning_shown
    if os.path.exists(COOKIES_PATH):
        return ["--cookies", COOKIES_PATH]

    if not _cookie_warning_shown:
        print(f"{YELLOW}[~] Файл cookies.txt не найден ({COOKIES_PATH}). "
              f"Пробую взять cookies из Chrome автоматически.{CLR}")
        print(f"{YELLOW}[~] Если Chrome сейчас открыт, это иногда мешает чтению его базы cookies — "
              f"при ошибке закройте браузер или подготовьте свой cookies.txt (см. README).{CLR}")
        _cookie_warning_shown = True

    return ["--cookies-from-browser", "chrome"]

COOKIE_ISSUE_MARKERS = (
    "could not copy chrome cookie database",
    "could not find chrome cookies database",
    "could not find browser",
    "database is locked",
    "failed to decrypt",
    "unsupported browser",
    "permission denied",
)

def has_cookie_issue(logs):
    """Определяет, похожа ли неудача на проблему с извлечением cookies из браузера
    (например, заблокированная открытым Chrome база данных)."""
    if os.path.exists(COOKIES_PATH):
        return False
    low = " ".join(l.lower() for l in logs)
    return any(marker in low for marker in COOKIE_ISSUE_MARKERS)

def print_cookie_issue_hint():
    print(f"\n{YELLOW}[~] Похоже, не удалось прочитать cookies из Chrome — браузер может быть открыт,"
          f" а его база cookies временно заблокирована.{CLR}")
    print(f"{YELLOW}[~] Закройте Chrome и повторите попытку, либо экспортируйте cookies.txt "
          f"(расширение 'Get cookies.txt LOCALLY') и укажите путь через NOVADL_COOKIES_PATH.{CLR}")

def clean_url(url):
    url = url.strip().strip('"').strip("'")
    if "spotify.com" in url and "?" in url:
        url = url.split("?")[0]
    return url

def get_platform(url):
    url = url.strip()
    if re.search(r'(spotify\.com)', url, re.IGNORECASE): return "Spotify"
    if re.search(r'(youtube\.com|youtu\.be)', url, re.IGNORECASE): return "YouTube"
    if re.search(r'(soundcloud\.com)', url, re.IGNORECASE): return "SoundCloud"
    return None

def is_playlist_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    qs = parse_qs(parsed.query)
    if "list" in qs:
        if "v" in qs:
            return False
        return True

    # Раньше здесь был дубликат "/sets" рядом с "/sets/", из-за чего проверка
    # ничего не выигрывала от второго варианта. Приведено к явному списку
    # путей-коллекций: /sets/, /likes, /reposts для SoundCloud и /playlist/, /album/ для Spotify.
    path = parsed.path.lower()
    return any(seg in path for seg in ("/sets/", "/likes", "/reposts", "/playlist/", "/album/"))

def render_progress_bar(percentage, status_text, speed_text=""):
    width = 30
    filled_length = int(width * percentage // 100)
    bar = '█' * filled_length + '░' * (width - filled_length)
    speed_part = f" {WHITE}{speed_text}{CLR}" if speed_text else ""
    sys.stdout.write(f"\r{CYAN}[*] {status_text} [{GREEN}{bar}{CYAN}] {percentage:>5.1f}%{speed_part}   ")
    sys.stdout.flush()

AUDIO_VIDEO_EXTENSIONS = (".mp3", ".wav", ".mp4", ".m4a", ".flac", ".webm", ".ogg", ".opus", ".mkv", ".weba")
INCOMPLETE_EXTENSIONS = (".part", ".ytdl", ".temp", ".ffmpeg", ".crdownload")

def get_media_files_snapshot(path):
    try:
        return {
            f for f in os.listdir(path)
            if f.lower().endswith(AUDIO_VIDEO_EXTENSIONS) and not f.lower().endswith(INCOMPLETE_EXTENSIONS)
        }
    except Exception:
        return set()

def execute_and_stream_output(cmd, platform):
    files_before = get_media_files_snapshot(SAVE_PATH)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=SAVE_PATH,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            errors='ignore',
            bufsize=1
        )
    except FileNotFoundError:
        raise
    except Exception as e:
        print(f"\n{RED}[-] Не удалось запустить процесс загрузки: {e}{CLR}")
        log_line(f"Popen error: {e}")
        return False, False, True

    current_track_num = 0
    has_errors = False
    error_logs = []

    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break

        line_str = line.strip()
        if line_str:
            error_logs.append(line_str)
            if len(error_logs) > 15:
                error_logs.pop(0)

            if "ERROR:" in line_str or "Failed" in line_str:
                has_errors = True

        if "[download]" in line_str and "Downloading item" in line_str:
            match_item = re.search(r'Downloading item (\d+) of (\d+)', line_str)
            if match_item:
                current_track_num = match_item.group(1)
                total_tracks = match_item.group(2)
                print(f"\n\n{WHITE}{BOLD}[Плейлист] Обработка трека {current_track_num} из {total_tracks}...{CLR}")

        if platform in ["YouTube", "SoundCloud"]:
            if "[download]" in line_str and "%" in line_str and "ETA" in line_str:
                match = re.search(r'(\d+\.\d+)%', line_str)
                if match:
                    pct = float(match.group(1))
                    speed_match = re.search(r'at\s+([\d.]+\S+/s)', line_str)
                    speed_text = speed_match.group(1) if speed_match else ""
                    render_progress_bar(pct, f"Загрузка #{current_track_num if current_track_num else 1} ", speed_text)
            elif "[ExtractAudio]" in line_str:
                print(f"\n{YELLOW}[*] Извлечение аудиопотока...{CLR}")
            elif "[ThumbnailsConvertor]" in line_str or "embed-thumbnail" in line_str.lower():
                print(f"{YELLOW}[*] Обработка обложки...{CLR}")
            elif "[Metadata]" in line_str or "embed-metadata" in line_str.lower():
                print(f"{YELLOW}[*] Сохранение метаданных...{CLR}")

        elif platform == "Spotify":
            if "Fetching" in line_str or "Searching" in line_str or "Found" in line_str:
                print(f"\n{YELLOW}[*] Поиск трека в базе данных...{CLR}")
            elif "Downloading" in line_str or "Downloaded" in line_str:
                match = re.search(r'(\d+)%', line_str)
                pct = float(match.group(1)) if match else 100.0
                render_progress_bar(pct, "Загрузка аудио")
            elif "Converting" in line_str or "Processing" in line_str:
                print(f"\n{YELLOW}[*] Применение тегов и финализация...{CLR}")

    process.wait()

    format_not_available = any("Requested format is not available" in l for l in error_logs)

    files_after = get_media_files_snapshot(SAVE_PATH)
    new_files = files_after - files_before
    already_had_file = any(
        ("already exists" in l.lower()) or ("skipping" in l.lower()) or ("already downloaded" in l.lower())
        for l in error_logs
    )
    disk_confirmed = bool(new_files) or already_had_file

    for l in error_logs:
        log_line(l)

    if not disk_confirmed:
        print(f"\n\n{RED}[-] Файлы не сохранены. Лог утилиты:{CLR}")
        for err_line in error_logs:
            if "ETA" not in err_line:
                print(f"{RED} > {err_line}{CLR}")
        if has_cookie_issue(error_logs):
            print_cookie_issue_hint()
        return False, format_not_available, has_errors

    if new_files:
        print(f"\n{GREEN}[+] Успешно сохранено файлов: {len(new_files)}{CLR}")

    return True, format_not_available, has_errors

def build_common_ytdlp_args(retry=False):
    """Общие аргументы yt-dlp (метаданные, ffmpeg, скорость, cookies), без формата/шаблона/URL."""
    ffmpeg_target = FFMPEG_DIR if FFMPEG_DIR else "ffmpeg"

    # Использование резервных клиентов при повторной попытке загрузки
    player_clients = "tv,web_safari" if retry else "ios,mweb,tv"

    args = [
        "--ffmpeg-location", ffmpeg_target,
        "--ignore-errors",
        "--no-warnings",
        "--embed-metadata",
        "--parse-metadata", "%(artist,uploader)s:artist",
        "--parse-metadata", "%(artist,uploader)s:album_artist",
        "--parse-metadata", "%(album)s:album",
        "--windows-filenames",
        "--extractor-args", f"youtube:player_client={player_clients}",
        "--remote-components", "ejs:github",
    ]
    args.extend(get_speed_args())
    args.extend(get_cookies_args())
    return args

def _format_specific_args(file_type, retry):
    """Возвращает (аргументы формата/кодека, дополнительные постобработочные аргументы)."""
    if file_type == "mp3":
        fmt = "best" if retry else "bestaudio[abr>0]/bestaudio/best"
        return (
            ["-f", fmt, "-x", "--audio-format", "mp3", "--audio-quality", "320K"],
            ["--embed-thumbnail", "--convert-thumbnails", "jpg"],
        )
    elif file_type == "wav":
        fmt = "best" if retry else "bestaudio[abr>0]/bestaudio/best"
        return (["-f", fmt, "-x", "--audio-format", "wav"], [])
    else:
        fmt = "best" if retry else "bv*+ba/b/best"
        return (
            ["-f", fmt, "--merge-output-format", "mp4"],
            ["--embed-thumbnail", "--format-sort", "res,fps,hdr:12,vcodec:av01:vp9:h264,br,size"],
        )

def build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, retry=False):
    output_template = "%(playlist_index)02d - %(title)s.%(ext)s" if is_playlist else "%(title)s.%(ext)s"
    pre_fmt, post_fmt = _format_specific_args(file_type, retry)

    cmd = [ytdlp_bin] + pre_fmt + ["-o", output_template] + build_common_ytdlp_args(retry) + post_fmt

    if not is_playlist:
        cmd.append("--no-playlist")

    cmd.append(url)
    return cmd

def build_ytdlp_command_multi(ytdlp_bin, urls, file_type, retry=False):
    """Команда для загрузки уже готового списка КОНКРЕТНЫХ ссылок (не плейлиста целиком).
    Используется параллельными воркерами после однократного извлечения списка плейлиста
    функцией extract_playlist_video_urls, чтобы каждый поток не парсил страницу плейлиста заново."""
    output_template = "%(title)s.%(ext)s"
    pre_fmt, post_fmt = _format_specific_args(file_type, retry)

    cmd = [ytdlp_bin] + pre_fmt + ["-o", output_template] + build_common_ytdlp_args(retry) + post_fmt
    cmd.append("--no-playlist")
    cmd.extend(urls)
    return cmd

def extract_playlist_video_urls(ytdlp_bin, url):
    """Извлекает список прямых ссылок на все элементы плейлиста ОДНИМ запросом (--flat-playlist),
    чтобы параллельные воркеры не запрашивали и не парсили страницу плейлиста заново каждый по
    отдельности — это и стабильнее, и заметно снижает число запросов к сайту (anti-ban)."""
    cmd = [ytdlp_bin, "--flat-playlist", "--print", "webpage_url", "--no-warnings", "--ignore-errors"]
    cmd.extend(get_cookies_args())
    cmd.append(url)
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, encoding='utf-8', errors='ignore', timeout=90
        )
        urls = [ln.strip() for ln in result.stdout.splitlines() if ln.strip().startswith("http")]
        return urls
    except Exception as e:
        log_line(f"Не удалось получить список плейлиста одним запросом: {e}")
        return []

def execute_playlist_worker(cmd, worker_id, print_lock, shared_error_logs):
    try:
        try:
            process = subprocess.Popen(
                cmd,
                cwd=SAVE_PATH,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='ignore',
                bufsize=1
            )
        except Exception as e:
            with print_lock:
                shared_error_logs.append(f"[-] Поток {worker_id} не смог запуститься: {e}")
            return False, True

        last_bucket = -1
        local_logs = []
        format_not_available = False
        has_error = False

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            line_str = line.strip()
            if not line_str:
                continue

            local_logs.append(line_str)
            if len(local_logs) > 15:
                local_logs.pop(0)

            if "Requested format is not available" in line_str:
                format_not_available = True

            if "ERROR:" in line_str or "Failed" in line_str:
                has_error = True

            if "[download]" in line_str and "%" in line_str and "ETA" in line_str:
                match = re.search(r'(\d+\.\d+)%', line_str)
                if match:
                    pct = float(match.group(1))
                    bucket = int(pct // 20) * 20
                    if bucket != last_bucket:
                        last_bucket = bucket
                        speed_match = re.search(r'at\s+([\d.]+\S+/s)', line_str)
                        speed_text = f" ({speed_match.group(1)})" if speed_match else ""
                        with print_lock:
                            print(f"{CYAN}[Поток {worker_id}]{CLR} {GREEN}{pct:>5.1f}%{CLR}{speed_text}")

        process.wait()
        with print_lock:
            shared_error_logs.extend(local_logs)
        return format_not_available, has_error

    except Exception as e:
        with print_lock:
            shared_error_logs.append(f"[-] Ошибка потока {worker_id}: {e}")
        return False, True

def process_playlist_parallel(ytdlp_bin, url, file_type, platform, retry=False):
    print(f"{CYAN}[*] Получение списка элементов плейлиста (один запрос)...{CLR}")
    entries = extract_playlist_video_urls(ytdlp_bin, url)

    files_before = get_media_files_snapshot(SAVE_PATH)
    print_lock = threading.Lock()
    shared_error_logs = []

    if entries:
        # Список получен один раз — распределяем готовые ссылки между воркерами.
        # Так каждый поток скачивает свою часть напрямую, не парся плейлист заново.
        workers = max(1, min(PLAYLIST_WORKERS, len(entries)))
        print(f"{CYAN}[*] Найдено элементов: {len(entries)}. Загрузка в {workers} поток(а/ов)...{CLR}\n")
        chunks = [entries[i::workers] for i in range(workers)]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for i, chunk in enumerate(chunks):
                if not chunk:
                    continue
                cmd = build_ytdlp_command_multi(ytdlp_bin, chunk, file_type, retry=retry)
                futures.append(pool.submit(execute_playlist_worker, cmd, i + 1, print_lock, shared_error_logs))
            results = [f.result() for f in futures]
    else:
        # Резервный вариант: не удалось получить список заранее (например, приватный
        # плейлист или сбой сети) — используем встроенное распределение yt-dlp
        # по --playlist-items, как раньше.
        workers = PLAYLIST_WORKERS
        print(f"{YELLOW}[~] Не удалось получить список плейлиста заранее, использую резервный режим "
              f"({workers} потоков)...{CLR}\n")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for i in range(workers):
                cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist=True, retry=retry)
                cmd.extend(["--playlist-items", f"{i + 1}::{workers}"])
                futures.append(pool.submit(execute_playlist_worker, cmd, i + 1, print_lock, shared_error_logs))
            results = [f.result() for f in futures]

    format_not_available = any(r[0] for r in results) if results else False
    has_errors = any(r[1] for r in results) if results else True

    files_after = get_media_files_snapshot(SAVE_PATH)
    new_files = files_after - files_before
    already_had_file = any(
        ("already exists" in l.lower()) or ("skipping" in l.lower()) or ("already downloaded" in l.lower())
        for l in shared_error_logs
    )
    disk_confirmed = bool(new_files) or already_had_file

    for l in shared_error_logs:
        log_line(l)

    if new_files:
        print(f"\n{GREEN}[+] Успешно сохранено файлов: {len(new_files)}{CLR}")
    elif not disk_confirmed:
        print(f"\n{RED}[-] Ни один поток не сохранил файлы.{CLR}")
        for err_line in shared_error_logs[-15:]:
            if "ETA" not in err_line:
                print(f"{RED} > {err_line}{CLR}")
        if has_cookie_issue(shared_error_logs):
            print_cookie_issue_hint()

    return disk_confirmed, format_not_available, has_errors

def start_download_process(url, file_type, ytdlp_bin):
    url = clean_url(url)
    platform = get_platform(url)
    if not platform:
        print(f"\n{RED}[-] Ошибка: Платформа не поддерживается.{CLR}")
        return

    print(f"\n{GREEN}[+] Источник: {BOLD}{platform}{CLR} | {GREEN}Формат: {BOLD}{file_type.upper()}{CLR}")
    print(f"{CYAN}[*] Запуск обработки...{CLR}\n")

    is_playlist = is_playlist_url(url)
    ffmpeg_exe = os.path.join(FFMPEG_DIR, "ffmpeg.exe") if FFMPEG_DIR else "ffmpeg"

    if platform == "Spotify":
        if not ensure_spotdl_installed():
            print(f"\n{RED}[-] spotdl недоступен, загрузка отменена.{CLR}")
            return

        if file_type == "mp4":
            file_type = "mp3"
        cmd = [
            sys.executable, "-m", "spotdl", "download", url,
            "--format", file_type,
            "--bitrate", "320k",
            "--audio", "youtube-music", "youtube",
            "--threads", SPOTDL_THREADS,
            "--lyrics", "genius", "musixmatch",
            "--ffmpeg", ffmpeg_exe
        ]
        if os.path.exists(COOKIES_PATH):
            cmd.extend(["--cookie-file", COOKIES_PATH])

        try:
            success, _, has_errors = execute_and_stream_output(cmd, platform)
        except FileNotFoundError:
            print(f"\n{RED}[-] Модуль spotdl не найден.{CLR}")
            success = False
            has_errors = True

    else:
        if is_playlist and PLAYLIST_WORKERS > 1:
            success, format_not_available, has_errors = process_playlist_parallel(ytdlp_bin, url, file_type, platform, retry=False)
        else:
            cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, retry=False)
            try:
                success, format_not_available, has_errors = execute_and_stream_output(cmd, platform)
            except FileNotFoundError:
                print(f"\n{RED}[-] Утилита yt-dlp не найдена.{CLR}")
                success = False
                format_not_available = False
                has_errors = True

        if not success and format_not_available:
            print(f"\n{YELLOW}[~] Основные клиенты недоступны. Запуск резервного варианта...{CLR}\n")
            if is_playlist and PLAYLIST_WORKERS > 1:
                success, _, has_errors = process_playlist_parallel(ytdlp_bin, url, file_type, platform, retry=True)
            else:
                retry_cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, retry=True)
                try:
                    success, _, has_errors = execute_and_stream_output(retry_cmd, platform)
                except FileNotFoundError:
                    print(f"\n{RED}[-] Утилита yt-dlp не найдена.{CLR}")
                    success = False
                    has_errors = True

    print(f"\n{CYAN}──────────────────────────────────────────────────{CLR}")
    if success:
        if is_playlist and has_errors:
            print(f"{YELLOW}{BOLD}[~] Загрузка завершена (Частичный успех: некоторые файлы пропущены){CLR}")
        else:
            print(f"{GREEN}{BOLD}[+] Загрузка успешно завершена{CLR}")
        print(f"{WHITE}    Директория: {SAVE_PATH}{CLR}")
    else:
        print(f"{RED}[-] Загрузка прервана из-за ошибки.{CLR}")
        if platform != "Spotify" and not os.path.exists(COOKIES_PATH):
            print(f"{YELLOW}[~] Если ошибка связана с авторизацией — попробуйте закрыть Chrome "
                  f"или указать готовый cookies.txt через NOVADL_COOKIES_PATH.{CLR}")
    print(f"{CYAN}──────────────────────────────────────────────────{CLR}")

def read_menu_choice():
    """Считывает выбор пункта меню (1-3). На Windows — посимвольно с видимой обратной связью
    на неверный ввод, на прочих платформах — через input() с валидацией и повтором запроса."""
    valid = ('1', '2', '3')

    if os.name == 'nt':
        while True:
            ch = msvcrt.getch()
            if ch in (b'\x03',):
                raise KeyboardInterrupt
            try:
                ch_str = ch.decode('utf-8')
            except Exception:
                continue
            if ch_str in valid:
                print(ch_str)  # эхо выбранной цифры, чтобы было видно, что нажатие принято
                return ch_str
            if ch_str in ('\r', '\n'):
                continue
            sys.stdout.write(f"\r{YELLOW}[~] Нажмите 1, 2 или 3...{CLR}   ")
            sys.stdout.flush()
    else:
        while True:
            choice = input(f"{WHITE}Выбор (1-3):{CLR} ").strip()
            if choice in valid:
                return choice
            print(f"{YELLOW}[~] Нужно ввести 1, 2 или 3.{CLR}")

def main():
    ensure_save_directory()

    with ThreadPoolExecutor(max_workers=3) as pool:
        ytdlp_future = pool.submit(ensure_ytdlp)
        deno_future = pool.submit(ensure_deno)
        pool.submit(ensure_ffmpeg)
        ytdlp_bin = ytdlp_future.result()
        deno_future.result()

    threading.Thread(target=ensure_aria2c_background, daemon=True).start()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(update_tools, ytdlp_bin)
        pool.submit(update_spotdl_dependencies_background)

    while True:
        clear_screen()
        print(f"{CYAN}NovaDL  |  v1.1.0{CLR}")
        print(f"{CYAN}──────────────────────────────────────────────────{CLR}")
        print(f"{WHITE}• Сохранение:  {YELLOW}{SAVE_PATH}{CLR}")
        print(f"{WHITE}• Файл куки:   {GREEN}{'Активен' if os.path.exists(COOKIES_PATH) else 'Не найден (используется браузер)'}{CLR}")
        print(f"{WHITE}• FFmpeg:      {GREEN if FFMPEG_DIR else RED}{FFMPEG_DIR if FFMPEG_DIR else 'Не найден'}{CLR}")
        print(f"{CYAN}──────────────────────────────────────────────────{CLR}")

        url = input(f"{WHITE}URL (0 - настройки, Enter - выход):{CLR} ").strip()
        if not url: break

        if url == '0':
            prompt_change_save_directory()
            input(f"\n{WHITE}Нажмите Enter для продолжения...{CLR}")
            continue

        print(f"\n{WHITE}Выберите формат:{CLR}")
        print(f" {GREEN}1.{CLR} MP3  {WHITE}(Аудио 320kbps + обложка + теги){CLR}")
        print(f" {GREEN}2.{CLR} WAV  {WHITE}(Lossless аудио без сжатия){CLR}")
        print(f" {GREEN}3.{CLR} MP4  {WHITE}(Видео в максимальном качестве){CLR}")
        print(f"{CYAN}──────────────────────────────────────────────────{CLR}")

        choice = read_menu_choice()

        file_type = "mp3"
        if choice == '2': file_type = "wav"
        elif choice == '3': file_type = "mp4"

        try:
            start_download_process(url, file_type, ytdlp_bin)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"\n{RED}[-] Системная ошибка: {e}{CLR}")
            log_line(f"Системная ошибка: {e}")

        input(f"\n{WHITE}Нажмите Enter для продолжения...{CLR}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

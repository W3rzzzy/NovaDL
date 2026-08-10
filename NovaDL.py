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
CURRENT_LANG = _config.get("language", "ru")
if CURRENT_LANG not in ("ru", "en"):
    CURRENT_LANG = "ru"

USER_HOME = os.path.expanduser("~")
SAVE_PATH = os.environ.get("NOVADL_SAVE_PATH") or _config.get("save_path") or os.path.join(USER_HOME, "Downloads", "NovaDL")

# ──────────────────────────────────────────────────────────────────────────
# УМНЫЙ ПОИСК COOKIES.TXT
# Приоритет: NOVADL_COOKIES_PATH > SCRIPT_DIR/cookies.txt > Downloads/cookies.txt
# ──────────────────────────────────────────────────────────────────────────
local_cookies = os.path.join(SCRIPT_DIR, "cookies.txt")
downloads_cookies = os.path.join(USER_HOME, "Downloads", "cookies.txt")
COOKIES_PATH = os.environ.get("NOVADL_COOKIES_PATH") or (local_cookies if os.path.exists(local_cookies) else downloads_cookies)

CLR = "\033[0m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
WHITE = "\033[97m"
BOLD = "\033[1m"

# ──────────────────────────────────────────────────────────────────────────
# ЛОКАЛИЗАЦИЯ (i18n)
# ──────────────────────────────────────────────────────────────────────────
TRANSLATIONS = {
    "ru": {
        "curr_dir": "\n{WHITE}Текущая директория:{CLR} {YELLOW}{save_path}{CLR}",
        "new_dir_prompt": "{WHITE}Новая директория (Enter - отмена):{CLR} ",
        "op_cancelled": "{YELLOW}[~] Операция отменена.{CLR}",
        "dir_error": "{RED}[-] Не удалось использовать данную директорию: {e}{CLR}",
        "dir_env_warn": "{YELLOW}[~] Внимание: переменная окружения NOVADL_SAVE_PATH переопределит эту настройку при следующем запуске.{CLR}",
        "dir_saved": "{GREEN}[+] Директория сохранена:{CLR} {WHITE}{new_path}{CLR}",
        "dir_session_only": "{YELLOW}[~] Директория изменена только для текущей сессии (сбой сохранения конфига).{CLR}",
        "ffmpeg_not_found": "{RED}[-] FFmpeg не найден в системе.{CLR}",
        "ffmpeg_manual": "{YELLOW}[~] Установите FFmpeg вручную (https://ffmpeg.org/download.html) или укажите путь через переменную NOVADL_FFMPEG_DIR.{CLR}",
        "ffmpeg_winget": "{CYAN}[*] FFmpeg не найден, устанавливаю через winget...{CLR}",
        "ffmpeg_winget_err": "{RED}[-] Не удалось установить FFmpeg автоматически: {e}{CLR}",
        "ffmpeg_installed": "{GREEN}[+] FFmpeg установлен: {path}{CLR}",
        "ffmpeg_still_not_found": "{RED}[-] FFmpeg всё ещё не найден после установки. Проверьте PATH или переменную NOVADL_FFMPEG_DIR.{CLR}",
        "ytdlp_downloading": "{CYAN}[*] Загрузка портативной версии yt-dlp...{CLR}",
        "hash_skip": "{YELLOW}[~] Не удалось получить контрольную сумму {file}, проверка пропущена.{CLR}",
        "ytdlp_err": "{RED}[-] Ошибка загрузки yt-dlp: {e}{CLR}",
        "ytdlp_fallback": "{YELLOW}[~] Попытка использовать системный yt-dlp из PATH.{CLR}",
        "deno_downloading": "{CYAN}[*] Загрузка Deno (JS-runtime)...{CLR}",
        "deno_err": "{RED}[-] Ошибка загрузки Deno: {e}{CLR}",
        "deno_warn": "{YELLOW}[~] Без JS-runtime возможны ошибки 'Requested format is not available'.{CLR}",
        "chk_ytdlp": "{CYAN}[*] Проверка обновлений yt-dlp...{CLR}",
        "chk_spotdl": "{CYAN}[*] Проверка обновлений spotdl...{CLR}",
        "spotdl_deps": "{CYAN}[*] spotdl не найден, устанавливаю зависимости (первый запуск, может занять минуту)...{CLR}",
        "spotdl_err_pkg": "{RED}[-] Ошибка установки пакета {pkg}: {e}{CLR}",
        "spotdl_ready": "{GREEN}[+] spotdl готов к работе.{CLR}",
        "spotdl_fail": "{RED}[-] Не удалось установить spotdl. Проверьте подключение к интернету и права на запись в окружение Python.{CLR}",
        "cookie_not_found": "{YELLOW}[~] Файл cookies.txt не найден ({path}). Пробую взять cookies из Chrome автоматически.{CLR}",
        "cookie_chrome_warn": "{YELLOW}[~] Если Chrome сейчас открыт, это иногда мешает чтению его базы cookies — при ошибке закройте браузер или подготовьте свой cookies.txt (см. README).{CLR}",
        "cookie_issue_hint1": "\n{YELLOW}[~] Похоже, не удалось прочитать cookies из Chrome — браузер может быть открыт, а его база cookies временно заблокирована.{CLR}",
        "cookie_issue_hint2": "{YELLOW}[~] Закройте Chrome и повторите попытку, либо экспортируйте cookies.txt (расширение 'Get cookies.txt LOCALLY') и укажите путь через NOVADL_COOKIES_PATH.{CLR}",
        "popen_err": "\n{RED}[-] Не удалось запустить процесс загрузки: {e}{CLR}",
        "playlist_track": "\n\n{WHITE}{BOLD}[Плейлист] Обработка трека {curr} из {total}...{CLR}",
        "downloading_num": "Загрузка #{num} ",
        "extract_audio": "\n{YELLOW}[*] Извлечение аудиопотока...{CLR}",
        "process_cover": "{YELLOW}[*] Обработка обложки...{CLR}",
        "save_meta": "{YELLOW}[*] Сохранение метаданных...{CLR}",
        "fetching_db": "\n{YELLOW}[*] Поиск трека в базе данных...{CLR}",
        "download_audio": "Загрузка аудио",
        "applying_tags": "\n{YELLOW}[*] Применение тегов и финализация...{CLR}",
        "files_not_saved": "\n\n{RED}[-] Файлы не сохранены. Лог утилиты:{CLR}",
        "files_saved": "\n{GREEN}[+] Успешно сохранено файлов: {count}{CLR}",
        "playlist_fetch": "{CYAN}[*] Получение списка элементов плейлиста (один запрос)...{CLR}",
        "playlist_found": "{CYAN}[*] Найдено элементов: {count}. Загрузка в {workers} поток(а/ов)...{CLR}\n",
        "playlist_fallback": "{YELLOW}[~] Не удалось получить список плейлиста заранее, использую резервный режим ({workers} потоков)...{CLR}\n",
        "thread_err": "[-] Ошибка потока {id}: {e}",
        "thread_start_err": "[-] Поток {id} не смог запуститься: {e}",
        "thread_progress": "{CYAN}[Поток {id}]{CLR} {GREEN}{pct:>5.1f}%{CLR}{speed}",
        "no_files_saved": "\n{RED}[-] Ни один поток не сохранил файлы.{CLR}",
        "unsupported_platform": "\n{RED}[-] Ошибка: Платформа не поддерживается.{CLR}",
        "source": "\n{GREEN}[+] Источник: {BOLD}{platform}{CLR} | {GREEN}Формат: {BOLD}{fmt}{CLR}",
        "starting": "{CYAN}[*] Запуск обработки...{CLR}\n",
        "spotdl_not_avail": "\n{RED}[-] spotdl недоступен, загрузка отменена.{CLR}",
        "spotdl_not_found": "\n{RED}[-] Модуль spotdl не найден.{CLR}",
        "ytdlp_not_found": "\n{RED}[-] Утилита yt-dlp не найдена.{CLR}",
        "fallback_start": "\n{YELLOW}[~] Основные клиенты недоступны. Запуск резервного варианта...{CLR}\n",
        "separator": "{CYAN}──────────────────────────────────────────────────{CLR}",
        "partial_success": "{YELLOW}{BOLD}[~] Загрузка завершена (Частичный успех: некоторые файлы пропущены){CLR}",
        "success": "{GREEN}{BOLD}[+] Загрузка успешно завершена{CLR}",
        "saved_dir": "{WHITE}    Директория: {path}{CLR}",
        "aborted": "{RED}[-] Загрузка прервана из-за ошибки.{CLR}",
        "aborted_cookie_hint": "{YELLOW}[~] Если ошибка связана с авторизацией — попробуйте закрыть Chrome или указать готовый cookies.txt через NOVADL_COOKIES_PATH.{CLR}",
        "input_1_2_3": "\r{YELLOW}[~] Нажмите 1, 2 или 3...{CLR}   ",
        "input_1_2_3_unix": "{WHITE}Выбор (1-3):{CLR} ",
        "input_1_2_3_warn": "{YELLOW}[~] Нужно ввести 1, 2 или 3.{CLR}",
        "main_title": "{CYAN}NovaDL  |  v1.2.0{CLR}",
        "main_save": "{WHITE}• Сохранение:  {YELLOW}{path}{CLR}",
        "main_cookie": "{WHITE}• Файл куки:   {color}{status}{CLR}",
        "cookie_active": "Активен",
        "cookie_browser": "Не найден (используется браузер)",
        "main_ffmpeg": "{WHITE}• FFmpeg:      {color}{status}{CLR}",
        "ffmpeg_not_found_status": "Не найден",
        "main_lang": "{WHITE}• Язык (Lang): {GREEN}Русский (RU){CLR}",
        "url_prompt": "{WHITE}URL (0 - настройки, Enter - выход):{CLR} ",
        "press_enter": "\n{WHITE}Нажмите Enter для продолжения...{CLR}",
        "choose_format": "\n{WHITE}Выберите формат:{CLR}",
        "fmt_mp3": " {GREEN}1.{CLR} MP3  {WHITE}(Аудио 320kbps + обложка + теги){CLR}",
        "fmt_wav": " {GREEN}2.{CLR} WAV  {WHITE}(Lossless аудио без сжатия){CLR}",
        "fmt_mp4": " {GREEN}3.{CLR} MP4  {WHITE}(Видео в максимальном качестве){CLR}",
        "sys_err": "\n{RED}[-] Системная ошибка: {e}{CLR}",
        "settings_title": "\n{WHITE}НАСТРОЙКИ (SETTINGS):{CLR}",
        "settings_opt1": " {GREEN}1.{CLR} Изменить директорию сохранения (Change save path)",
        "settings_opt2": " {GREEN}2.{CLR} Изменить язык (Change language)",
        "settings_opt3": " {GREEN}3.{CLR} Назад (Back)",
        "settings_prompt": "{WHITE}Выбор / Choice (1-3):{CLR} "
    },
    "en": {
        "curr_dir": "\n{WHITE}Current directory:{CLR} {YELLOW}{save_path}{CLR}",
        "new_dir_prompt": "{WHITE}New directory (Enter to cancel):{CLR} ",
        "op_cancelled": "{YELLOW}[~] Operation cancelled.{CLR}",
        "dir_error": "{RED}[-] Failed to use this directory: {e}{CLR}",
        "dir_env_warn": "{YELLOW}[~] Warning: The NOVADL_SAVE_PATH environment variable will override this on next startup.{CLR}",
        "dir_saved": "{GREEN}[+] Directory saved:{CLR} {WHITE}{new_path}{CLR}",
        "dir_session_only": "{YELLOW}[~] Directory changed for this session only (failed to save config).{CLR}",
        "ffmpeg_not_found": "{RED}[-] FFmpeg not found on the system.{CLR}",
        "ffmpeg_manual": "{YELLOW}[~] Install FFmpeg manually (https://ffmpeg.org/download.html) or set NOVADL_FFMPEG_DIR.{CLR}",
        "ffmpeg_winget": "{CYAN}[*] FFmpeg not found, installing via winget...{CLR}",
        "ffmpeg_winget_err": "{RED}[-] Failed to install FFmpeg automatically: {e}{CLR}",
        "ffmpeg_installed": "{GREEN}[+] FFmpeg installed: {path}{CLR}",
        "ffmpeg_still_not_found": "{RED}[-] FFmpeg still not found after installation. Check PATH or NOVADL_FFMPEG_DIR.{CLR}",
        "ytdlp_downloading": "{CYAN}[*] Downloading portable yt-dlp...{CLR}",
        "hash_skip": "{YELLOW}[~] Failed to fetch checksum for {file}, verification skipped.{CLR}",
        "ytdlp_err": "{RED}[-] yt-dlp download error: {e}{CLR}",
        "ytdlp_fallback": "{YELLOW}[~] Attempting to use system yt-dlp from PATH.{CLR}",
        "deno_downloading": "{CYAN}[*] Downloading Deno (JS-runtime)...{CLR}",
        "deno_err": "{RED}[-] Deno download error: {e}{CLR}",
        "deno_warn": "{YELLOW}[~] Without JS-runtime, 'Requested format is not available' errors may occur.{CLR}",
        "chk_ytdlp": "{CYAN}[*] Checking for yt-dlp updates...{CLR}",
        "chk_spotdl": "{CYAN}[*] Checking for spotdl updates...{CLR}",
        "spotdl_deps": "{CYAN}[*] spotdl not found, installing dependencies (first run, may take a minute)...{CLR}",
        "spotdl_err_pkg": "{RED}[-] Failed to install package {pkg}: {e}{CLR}",
        "spotdl_ready": "{GREEN}[+] spotdl is ready to use.{CLR}",
        "spotdl_fail": "{RED}[-] Failed to install spotdl. Check your internet connection and Python environment permissions.{CLR}",
        "cookie_not_found": "{YELLOW}[~] cookies.txt not found ({path}). Attempting to extract cookies from Chrome.{CLR}",
        "cookie_chrome_warn": "{YELLOW}[~] If Chrome is currently open, it may block access to its cookie database. Close it if an error occurs, or prepare a cookies.txt file.{CLR}",
        "cookie_issue_hint1": "\n{YELLOW}[~] It seems cookie extraction from Chrome failed. The browser might be open and locking the database.{CLR}",
        "cookie_issue_hint2": "{YELLOW}[~] Close Chrome and try again, or export cookies.txt (extension 'Get cookies.txt LOCALLY') and set NOVADL_COOKIES_PATH.{CLR}",
        "popen_err": "\n{RED}[-] Failed to start download process: {e}{CLR}",
        "playlist_track": "\n\n{WHITE}{BOLD}[Playlist] Processing track {curr} of {total}...{CLR}",
        "downloading_num": "Downloading #{num} ",
        "extract_audio": "\n{YELLOW}[*] Extracting audio stream...{CLR}",
        "process_cover": "{YELLOW}[*] Processing cover art...{CLR}",
        "save_meta": "{YELLOW}[*] Saving metadata...{CLR}",
        "fetching_db": "\n{YELLOW}[*] Searching for track in database...{CLR}",
        "download_audio": "Downloading audio",
        "applying_tags": "\n{YELLOW}[*] Applying tags and finalizing...{CLR}",
        "files_not_saved": "\n\n{RED}[-] Files not saved. Utility log:{CLR}",
        "files_saved": "\n{GREEN}[+] Successfully saved files: {count}{CLR}",
        "playlist_fetch": "{CYAN}[*] Fetching playlist items (single request)...{CLR}",
        "playlist_found": "{CYAN}[*] Found {count} items. Downloading with {workers} thread(s)...{CLR}\n",
        "playlist_fallback": "{YELLOW}[~] Failed to pre-fetch playlist, using fallback mode ({workers} threads)...{CLR}\n",
        "thread_err": "[-] Thread {id} error: {e}",
        "thread_start_err": "[-] Thread {id} failed to start: {e}",
        "thread_progress": "{CYAN}[Thread {id}]{CLR} {GREEN}{pct:>5.1f}%{CLR}{speed}",
        "no_files_saved": "\n{RED}[-] No threads saved any files.{CLR}",
        "unsupported_platform": "\n{RED}[-] Error: Platform not supported.{CLR}",
        "source": "\n{GREEN}[+] Source: {BOLD}{platform}{CLR} | {GREEN}Format: {BOLD}{fmt}{CLR}",
        "starting": "{CYAN}[*] Starting process...{CLR}\n",
        "spotdl_not_avail": "\n{RED}[-] spotdl is unavailable, download aborted.{CLR}",
        "spotdl_not_found": "\n{RED}[-] spotdl module not found.{CLR}",
        "ytdlp_not_found": "\n{RED}[-] yt-dlp utility not found.{CLR}",
        "fallback_start": "\n{YELLOW}[~] Main clients unavailable. Starting fallback variant...{CLR}\n",
        "separator": "{CYAN}──────────────────────────────────────────────────{CLR}",
        "partial_success": "{YELLOW}{BOLD}[~] Download finished (Partial success: some files skipped){CLR}",
        "success": "{GREEN}{BOLD}[+] Download completed successfully{CLR}",
        "saved_dir": "{WHITE}    Directory: {path}{CLR}",
        "aborted": "{RED}[-] Download aborted due to an error.{CLR}",
        "aborted_cookie_hint": "{YELLOW}[~] If the error is auth-related — try closing Chrome or providing a cookies.txt file via NOVADL_COOKIES_PATH.{CLR}",
        "input_1_2_3": "\r{YELLOW}[~] Press 1, 2, or 3...{CLR}   ",
        "input_1_2_3_unix": "{WHITE}Choice (1-3):{CLR} ",
        "input_1_2_3_warn": "{YELLOW}[~] Please enter 1, 2, or 3.{CLR}",
        "main_title": "{CYAN}NovaDL  |  v1.2.0{CLR}",
        "main_save": "{WHITE}• Save path:   {YELLOW}{path}{CLR}",
        "main_cookie": "{WHITE}• Cookie file: {color}{status}{CLR}",
        "cookie_active": "Active",
        "cookie_browser": "Not found (using browser)",
        "main_ffmpeg": "{WHITE}• FFmpeg:      {color}{status}{CLR}",
        "ffmpeg_not_found_status": "Not found",
        "main_lang": "{WHITE}• Language:    {GREEN}English (EN){CLR}",
        "url_prompt": "{WHITE}URL (0 - settings, Enter - exit):{CLR} ",
        "press_enter": "\n{WHITE}Press Enter to continue...{CLR}",
        "choose_format": "\n{WHITE}Choose format:{CLR}",
        "fmt_mp3": " {GREEN}1.{CLR} MP3  {WHITE}(Audio 320kbps + cover + tags){CLR}",
        "fmt_wav": " {GREEN}2.{CLR} WAV  {WHITE}(Lossless audio uncompressed){CLR}",
        "fmt_mp4": " {GREEN}3.{CLR} MP4  {WHITE}(Video in max quality){CLR}",
        "sys_err": "\n{RED}[-] System error: {e}{CLR}",
        "settings_title": "\n{WHITE}SETTINGS:{CLR}",
        "settings_opt1": " {GREEN}1.{CLR} Change save directory",
        "settings_opt2": " {GREEN}2.{CLR} Change language (RU / EN)",
        "settings_opt3": " {GREEN}3.{CLR} Back",
        "settings_prompt": "{WHITE}Choice (1-3):{CLR} "
    }
}

def tr(key, **kwargs):
    """Возвращает переведённую строку, подставляя цвета и переданные аргументы."""
    lang_dict = TRANSLATIONS.get(CURRENT_LANG, TRANSLATIONS["ru"])
    text = lang_dict.get(key, TRANSLATIONS["ru"].get(key, key))
    fmt_kwargs = {
        "CLR": CLR, "GREEN": GREEN, "CYAN": CYAN, "YELLOW": YELLOW,
        "RED": RED, "WHITE": WHITE, "BOLD": BOLD
    }
    fmt_kwargs.update(kwargs)
    try:
        return text.format(**fmt_kwargs)
    except Exception:
        return text

_log_lock = threading.Lock()

def log_line(text):
    try:
        with _log_lock:
            os.makedirs(TOOLS_DIR, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass

def _find_ffmpeg_dir():
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
    global FFMPEG_DIR
    exe_name = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"
    if FFMPEG_DIR and os.path.isfile(os.path.join(FFMPEG_DIR, exe_name)):
        return

    if os.name != 'nt' or not shutil.which("winget"):
        print(tr("ffmpeg_not_found"))
        print(tr("ffmpeg_manual"))
        log_line("FFmpeg не найден, автоустановка недоступна (нет winget или не Windows)")
        return

    print(tr("ffmpeg_winget"))
    try:
        subprocess.run(
            ["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180
        )
    except Exception as e:
        print(tr("ffmpeg_winget_err", e=e))
        log_line(f"Ошибка автоустановки FFmpeg: {e}")
        return

    FFMPEG_DIR = _find_ffmpeg_dir()
    if FFMPEG_DIR:
        if FFMPEG_DIR not in os.environ.get("PATH", ""):
            os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")
        print(tr("ffmpeg_installed", path=FFMPEG_DIR))
    else:
        print(tr("ffmpeg_still_not_found"))
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
    print(tr("curr_dir", save_path=SAVE_PATH))
    new_path = input(tr("new_dir_prompt")).strip().strip('"')
    if not new_path:
        print(tr("op_cancelled"))
        return

    try:
        os.makedirs(new_path, exist_ok=True)
    except Exception as e:
        print(tr("dir_error", e=e))
        return

    if os.environ.get("NOVADL_SAVE_PATH"):
        print(tr("dir_env_warn"))

    SAVE_PATH = new_path
    cfg = _load_config()
    cfg["save_path"] = new_path
    if _save_config(cfg):
        print(tr("dir_saved", new_path=new_path))
    else:
        print(tr("dir_session_only"))

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
    for line in sums_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0]
        if len(parts) == 1 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0]
    return None

def ensure_ytdlp():
    if os.name != 'nt':
        return "yt-dlp"

    if os.path.exists(YTDLP_EXE):
        return YTDLP_EXE

    os.makedirs(TOOLS_DIR, exist_ok=True)
    print(tr("ytdlp_downloading"))
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
            print(tr("hash_skip", file="yt-dlp.exe"))

        with open(YTDLP_EXE, "wb") as f:
            f.write(data)
        return YTDLP_EXE
    except Exception as e:
        print(tr("ytdlp_err", e=e))
        print(tr("ytdlp_fallback"))
        log_line(f"Ошибка загрузки yt-dlp: {e}")
        return "yt-dlp"

def ensure_deno():
    if os.name != 'nt':
        return

    if os.path.exists(DENO_EXE):
        if TOOLS_DIR not in os.environ.get("PATH", ""):
            os.environ["PATH"] = TOOLS_DIR + os.pathsep + os.environ.get("PATH", "")
        return

    os.makedirs(TOOLS_DIR, exist_ok=True)
    print(tr("deno_downloading"))
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
            print(tr("hash_skip", file="Deno"))

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            z.extract("deno.exe", TOOLS_DIR)
        os.environ["PATH"] = TOOLS_DIR + os.pathsep + os.environ.get("PATH", "")
    except Exception as e:
        print(tr("deno_err", e=e))
        print(tr("deno_warn"))
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

    print(tr("chk_ytdlp"))
    try:
        subprocess.run([ytdlp_bin, "-U"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        pass

_spotdl_lock = threading.Lock()
_spotdl_ready = False

def _spotdl_importable():
    try:
        return importlib.util.find_spec("spotdl") is not None
    except Exception:
        return False

def ensure_spotdl_installed():
    global _spotdl_ready
    with _spotdl_lock:
        if _spotdl_ready:
            return True

        if _spotdl_importable():
            _spotdl_ready = True
            return True

        print(tr("spotdl_deps"))
        for pkg in ("yt-dlp", "yt-dlp-ejs", "spotdl"):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-U", "--no-input", pkg],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
                )
            except Exception as e:
                print(tr("spotdl_err_pkg", pkg=pkg, e=e))
                log_line(f"Ошибка установки {pkg}: {e}")

        _spotdl_ready = _spotdl_importable()
        if _spotdl_ready:
            print(tr("spotdl_ready"))
        else:
            print(tr("spotdl_fail"))
        return _spotdl_ready

def update_spotdl_dependencies_background():
    with _UPDATE_STATE_LOCK:
        state = load_update_state()
        if not check_should_update(state, "spotdl_deps"):
            return
        state["spotdl_deps"] = time.time()
        save_update_state(state)

    if not _spotdl_importable():
        return

    print(tr("chk_spotdl"))
    for pkg in ("yt-dlp", "yt-dlp-ejs", "spotdl"):
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "--no-input", pkg],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45
            )
        except Exception:
            pass

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

_cookie_warning_shown = False

def get_cookies_args():
    global _cookie_warning_shown
    if os.path.exists(COOKIES_PATH):
        return ["--cookies", COOKIES_PATH]

    if not _cookie_warning_shown:
        print(tr("cookie_not_found", path=COOKIES_PATH))
        print(tr("cookie_chrome_warn"))
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
    if os.path.exists(COOKIES_PATH):
        return False
    low = " ".join(l.lower() for l in logs)
    return any(marker in low for marker in COOKIE_ISSUE_MARKERS)

def print_cookie_issue_hint():
    print(tr("cookie_issue_hint1"))
    print(tr("cookie_issue_hint2"))

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
            cmd, cwd=SAVE_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, encoding='utf-8', errors='ignore', bufsize=1
        )
    except FileNotFoundError:
        raise
    except Exception as e:
        print(tr("popen_err", e=e))
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
                print(tr("playlist_track", curr=current_track_num, total=total_tracks))

        if platform in ["YouTube", "SoundCloud"]:
            if "[download]" in line_str and "%" in line_str and "ETA" in line_str:
                match = re.search(r'(\d+\.\d+)%', line_str)
                if match:
                    pct = float(match.group(1))
                    speed_match = re.search(r'at\s+([\d.]+\S+/s)', line_str)
                    speed_text = speed_match.group(1) if speed_match else ""
                    render_progress_bar(pct, tr("downloading_num", num=current_track_num if current_track_num else 1), speed_text)
            elif "[ExtractAudio]" in line_str:
                print(tr("extract_audio"))
            elif "[ThumbnailsConvertor]" in line_str or "embed-thumbnail" in line_str.lower():
                print(tr("process_cover"))
            elif "[Metadata]" in line_str or "embed-metadata" in line_str.lower():
                print(tr("save_meta"))

        elif platform == "Spotify":
            if "Fetching" in line_str or "Searching" in line_str or "Found" in line_str:
                print(tr("fetching_db"))
            elif "Downloading" in line_str or "Downloaded" in line_str:
                match = re.search(r'(\d+)%', line_str)
                pct = float(match.group(1)) if match else 100.0
                render_progress_bar(pct, tr("download_audio"))
            elif "Converting" in line_str or "Processing" in line_str:
                print(tr("applying_tags"))

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
        print(tr("files_not_saved"))
        for err_line in error_logs:
            if "ETA" not in err_line:
                print(f"{RED} > {err_line}{CLR}")
        if has_cookie_issue(error_logs):
            print_cookie_issue_hint()
        return False, format_not_available, has_errors

    if new_files:
        print(tr("files_saved", count=len(new_files)))

    return True, format_not_available, has_errors

def build_common_ytdlp_args(retry=False):
    ffmpeg_target = FFMPEG_DIR if FFMPEG_DIR else "ffmpeg"
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
    output_template = "%(title)s.%(ext)s"
    pre_fmt, post_fmt = _format_specific_args(file_type, retry)
    cmd = [ytdlp_bin] + pre_fmt + ["-o", output_template] + build_common_ytdlp_args(retry) + post_fmt
    cmd.append("--no-playlist")
    cmd.extend(urls)
    return cmd

def extract_playlist_video_urls(ytdlp_bin, url):
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
                cmd, cwd=SAVE_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, encoding='utf-8', errors='ignore', bufsize=1
            )
        except Exception as e:
            with print_lock:
                shared_error_logs.append(tr("thread_start_err", id=worker_id, e=e))
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
                            print(tr("thread_progress", id=worker_id, pct=pct, speed=speed_text))

        process.wait()
        with print_lock:
            shared_error_logs.extend(local_logs)
        return format_not_available, has_error

    except Exception as e:
        with print_lock:
            shared_error_logs.append(tr("thread_err", id=worker_id, e=e))
        return False, True

def process_playlist_parallel(ytdlp_bin, url, file_type, platform, retry=False):
    print(tr("playlist_fetch"))
    entries = extract_playlist_video_urls(ytdlp_bin, url)

    files_before = get_media_files_snapshot(SAVE_PATH)
    print_lock = threading.Lock()
    shared_error_logs = []

    if entries:
        workers = max(1, min(PLAYLIST_WORKERS, len(entries)))
        print(tr("playlist_found", count=len(entries), workers=workers))
        chunks = [entries[i::workers] for i in range(workers)]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for i, chunk in enumerate(chunks):
                if not chunk: continue
                cmd = build_ytdlp_command_multi(ytdlp_bin, chunk, file_type, retry=retry)
                futures.append(pool.submit(execute_playlist_worker, cmd, i + 1, print_lock, shared_error_logs))
            results = [f.result() for f in futures]
    else:
        workers = PLAYLIST_WORKERS
        print(tr("playlist_fallback", workers=workers))
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
        print(tr("files_saved", count=len(new_files)))
    elif not disk_confirmed:
        print(tr("no_files_saved"))
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
        print(tr("unsupported_platform"))
        return

    print(tr("source", platform=platform, fmt=file_type.upper()))
    print(tr("starting"))

    is_playlist = is_playlist_url(url)
    ffmpeg_exe = os.path.join(FFMPEG_DIR, "ffmpeg.exe") if FFMPEG_DIR else "ffmpeg"

    if platform == "Spotify":
        if not ensure_spotdl_installed():
            print(tr("spotdl_not_avail"))
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
            print(tr("spotdl_not_found"))
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
                print(tr("ytdlp_not_found"))
                success = False
                format_not_available = False
                has_errors = True

        if not success and format_not_available:
            print(tr("fallback_start"))
            if is_playlist and PLAYLIST_WORKERS > 1:
                success, _, has_errors = process_playlist_parallel(ytdlp_bin, url, file_type, platform, retry=True)
            else:
                retry_cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, retry=True)
                try:
                    success, _, has_errors = execute_and_stream_output(retry_cmd, platform)
                except FileNotFoundError:
                    print(tr("ytdlp_not_found"))
                    success = False
                    has_errors = True

    print(tr("separator"))
    if success:
        if is_playlist and has_errors:
            print(tr("partial_success"))
        else:
            print(tr("success"))
        print(tr("saved_dir", path=SAVE_PATH))
    else:
        print(tr("aborted"))
        if platform != "Spotify" and not os.path.exists(COOKIES_PATH):
            print(tr("aborted_cookie_hint"))
    print(tr("separator"))

def read_menu_choice(prompt_key="input_1_2_3", unix_prompt="input_1_2_3_unix"):
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
                print(ch_str)
                return ch_str
            if ch_str in ('\r', '\n'):
                continue
            sys.stdout.write(tr(prompt_key))
            sys.stdout.flush()
    else:
        while True:
            choice = input(tr(unix_prompt)).strip()
            if choice in valid:
                return choice
            print(tr("input_1_2_3_warn"))

def show_settings_menu():
    global CURRENT_LANG
    while True:
        clear_screen()
        print(tr("settings_title"))
        print(tr("settings_opt1"))
        print(tr("settings_opt2"))
        print(tr("settings_opt3"))
        print(tr("separator"))
        
        c = read_menu_choice("settings_prompt", "settings_prompt")
        
        if c == '1':
            prompt_change_save_directory()
            input(tr("press_enter"))
        elif c == '2':
            CURRENT_LANG = "en" if CURRENT_LANG == "ru" else "ru"
            cfg = _load_config()
            cfg["language"] = CURRENT_LANG
            _save_config(cfg)
        elif c == '3':
            break

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
        print(tr("main_title"))
        print(tr("separator"))
        print(tr("main_save", path=SAVE_PATH))
        
        cookie_status = tr("cookie_active") if os.path.exists(COOKIES_PATH) else tr("cookie_browser")
        cookie_color = GREEN if os.path.exists(COOKIES_PATH) else YELLOW
        print(tr("main_cookie", color=cookie_color, status=cookie_status))
        
        ffmpeg_status = FFMPEG_DIR if FFMPEG_DIR else tr("ffmpeg_not_found_status")
        ffmpeg_color = GREEN if FFMPEG_DIR else RED
        print(tr("main_ffmpeg", color=ffmpeg_color, status=ffmpeg_status))
        
        print(tr("main_lang"))
        print(tr("separator"))

        url = input(tr("url_prompt")).strip()
        if not url: break

        if url == '0':
            show_settings_menu()
            continue

        print(tr("choose_format"))
        print(tr("fmt_mp3"))
        print(tr("fmt_wav"))
        print(tr("fmt_mp4"))
        print(tr("separator"))

        choice = read_menu_choice()

        file_type = "mp3"
        if choice == '2': file_type = "wav"
        elif choice == '3': file_type = "mp4"

        try:
            start_download_process(url, file_type, ytdlp_bin)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(tr("sys_err", e=e))
            log_line(f"Системная ошибка: {e}")

        input(tr("press_enter"))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
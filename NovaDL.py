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
import collections
import queue
import atexit

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
        "fs_permission_hint1": "\n{YELLOW}[~] Не удалось записать файл в папку загрузки — система отказала в доступе (Permission denied).{CLR}",
        "fs_permission_hint2": "{YELLOW}[~] Частые причины: папка защищена 'Контролируемым доступом к папкам' Windows (Defender) или антивирусом; файл с таким именем уже открыт в другой программе или помечен 'только для чтения'; папка на OneDrive временно заблокирована синхронизацией. Попробуйте сменить папку загрузки (пункт '0' в меню) на другую, например обычную папку не под OneDrive, либо добавьте NovaDL в исключения антивируса/Controlled folder access.{CLR}",
        "cookie_retry_no_auth": "{YELLOW}[~] Не удалось прочитать cookies из Chrome — повторяю попытку без авторизации (без cookies).{CLR}",
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
        "multi_urls_summary": "\n{GREEN}[+] Ссылок: {BOLD}{count}{CLR} | {GREEN}Формат: {BOLD}{fmt}{CLR}",
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
        "fmt_mp3": " {GREEN}1.{CLR}  ♪  MP3   {WHITE}320kbps · обложка · теги{CLR}",
        "fmt_wav": " {GREEN}2.{CLR}  ◈  WAV   {WHITE}Lossless · без сжатия{CLR}",
        "fmt_mp4": " {GREEN}3.{CLR}  ▶  MP4   {WHITE}Видео в максимальном качестве{CLR}",
        "sys_err": "\n{RED}[-] Системная ошибка: {e}{CLR}",
        "settings_title": "\n{WHITE}НАСТРОЙКИ (SETTINGS):{CLR}",
        "settings_opt1": " {GREEN}1.{CLR} Изменить директорию сохранения (Change save path)",
        "settings_opt2": " {GREEN}2.{CLR} Изменить язык (Change language)",
        "settings_opt3": " {GREEN}3.{CLR} Назад (Back)",
        "settings_prompt": "{WHITE}Выбор / Choice (1-3):{CLR} ",
        "quality_probing": "{CYAN}[*] Определяю максимальное доступное качество видео...{CLR}",
        "quality_probe_failed": "{YELLOW}[~] Не удалось определить качество ролика заранее — будет использовано наилучшее доступное.{CLR}",
        "quality_menu_title": "\n{WHITE}Максимальное качество этого видео: {GREEN}{height}p{CLR}. Выберите качество для загрузки:{CLR}",
        "quality_max_label": "максимальное",
        "quality_prompt": "{WHITE}Выбор (1-{max_num}, Enter - максимальное):{CLR} ",
        "quality_invalid": "{YELLOW}[~] Введите число из списка.{CLR}",
        "playlist_v_ignored": "{YELLOW}[~] Ссылка содержит плейлист, но также параметр v= (конкретное видео). Будет скачано только это видео. Для загрузки плейлиста уберите v= из URL.{CLR}",
        "result_time": "{WHITE}    Время: {elapsed}{CLR}",
        "mode_single": "Одиночное",
        "mode_playlist": "Плейлист",
        "mode_multi": "Несколько ссылок",
        "platform_label": "Платформа",
        "mode_label": "Режим",
        "thread_label": "Поток {id}",
        "multi_overall": "{WHITE}Всего:{CLR} {GREEN}{done}{CLR}{WHITE}/{total}{CLR}",
        "multi_failed": "{RED}Ошибок: {n}{CLR}",
        "stage_processing": "Обработка…",
        "stage_merging": "Склейка…",
        "stage_audio": "Аудио…",
        "stage_cover": "Обложка…",
        "stage_meta": "Метаданные…",
        "stage_done": "Готово",
        "stage_failed": "Ошибка",
        "stage_idle": "Свободен",
        "stage_exists": "Уже скачано",
        "merge_streams": "\n{YELLOW}[*] Склейка видео и аудио...{CLR}",
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
        "fs_permission_hint1": "\n{YELLOW}[~] Could not write a file to the download folder — the OS denied access (Permission denied).{CLR}",
        "fs_permission_hint2": "{YELLOW}[~] Common causes: the folder is protected by Windows 'Controlled folder access' (Defender) or antivirus; a file with the same name is open in another program or marked read-only; the OneDrive folder is temporarily locked by sync. Try changing the download folder (option '0' in the menu) to a plain, non-OneDrive folder, or add NovaDL to your antivirus/Controlled folder access exceptions.{CLR}",
        "cookie_retry_no_auth": "{YELLOW}[~] Failed to read cookies from Chrome — retrying without authentication (no cookies).{CLR}",
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
        "multi_urls_summary": "\n{GREEN}[+] Links: {BOLD}{count}{CLR} | {GREEN}Format: {BOLD}{fmt}{CLR}",
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
        "fmt_mp3": " {GREEN}1.{CLR}  ♪  MP3   {WHITE}320kbps · cover · tags{CLR}",
        "fmt_wav": " {GREEN}2.{CLR}  ◈  WAV   {WHITE}Lossless · uncompressed{CLR}",
        "fmt_mp4": " {GREEN}3.{CLR}  ▶  MP4   {WHITE}Video in max quality{CLR}",
        "sys_err": "\n{RED}[-] System error: {e}{CLR}",
        "settings_title": "\n{WHITE}SETTINGS:{CLR}",
        "settings_opt1": " {GREEN}1.{CLR} Change save directory",
        "settings_opt2": " {GREEN}2.{CLR} Change language (RU / EN)",
        "settings_opt3": " {GREEN}3.{CLR} Back",
        "settings_prompt": "{WHITE}Choice (1-3):{CLR} ",
        "quality_probing": "{CYAN}[*] Detecting the maximum available video quality...{CLR}",
        "quality_probe_failed": "{YELLOW}[~] Could not detect quality in advance — best available quality will be used.{CLR}",
        "quality_menu_title": "\n{WHITE}Maximum quality for this video: {GREEN}{height}p{CLR}. Choose a quality to download:{CLR}",
        "quality_max_label": "maximum",
        "quality_prompt": "{WHITE}Choice (1-{max_num}, Enter - maximum):{CLR} ",
        "quality_invalid": "{YELLOW}[~] Please enter a number from the list.{CLR}",
        "playlist_v_ignored": "{YELLOW}[~] URL contains a playlist but also v= (specific video). Only this video will be downloaded. Remove v= from the URL to download the full playlist.{CLR}",
        "result_time": "{WHITE}    Time: {elapsed}{CLR}",
        "mode_single": "Single",
        "mode_playlist": "Playlist",
        "mode_multi": "Multiple URLs",
        "platform_label": "Platform",
        "mode_label": "Mode",
        "thread_label": "Thread {id}",
        "multi_overall": "{WHITE}Total:{CLR} {GREEN}{done}{CLR}{WHITE}/{total}{CLR}",
        "multi_failed": "{RED}Failed: {n}{CLR}",
        "stage_processing": "Processing…",
        "stage_merging": "Merging…",
        "stage_audio": "Audio…",
        "stage_cover": "Cover art…",
        "stage_meta": "Metadata…",
        "stage_done": "Done",
        "stage_failed": "Failed",
        "stage_idle": "Idle",
        "stage_exists": "Already saved",
        "merge_streams": "\n{YELLOW}[*] Merging video and audio...{CLR}",
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
    # Принудительно сбрасываем буфер вывода перед очисткой экрана.
    # Иначе при многопоточной загрузке (несколько ссылок / плейлист) часть
    # ещё не выведенных строк из потоков может "дорисоваться" уже поверх
    # очищенного экрана, из-за чего кажется, что старый текст не стёрся.
    sys.stdout.flush()
    sys.stderr.flush()
    os.system('cls' if os.name == 'nt' else 'clear')

class LoadingAnimation:
    BRAILLE = "⣾⣽⣻⢿⡿⣟⣯⣷"
    DOTS    = "⠁⠃⠇⠏⠟⠿⠟⠏⠇⠃"

    def __init__(self, text, style="braille"):
        self.text = text.replace('\n', '').rstrip()
        self.style = style
        self.chars = self.BRAILLE if style == "braille" else self.DOTS
        self.running = False
        self.thread = None

    def _spin(self):
        idx = 0
        while self.running:
            frame = self.chars[idx % len(self.chars)]
            sys.stdout.write(f"\r{self.text} {frame}  ")
            sys.stdout.flush()
            time.sleep(0.08)
            idx += 1
        sys.stdout.write(f"\r{self.text}   \n")
        sys.stdout.flush()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

_global_anim = None

def start_anim(text, style="braille"):
    global _global_anim
    if _global_anim:
        _global_anim.stop()
    _global_anim = LoadingAnimation(text, style=style)
    _global_anim.start()

def stop_anim():
    global _global_anim
    if _global_anim:
        _global_anim.stop()
        _global_anim = None

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

    if os.path.exists(YTDLP_EXE) and os.path.getsize(YTDLP_EXE) > 0:
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

        stop_anim()
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

CONCURRENT_FRAGMENTS = int(os.environ.get("NOVADL_CONCURRENT_FRAGMENTS", "16"))
SPOTDL_THREADS = os.environ.get("NOVADL_SPOTDL_THREADS", "4")
HTTP_CHUNK_SIZE = os.environ.get("NOVADL_HTTP_CHUNK_SIZE", "16M")
PLAYLIST_WORKERS = max(1, int(os.environ.get("NOVADL_PLAYLIST_WORKERS", "2")))
ARIA2_CONNECTIONS = os.environ.get("NOVADL_ARIA2_CONNECTIONS", "8")

# aria2c теперь ОПЦИОНАЛЕН (NOVADL_USE_ARIA2C=1). С "-x 1 -s 1" он не даёт никакого
# параллелизма, зато качает файл ОДНИМ непрерывным запросом: родной загрузчик
# yt-dlp режет YouTube-потоки на чанки (--http-chunk-size), чтобы обойти
# троттлинг googlevideo, а внешний aria2c этого не делает — отсюда "быстро до
# ~90%, а дальше ползёт". Плюс его строки прогресса имеют другой формат.
USE_ARIA2C = os.environ.get("NOVADL_USE_ARIA2C", "0").strip().lower() in ("1", "true", "yes", "on")

# Защита от "зависаний на последних процентах":
#  * socket-timeout — по умолчанию у yt-dlp 20 с, умноженное на 10 ретраев даёт
#    минуты ожидания на одном зависшем чанке/фрагменте;
#  * throttled-rate — если скорость падает ниже порога (YouTube душит соединение),
#    yt-dlp заново запрашивает ссылку вместо того, чтобы ползти на 50 КБ/с.
#    Чтобы отключить, задайте NOVADL_THROTTLED_RATE=0.
SOCKET_TIMEOUT = os.environ.get("NOVADL_SOCKET_TIMEOUT", "15")
THROTTLED_RATE = os.environ.get("NOVADL_THROTTLED_RATE", "100K")

_ARIA2C_PATH = shutil.which("aria2c")

def ensure_aria2c_background():
    global _ARIA2C_PATH
    if not USE_ARIA2C or os.name != 'nt' or _ARIA2C_PATH or not shutil.which("winget"):
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
    if USE_ARIA2C and _ARIA2C_PATH:
        # ВАЖНО: googlevideo.com не допускает несколько параллельных
        # Range-соединений к одному и тому же подписанному URL — все,
        # кроме первого, получают HTTP 403 (aria2c падает с errorCode=22).
        # Это не влияет на фрагментированные (DASH/HLS) загрузки, т.к. там
        # каждый фрагмент — отдельный URL, поэтому параллелизм там
        # обеспечивает --concurrent-fragments, а не -x/-s aria2c. Именно
        # поэтому ускоряем именно CONCURRENT_FRAGMENTS (16 вместо 8) и
        # НЕ трогаем -x/-s — попытка поднять их вернёт те же 403.
        # "--file-allocation=none" убирает паузу на предварительное
        # выделение места на диске перед стартом закачки (особенно
        # заметно на Windows/HDD и в первые секунды загрузки).
        return [
            "--downloader", "aria2c",
            "--downloader-args",
            "aria2c:-x 1 -s 1 -k 1M --max-tries=10 --retry-wait=3 --file-allocation=none",
            "--concurrent-fragments", str(CONCURRENT_FRAGMENTS),
        ]
    return [
        "--concurrent-fragments", str(CONCURRENT_FRAGMENTS),
        "--http-chunk-size", HTTP_CHUNK_SIZE,
        # ВАЖНО: у встроенного (не aria2c) загрузчика yt-dlp по умолчанию
        # маленький буфер чтения — это означает больше системных вызовов
        # на тот же объём данных и заметно бьёт по скорости на быстрых
        # каналах. Увеличиваем буфер, чтобы меньше "дёргать" диск/сеть.
        "--buffer-size", "16M",
    ]


_cookie_warning_shown = False

def get_cookies_args(allow_browser_fallback=True):
    global _cookie_warning_shown
    if os.path.exists(COOKIES_PATH):
        return ["--cookies", COOKIES_PATH]

    if not allow_browser_fallback:
        # Ранее при сбое чтения cookies.txt (не найден) скрипт ВСЕГДА
        # принудительно пытался вытащить cookies из Chrome, даже если
        # это было уже опробовано и не удалось (например, из-за
        # заблокированной/открытой базы Chrome — "Could not copy Chrome
        # cookie database"). Из-за этого загрузка публичного контента,
        # не требующего авторизации вовсе, полностью падала, хотя без
        # cookies она могла пройти успешно. Теперь вызывающий код может
        # явно попросить не трогать браузер и просто скачивать анонимно.
        return []

    if not _cookie_warning_shown:
        # Если в этот момент крутится спиннер, его "\r"-строка перемешалась бы с
        # текстом предупреждения (получалась каша из двух строк). Гасим спиннер
        # на время вывода и запускаем заново с тем же текстом/стилем.
        _anim = _global_anim
        _resume = (_anim.text, _anim.style) if _anim else None
        stop_anim()
        print(tr("cookie_not_found", path=COOKIES_PATH))
        print(tr("cookie_chrome_warn"))
        _cookie_warning_shown = True
        if _resume:
            start_anim(_resume[0], style=_resume[1])

    return ["--cookies-from-browser", "chrome"]

COOKIE_ISSUE_MARKERS = (
    "could not copy chrome cookie database",
    "could not find chrome cookies database",
    "could not find browser",
    "database is locked",
    "failed to decrypt",
    "unsupported browser",
)

def has_cookie_issue(logs):
    if os.path.exists(COOKIES_PATH):
        return False
    low = " ".join(l.lower() for l in logs)
    return any(marker in low for marker in COOKIE_ISSUE_MARKERS)

def print_cookie_issue_hint():
    print(tr("cookie_issue_hint1"))
    print(tr("cookie_issue_hint2"))

# ВАЖНО: раньше "permission denied" был в COOKIE_ISSUE_MARKERS. Это было
# неверно: обычная ошибка записи файла на диск (например, "ERROR: [Errno 13]
# Permission denied" при попытке сохранить обложку/thumbnail в папку
# загрузки — папка защищена антивирусом/Controlled Folder Access, файл
# занят другим приложением и т.п.) не имеет никакого отношения к чтению
# cookies из браузера, но по этому общему слову ошибочно определялась как
# "проблема с cookies" — пользователю показывались нерелевантные советы
# про Chrome вместо реальной причины (недоступна папка для записи).
FS_PERMISSION_MARKERS = (
    "permission denied",
    "errno 13",
)

def has_fs_permission_issue(logs):
    low = " ".join(l.lower() for l in logs)
    if not any(marker in low for marker in FS_PERMISSION_MARKERS):
        return False
    # Не путать с ошибками чтения cookies из браузера — у тех своя,
    # более точная диагностика (has_cookie_issue).
    return not any(marker in low for marker in COOKIE_ISSUE_MARKERS)

def print_fs_permission_hint():
    print(tr("fs_permission_hint1"))
    print(tr("fs_permission_hint2"))

# ──────────────────────────────────────────────────────────────────────────
# АВТОМАТИЧЕСКОЕ ВОССТАНОВЛЕНИЕ ПОСЛЕ ОШИБОК ВЫБОРА КЛИЕНТА/СЕССИИ YOUTUBE
#
# "The page needs to be reloaded" — это сигнал innertube API о том, что
# ответ плеера (playability status) для выбранного клиента (в частности
# "tv"/TVHTML5) недействителен: клиент требует свежей сессии/визитора,
# либо у yt-dlp закэширован устаревший player/nsig-код для этого клиента.
# То же семейство проблем даёт "Sign in to confirm you're not a bot" и
# "Sign in to confirm your age" — все они означают, что ВЫБРАННЫЙ клиент
# innertube больше не отдаёт рабочий формат, а не что видео недоступно.
# Поэтому все такие ошибки обрабатываются как единый класс "нужен другой
# клиент/чистый кэш" — так же, как и "Requested format is not available":
# запускается автоматический повтор с другим набором player_client и,
# при необходимости, с очищенным кэшем yt-dlp.
# ──────────────────────────────────────────────────────────────────────────
RETRYABLE_YTDLP_MARKERS = (
    "requested format is not available",
    "the page needs to be reloaded",
    "sign in to confirm you're not a bot",
    "sign in to confirm your age",
    "unable to extract initial data",
)

def is_retryable_ytdlp_error(line_str):
    low = line_str.lower()
    return any(marker in low for marker in RETRYABLE_YTDLP_MARKERS)

def clear_ytdlp_cache(ytdlp_bin):
    # Сбрасывает кэш yt-dlp (в т.ч. закэшированные player/nsig-функции для
    # клиентов вроде "tv"). Устаревший кэш — частая причина ошибки
    # "The page needs to be reloaded", т.к. yt-dlp пытается расшифровать
    # подпись/nsig старым, уже неактуальным кодом плеера YouTube.
    try:
        subprocess.run(
            [ytdlp_bin, "--rm-cache-dir"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20
        )
        log_line("[NovaDL] Кэш yt-dlp очищен из-за ошибки сессии/клиента YouTube.")
    except Exception:
        pass

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

_PARTIAL_BLOCKS = " ▏▎▍▌▋▊▉"

def render_progress_bar(percentage, status_text, speed_text="", width=30, speed_width=13):
    """Рисует аккуратный прогресс-бар одной строкой (перезаписывает саму себя через \\r).

    Скорость закреплена в колонке справа от бара фиксированной ширины
    (speed_width), поэтому при изменении длины строки скорости ("1.2MiB/s" ->
    "980.4KiB/s") бар не "дёргается" и не остаются хвосты от предыдущей строки.
    """
    percentage = max(0.0, min(100.0, percentage))

    # Цвет бара мягко меняется по мере прогресса: жёлтый -> голубой -> зелёный.
    if percentage < 34:
        bar_color = YELLOW
    elif percentage < 75:
        bar_color = CYAN
    else:
        bar_color = GREEN

    filled_float = (width * percentage) / 100
    filled_length = int(filled_float)
    remainder = filled_float - filled_length
    partial_idx = int(round(remainder * (len(_PARTIAL_BLOCKS) - 1)))

    bar = '█' * filled_length
    if filled_length < width and partial_idx > 0:
        bar += _PARTIAL_BLOCKS[partial_idx]
        filled_length += 1
    bar += '░' * (width - filled_length)

    speed_display = f"⇩ {speed_text}" if speed_text else ""
    speed_part = f" {WHITE}{speed_display:<{speed_width}}{CLR}"

    sys.stdout.write(
        f"\r{CYAN}[*] {status_text} {WHITE}│{CLR}{bar_color}{bar}{CLR}{WHITE}│{CLR} "
        f"{BOLD}{percentage:>5.1f}%{CLR}{speed_part}"
    )
    sys.stdout.flush()

# ──────────────────────────────────────────────────────────────────────────
# РАЗБОР ВЫВОДА yt-dlp И ПРОГРЕСС ТРЕКОВ
# ──────────────────────────────────────────────────────────────────────────
_RE_PERCENT = re.compile(r'(\d+(?:\.\d+)?)%')
_RE_YT_SPEED = re.compile(r'at\s+([\d.]+\S+/s)')
_RE_ARIA = re.compile(r'\[#\w+\s+[\d.]+\w*/[\d.]+\w*\((\d+)%\)(?:.*?DL:([\d.]+\w*))?')
_RE_ITEM = re.compile(r'Downloading item (\d+) of (\d+)')
_RE_FORMATS = re.compile(r'Downloading\s+\d+\s+format\(s\):\s*(\S+)')

def parse_progress_line(line):
    """Возвращает (процент, скорость_текстом) для строки прогресса загрузки или None.

    Понимает и родной вывод yt-dlp ("[download]  45.3% of ~10MiB at 2MiB/s ETA 00:05"),
    и вывод aria2c ("[#a1b2c3 5MiB/20MiB(25%) CN:1 DL:3MiB ETA:4s]"). Раньше
    учитывался только первый вариант и только с десятичной точкой в проценте.
    """
    if "[download]" in line and "%" in line and ("ETA" in line or " of " in line):
        m = _RE_PERCENT.search(line)
        if m:
            sm = _RE_YT_SPEED.search(line)
            return float(m.group(1)), (sm.group(1) if sm else "")
    elif line.startswith("[#"):
        m = _RE_ARIA.search(line)
        if m:
            speed = (m.group(2) + "/s") if m.group(2) else ""
            return float(m.group(1)), speed
    return None

def classify_post_stage(line):
    """Ключ перевода стадии постобработки (склейка, обложка, теги...) или None."""
    low = line.lower()
    if "[Merger]" in line:
        return "stage_merging"
    if "[ExtractAudio]" in line:
        return "stage_audio"
    if "[ThumbnailsConvertor]" in line or "[EmbedThumbnail]" in line or "embed-thumbnail" in low:
        return "stage_cover"
    if "[Metadata]" in line or "embed-metadata" in low:
        return "stage_meta"
    if any(tag in line for tag in ("[MoveFiles]", "[Fixup", "[VideoConvertor]", "[VideoRemuxer]")):
        return "stage_processing"
    return None

def expected_stream_count(file_type, tier=0, max_height=None):
    """Сколько потоков (видео+аудио) yt-dlp скачает для одного трека, если не сказано точнее."""
    if file_type != "mp4":
        return 1
    if tier > 0 and not max_height:
        return 1    # резервный формат "best" — один совмещённый поток
    return 2

class TrackProgress:
    """Монотонный общий прогресс ОДНОГО трека.

    Что исправляет:
      * проценты yt-dlp "гуляют" (для фрагментных загрузок оценка размера
        уточняется на ходу: 63.4% -> 62.9% -> 64.1%) — откаты внутри потока
        игнорируются, бар идёт только вперёд;
      * у видео и аудио счёт идёт заново с 0% — раньше бар на середине
        прыгал обратно в ноль. Теперь потоки сводятся в один бар с весами
        (видео ≈ 88%, аудио ≈ 12%), число потоков берётся из строки
        "Downloading 2 format(s): 137+140".
    """
    VIDEO_WEIGHT = 0.88

    def __init__(self, expected_streams=1):
        self.expected = max(1, int(expected_streams))
        self.idx = 0
        self.stream_pct = 0.0
        self.overall = 0.0
        self.speed_text = ""
        self.started = False

    def _weights(self):
        if self.expected == 1:
            return [1.0]
        rest = (1.0 - self.VIDEO_WEIGHT) / (self.expected - 1)
        return [self.VIDEO_WEIGHT] + [rest] * (self.expected - 1)

    def set_expected(self, n):
        if not self.started:
            self.expected = max(1, int(n))

    def new_stream(self):
        """Вызывается на "[download] Destination:" — начался следующий поток трека."""
        if self.started and self.stream_pct > 0:
            self.idx += 1
            self.stream_pct = 0.0

    def update(self, pct, speed_text=""):
        pct = max(0.0, min(100.0, pct))
        # Страховка, если строку Destination пропустили: прошлый поток уже ~100%,
        # а новый стартует с малого значения — это следующий поток, а не откат.
        if self.started and self.stream_pct >= 99.0 and pct < 20.0 and self.idx + 1 < self.expected:
            self.idx += 1
            self.stream_pct = 0.0
        self.started = True
        if pct > self.stream_pct:
            self.stream_pct = pct
        if speed_text:
            self.speed_text = speed_text
        w = self._weights()
        i = min(self.idx, len(w) - 1)
        value = (sum(w[:i]) + w[i] * self.stream_pct / 100.0) * 100.0
        if value > self.overall:
            self.overall = value
        return self.overall

    def finish(self):
        """Загрузка закончена (пошла постобработка / файл уже был) — бар на 100%."""
        self.started = True
        self.overall = 100.0
        return self.overall

class MultiProgress:
    """Живой блок прогресса для параллельной загрузки.

    По ОДНОЙ строке на каждый активный поток + итоговая строка. Блок
    перерисовывается на месте (курсор вверх + очистка строки) одним write()
    ~12 раз в секунду, поэтому:
      * вместо 10–15 новых строк на трек — один бар, который обновляется;
      * отображаемое значение плавно "догоняет" реальное и никогда не
        откатывается назад;
      * во время склейки/обложки/тегов в строке виден этап, а не "зависший" бар.
    Если stdout не терминал (перенаправлен в файл) — живая отрисовка отключается,
    печатается по одной строке на завершённый трек.
    """
    FPS = 12
    _cursor_guard_registered = False

    def __init__(self, slot_count, total_tracks=0, show_overall=True):
        self._lock = threading.RLock()
        self._slots = [self._new_slot(i) for i in range(max(1, slot_count))]
        self.total = total_tracks
        self.show_overall = show_overall
        self._status = {}
        self._frame = 0
        self._drawn_lines = 0
        self._stop_evt = threading.Event()
        self._thread = None
        self._started = False
        try:
            self._tty = sys.stdout.isatty()
        except Exception:
            self._tty = False

    @staticmethod
    def _new_slot(i):
        return {"label": tr("thread_label", id=i + 1), "target": 0.0, "shown": 0.0,
                "speed": "", "state": "idle", "stage": ""}

    # ── управление ──
    def start(self):
        if self._started:
            return
        self._started = True
        if self._tty:
            if not MultiProgress._cursor_guard_registered:
                atexit.register(lambda: (sys.stdout.write("\033[?25h"), sys.stdout.flush()))
                MultiProgress._cursor_guard_registered = True
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            self._stop_evt.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        if not self._started:
            return
        self._started = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._tty:
            self._draw(final=True)
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()

    # ── обновление состояния (потокобезопасно) ──
    def begin_track(self, slot, label):
        with self._lock:
            s = self._slots[slot]
            s.update(label=label, target=0.0, shown=0.0, speed="", state="active", stage="")

    def set_label(self, slot, label):
        with self._lock:
            self._slots[slot]["label"] = label

    def update(self, slot, pct, speed=""):
        with self._lock:
            s = self._slots[slot]
            if s["state"] in ("idle", "ok", "fail"):
                s["state"] = "active"
            if pct > s["target"]:
                s["target"] = min(100.0, pct)
            if speed:
                s["speed"] = speed
            if s["state"] == "active":
                s["stage"] = ""

    def set_stage(self, slot, stage_text):
        with self._lock:
            s = self._slots[slot]
            s["state"] = "processing"
            s["stage"] = stage_text
            s["target"] = 100.0

    def finish_track(self, slot, track_key, ok):
        with self._lock:
            s = self._slots[slot]
            s["state"] = "ok" if ok else "fail"
            s["stage"] = tr("stage_done") if ok else tr("stage_failed")
            s["speed"] = ""
            if ok:
                s["target"] = 100.0
            self._status[track_key] = bool(ok)
        if not self._tty:
            with self._lock:
                print(f"[{s['label']}] {tr('stage_done') if ok else tr('stage_failed')}", flush=True)

    def set_idle(self, slot):
        with self._lock:
            s = self._slots[slot]
            if s["state"] not in ("ok", "fail"):
                s["state"] = "idle"
                s["stage"] = tr("stage_idle")
                s["speed"] = ""

    def add_total(self, n):
        with self._lock:
            if self.total > 0:
                self.total += n

    # ── отрисовка ──
    def _loop(self):
        while not self._stop_evt.wait(1.0 / self.FPS):
            self._frame += 1
            try:
                self._draw()
            except Exception:
                pass

    @staticmethod
    def _layout(cols):
        label_w, tail_w = 22, 16
        bar_w = cols - 1 - 13 - label_w - tail_w
        if bar_w < 8:
            tail_w = 10
            bar_w = cols - 1 - 13 - label_w - tail_w
        if bar_w < 8:
            label_w = max(6, cols - 1 - 13 - tail_w - 8)
            bar_w = max(4, cols - 1 - 13 - label_w - tail_w)
        return label_w, min(bar_w, 26), tail_w

    def _slot_line(self, s, label_w, bar_w, tail_w):
        pct = max(0.0, min(100.0, s["shown"]))
        state = s["state"]
        if state == "ok":
            icon, bar_color = f"{GREEN}✓{CLR}", GREEN
        elif state == "fail":
            icon, bar_color = f"{RED}✗{CLR}", RED
        elif state == "idle":
            icon, bar_color = f"{WHITE}·{CLR}", WHITE
        else:
            icon = f"{CYAN}{LoadingAnimation.BRAILLE[self._frame % len(LoadingAnimation.BRAILLE)]}{CLR}"
            bar_color = YELLOW if pct < 34 else (CYAN if pct < 75 else GREEN)

        filled_float = bar_w * pct / 100.0
        filled = int(filled_float)
        part_idx = int(round((filled_float - filled) * (len(_PARTIAL_BLOCKS) - 1)))
        bar = '█' * filled
        if filled < bar_w and part_idx > 0:
            bar += _PARTIAL_BLOCKS[part_idx]
            filled += 1
        bar += '░' * (bar_w - filled)

        if state == "active":
            tail = f"⇩ {s['speed']}" if s["speed"] else ""
        else:
            tail = s["stage"]
        label = s["label"][:label_w].ljust(label_w)
        tail = tail[:tail_w].ljust(tail_w)
        return (f"{icon} {CYAN}{label}{CLR} {WHITE}│{CLR}{bar_color}{bar}{CLR}{WHITE}│{CLR} "
                f"{BOLD}{pct:>5.1f}%{CLR} {WHITE}{tail}{CLR}")

    def _build_lines(self, final=False):
        try:
            size = shutil.get_terminal_size((100, 30))
            cols, rows = size.columns, size.lines
        except Exception:
            cols, rows = 100, 30
        label_w, bar_w, tail_w = self._layout(cols)
        max_visible = max(1, rows - 4)
        lines = []
        with self._lock:
            for s in self._slots[:max_visible]:
                if final:
                    s["shown"] = s["target"]
                else:
                    diff = s["target"] - s["shown"]
                    if diff > 0:
                        s["shown"] = min(s["target"], s["shown"] + max(diff * 0.35, 0.2))
                lines.append(self._slot_line(s, label_w, bar_w, tail_w))
            if self.show_overall:
                done = sum(1 for v in self._status.values() if v)
                failed = sum(1 for v in self._status.values() if not v)
                total = str(self.total) if self.total > 0 else "?"
                text = "  " + tr("multi_overall", done=done, total=total)
                if failed:
                    text += "  " + tr("multi_failed", n=failed)
                lines.append(text)
        return lines

    def _draw(self, final=False):
        lines = self._build_lines(final=final)
        buf = []
        if self._drawn_lines:
            buf.append(f"\033[{self._drawn_lines}A")
        for ln in lines:
            buf.append(f"\r\033[K{ln}\n")
        buf.append("\033[J")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()
        self._drawn_lines = len(lines)

AUDIO_VIDEO_EXTENSIONS = (".mp3", ".wav", ".mp4", ".m4a", ".flac", ".webm", ".ogg", ".opus", ".mkv", ".weba")
INCOMPLETE_EXTENSIONS = (".part", ".ytdl", ".temp", ".ffmpeg", ".crdownload")

def get_media_files_snapshot(path):
    # ВАЖНО: возвращает {имя_файла: (размер, mtime_ns)}, а НЕ просто
    # множество имён. При включённом --force-overwrites (см.
    # build_common_ytdlp_args) повторная загрузка того же трека
    # пересоздаёт файл с ТЕМ ЖЕ именем — раньше снимок хранил только
    # имена, поэтому сравнение "после - до" давало пустое множество
    # (имя ведь не новое), и успешно перезаписанный файл ошибочно
    # считался "не сохранённым". Сравнение по (размер, mtime) отличает
    # пересозданный файл от нетронутого.
    try:
        snapshot = {}
        for f in os.listdir(path):
            low = f.lower()
            if not low.endswith(AUDIO_VIDEO_EXTENSIONS) or low.endswith(INCOMPLETE_EXTENSIONS):
                continue
            try:
                st = os.stat(os.path.join(path, f))
                snapshot[f] = (st.st_size, st.st_mtime_ns)
            except OSError:
                continue
        return snapshot
    except Exception:
        return {}

def diff_media_snapshots(before, after):
    """Имена файлов, которые появились заново или изменились (перезаписаны) между двумя снимками."""
    changed = set()
    for name, meta in after.items():
        if name not in before or before[name] != meta:
            changed.add(name)
    return changed

def execute_and_stream_output(cmd, platform, expected_streams=1):
    files_before = get_media_files_snapshot(SAVE_PATH)

    try:
        process = subprocess.Popen(
            cmd, cwd=SAVE_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, encoding='utf-8', errors='ignore', bufsize=1
        )
    except FileNotFoundError:
        stop_anim()
        raise
    except Exception as e:
        stop_anim()
        print(tr("popen_err", e=e))
        log_line(f"Popen error: {e}")
        return False, False, True, False

    # Спиннер (start_anim(tr("starting"))), уже запущенный вызывающей
    # стороной, раньше гасился здесь же — ДО того как процесс успевал
    # вывести хоть одну строку. yt-dlp/spotdl могут по несколько секунд
    # молча резолвить форматы или искать трек в базе, и всё это время
    # экран оставался абсолютно пустым (создавая впечатление, что
    # анимации вообще нет), пока внезапно не появлялось "Загрузка
    # завершена". Теперь спиннер продолжает крутиться до первой
    # содержательной строки, а затем снова включается на каждой "тихой"
    # паузе между этапами (извлечение аудио, обложка, теги и т.п.) —
    # и выключается только на время, пока реально идут процентные
    # обновления прогресс-бара (чтобы не спорить за одну и ту же строку).
    anim_text = tr("starting")
    anim_on = True

    bar_open = False    # True, пока курсор стоит в конце незавершённой строки с баром

    def announce(text):
        # ВАЖНО: раньше здесь был print(text), а затем start_anim(text) с ТЕМ ЖЕ
        # текстом — каждый этап ("Склейка...", "Сохранение метаданных...")
        # выводился дважды подряд. Теперь текст рисует только спиннер (он же
        # печатает итоговую строку при остановке); здесь лишь сохраняем отступы:
        # ведущие "\n" из перевода и перенос строки после недорисованного бара.
        nonlocal anim_on, anim_text, bar_open
        stop_anim()
        lead = len(text) - len(text.lstrip("\n"))
        if bar_open:
            sys.stdout.write("\n")
            bar_open = False
            lead -= 1
        if lead > 0:
            sys.stdout.write("\n" * lead)
        sys.stdout.flush()
        anim_text = text
        start_anim(anim_text)
        anim_on = True

    def pause_anim_for_progress():
        nonlocal anim_on
        if anim_on:
            stop_anim()
            anim_on = False

    current_track_num = 0
    has_errors = False
    # ВАЖНО: в журнал ошибок больше НЕ попадают строки прогресса. Раньше при
    # сотнях строк "[download] xx%" в секунду реальные сообщения об ошибках
    # (и "Requested format is not available") вытеснялись из 15-строчного
    # буфера, и повторная попытка с другим клиентом не запускалась.
    error_logs = collections.deque(maxlen=15)
    retryable_seen = False
    already_seen = False
    cookie_seen = False

    tracker = TrackProgress(expected_streams)
    last_draw_t = 0.0
    last_drawn_pct = -1.0

    def draw_progress(pct, speed_text, label_num):
        # Не чаще ~10 раз/с и только если значение реально изменилось —
        # меньше мерцания и системных вызовов записи в консоль.
        nonlocal last_draw_t, last_drawn_pct
        now = time.monotonic()
        if pct == last_drawn_pct:
            return
        if pct < 100.0 and now - last_draw_t < 0.1:
            return
        nonlocal bar_open
        last_draw_t = now
        last_drawn_pct = pct
        render_progress_bar(pct, tr("downloading_num", num=label_num if label_num else 1), speed_text)
        bar_open = True

    while True:
        line = process.stdout.readline()
        if not line:
            break    # EOF: процесс закрыл вывод (раньше здесь был холостой цикл с нагрузкой на CPU)

        line_str = line.strip()
        if not line_str:
            continue

        prog = parse_progress_line(line_str) if platform in ("YouTube", "SoundCloud") else None
        if prog is None:
            error_logs.append(line_str)
            if "ERROR:" in line_str or "Failed" in line_str:
                has_errors = True
            if is_retryable_ytdlp_error(line_str):
                retryable_seen = True
            low_line = line_str.lower()
            if ("already exists" in low_line or "skipping" in low_line
                    or "already downloaded" in low_line or "already been downloaded" in low_line):
                already_seen = True
            if not cookie_seen and has_cookie_issue([line_str]):
                cookie_seen = True

        if "[download]" in line_str and "Downloading item" in line_str:
            match_item = _RE_ITEM.search(line_str)
            if match_item:
                current_track_num = match_item.group(1)
                total_tracks = match_item.group(2)
                # Новый трек плейлиста — новый независимый прогресс.
                tracker = TrackProgress(expected_streams)
                last_drawn_pct = -1.0
                announce(tr("playlist_track", curr=current_track_num, total=total_tracks))

        if platform in ["YouTube", "SoundCloud"]:
            if "format(s):" in line_str:
                fm = _RE_FORMATS.search(line_str)
                if fm:
                    tracker.set_expected(len(fm.group(1).split("+")))
            elif "[download] Destination:" in line_str:
                tracker.new_stream()

            if prog is not None:
                pause_anim_for_progress()
                pct = tracker.update(prog[0], prog[1])
                draw_progress(pct, tracker.speed_text, current_track_num)
            elif "already been downloaded" in line_str:
                tracker.finish()
            else:
                stage = classify_post_stage(line_str)
                if stage:
                    # Скачивание закончено — доводим бар до 100% и объявляем этап.
                    # Именно этот промежуток (склейка видео+аудио, вшивание обложки
                    # и тегов — каждый раз полная перепаковка файла ffmpeg) раньше
                    # выглядел как "бар завис на последних процентах".
                    if tracker.started:
                        pause_anim_for_progress()
                        draw_progress(tracker.finish(), tracker.speed_text, current_track_num)
                    else:
                        tracker.finish()
                    if stage == "stage_merging":
                        announce(tr("merge_streams"))
                    elif stage == "stage_audio":
                        announce(tr("extract_audio"))
                    elif stage == "stage_cover":
                        announce(tr("process_cover"))
                    elif stage == "stage_meta":
                        announce(tr("save_meta"))

        elif platform == "Spotify":
            if "Fetching" in line_str or "Searching" in line_str or "Found" in line_str:
                if anim_text != tr("fetching_db"):
                    announce(tr("fetching_db"))
            elif "Downloading" in line_str or "Downloaded" in line_str:
                match = re.search(r'(\d+)%', line_str)
                # ВАЖНО: раньше при отсутствии "%" в строке бар рисовался на 100%
                # (по умолчанию), и тут же откатывался на реальные 40–60% в
                # следующей строке — отсюда "дёргания" на Spotify. Теперь строка
                # без процента бар не трогает, а полные 100% рисуются только для
                # "Downloaded".
                if match or "Downloaded" in line_str:
                    pause_anim_for_progress()
                    pct = float(match.group(1)) if match else 100.0
                    speed_match = re.search(r'([\d.]+\s?[KMG]?i?B/s)', line_str, re.IGNORECASE)
                    speed_text = speed_match.group(1) if speed_match else ""
                    render_progress_bar(pct, tr("download_audio"), speed_text)
            elif "Converting" in line_str or "Processing" in line_str:
                announce(tr("applying_tags"))

    stop_anim()
    returncode = process.wait()

    # Процесс завершился успешно, а бар так и не дошёл до 100% (один поток без
    # этапов постобработки в выводе) — дорисовываем.
    if platform in ("YouTube", "SoundCloud") and tracker.started and last_drawn_pct < 100.0 and returncode == 0:
        render_progress_bar(tracker.finish(), tr("downloading_num", num=current_track_num if current_track_num else 1), tracker.speed_text)
        bar_open = True

    format_not_available = retryable_seen or any(is_retryable_ytdlp_error(l) for l in error_logs)
    files_after = get_media_files_snapshot(SAVE_PATH)
    new_files = diff_media_snapshots(files_before, files_after)
    already_had_file = already_seen or any(
        ("already exists" in l.lower()) or ("skipping" in l.lower()) or ("already downloaded" in l.lower()) or ("already been downloaded" in l.lower())
        for l in error_logs
    )
    disk_confirmed = bool(new_files) or already_had_file

    for l in error_logs:
        log_line(l)

    cookie_issue = cookie_seen or has_cookie_issue(error_logs)
    fs_permission_issue = has_fs_permission_issue(error_logs)

    if not disk_confirmed:
        print(tr("files_not_saved"))
        for err_line in error_logs:
            if "ETA" not in err_line:
                print(f"{RED} > {err_line}{CLR}")
        if cookie_issue:
            print_cookie_issue_hint()
        elif fs_permission_issue:
            print_fs_permission_hint()
        return False, format_not_available, has_errors, cookie_issue

    if new_files:
        print(tr("files_saved", count=len(new_files)))

    return True, format_not_available, has_errors, cookie_issue

PLAYER_CLIENT_TIERS = (
    # ВАЖНО: раньше уровень 0 был "ios,tv_simply" в предположении, что эти
    # клиенты "обычно не требуют PO Token". Это устарело: по актуальной
    # PO Token Guide yt-dlp ios требует PO Token для GVS/Player, а
    # tv_simply — PO Token для GVS. Раньше это не было заметно, потому
    # что скрипт получал от этих клиентов ТОЛЬКО старый слитый формат
    # "18" (жёстко 360p) — единственный, что отдаётся без токена — и
    # тихо на нём и оставался. Как только форматы, требующие токена,
    # стали видны yt-dlp, попытка их реально скачать стала падать с
    # HTTP 403 (нет токена — нет доступа), а не улучшать качество.
    # "default" отдаёт выбор клиента встроенной логике самого yt-dlp,
    # которая поддерживается мейнтейнерами и уже сама уходит от клиентов,
    # требующих токен, когда это возможно — поэтому теперь это основной,
    # самый надёжный вариант.
    "default",                # Уровень 0 (основной): встроенный выбор клиента yt-dlp.
    "tv_simply,web_safari",   # Уровень 1 (резервный): другой набор клиентов, если
                              # основной не подошёл для конкретного видео.
    "ios,tv_simply",          # Уровень 2 (последний резерв): оставлен на случай видео,
                              # для которых даже это неожиданно сработает лучше.
)

def build_common_ytdlp_args(tier=0, no_browser_cookies=False):
    ffmpeg_target = FFMPEG_DIR if FFMPEG_DIR else "ffmpeg"
    tier = max(0, min(tier, len(PLAYER_CLIENT_TIERS) - 1))
    player_clients = PLAYER_CLIENT_TIERS[tier]
    args = [
        "--ffmpeg-location", ffmpeg_target,
        "--ignore-errors",
        "--embed-metadata",
        "--parse-metadata", "%(artist,uploader)s:artist",
        "--parse-metadata", "%(artist,uploader)s:album_artist",
        "--parse-metadata", "%(album)s:album",
        "--windows-filenames",
        # ВАЖНО: см. комментарий у PLAYER_CLIENT_TIERS — ограничение по
        # высоте (max_height) реально работает только когда yt-dlp
        # выбирает клиент, отдающий форматы БЕЗ требования PO Token
        # (Tier 0 = "default"). Флаг "formats=missing_pot" здесь
        # намеренно НЕ используется: он заставляет yt-dlp показывать
        # форматы, требующие токена, которого у нас нет, — из-за чего
        # выбирался, например, 1080p-формат, но его реальное скачивание
        # падало с HTTP 403 (см. лог "Download aborted... status=403").
        "--extractor-args", f"youtube:player_client={player_clients}",
        "--remote-components", "ejs:github",
        "--force-overwrites",
        "--retries", "10",
        "--fragment-retries", "10",
        # Короткие паузы между повторами: обычные HTTP-ретраи — 2 с, для
        # фрагментов — экспоненциально 1..8 с (раньше везде стояло фиксированное
        # "3", и вместе с 20-секундным socket-timeout одно зависание стоило минуты).
        "--retry-sleep", "2",
        "--retry-sleep", "fragment:exp=1:8",
        "--socket-timeout", SOCKET_TIMEOUT,
        # Каждое обновление прогресса — отдельная строка (а не "\r"-перезапись) и
        # не чаще 4 раз в секунду: при 16 параллельных фрагментах yt-dlp иначе
        # шлёт сотни строк/с, которые мы зря разбираем регулярками.
        "--newline",
        "--progress-delta", "0.25",
    ]
    if THROTTLED_RATE and THROTTLED_RATE != "0":
        args.extend(["--throttled-rate", THROTTLED_RATE])
    # ВАЖНО: раньше здесь стоял "--no-warnings", который скрывал причину
    # неудачи конкретного клиента (например "Sign in to confirm your age",
    # "requires purchase", предупреждения о PO Token и т.п.) — в логе
    # оставалась только финальная общая ошибка "Requested format is not
    # available" без единой зацепки, почему именно. Убрали флаг, чтобы
    # реальная причина попадала в лог и её можно было увидеть и
    # диагностировать, а не гадать вслепую.
    args.extend(get_speed_args())
    args.extend(get_cookies_args(allow_browser_fallback=not no_browser_cookies))
    return args

def _format_specific_args(file_type, retry, max_height=None):
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
        # ВАЖНО: раньше здесь была жёстко зашита высота "height<=1080" —
        # из-за этого видео, у которых реальное максимальное качество
        # выше 1080p (1440p/4K), принудительно урезались, а если у
        # конкретного ролика вообще не было отдельного 1080p-варианта,
        # загрузка могла падать целиком. Теперь потолок качества берётся
        # из max_height, который выбирает пользователь в меню качества
        # (choose_video_quality), а верхний пункт этого меню всегда равен
        # РЕАЛЬНОМУ максимальному качеству именно этого видео
        # (probe_max_video_height). Если max_height не задан (пользователь
        # не выбирал качество или определить его не удалось) — ограничение
        # по высоте не накладывается вовсе, берётся лучшее из доступного.
        if max_height:
            fmt = (
                f"bv*[height<={max_height}]+ba/b[height<={max_height}]/best[height<={max_height}]/best"
                if retry else
                f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b/best"
            )
        else:
            fmt = "best" if retry else "bv*+ba/b/best"
        return (
            ["-f", fmt, "--merge-output-format", "mp4"],
            # ВАЖНО: раньше сортировка кодеков была "av01:vp9:h264" — то
            # есть AV1 в приоритете. "--merge-output-format mp4" задаёт
            # только КОНТЕЙНЕР (расширение файла), а не кодек видео
            # внутри — поэтому получался файл .mp4, но с видеодорожкой
            # AV1, которую многие плееры/редакторы/мессенджеры не умеют
            # проигрывать как обычный mp4 (ожидают H.264). Теперь h264
            # стоит первым, поэтому при прочих равных (то же разрешение)
            # выбирается H.264-поток — совместимый mp4, как и просили.
            ["--embed-thumbnail", "--format-sort", "res,fps,hdr:12,vcodec:h264:vp9:av01,br,size"],
        )

QUALITY_TIERS = (2160, 1440, 1080, 720, 480, 360, 240)

def probe_max_video_height(ytdlp_bin, url):
    """
    Определяет РЕАЛЬНОЕ максимальное доступное качество (высоту видео в
    пикселях) для указанной ссылки, опрашивая yt-dlp БЕЗ скачивания
    самого файла (только метаданные формата "bestvideo"). Для плейлиста
    берётся первый элемент — этого достаточно, чтобы понять исходное
    максимальное разрешение ролика/канала для меню выбора качества.

    Возвращает int (высоту в пикселях) или None, если определить не
    удалось (например, сетевая ошибка, недоступное видео, не-YouTube
    ссылка) — в этом случае вызывающий код должен использовать вариант
    "без ограничения по высоте" (лучшее из доступного).
    """
    cmd = [
        ytdlp_bin, "--no-warnings", "--ignore-errors",
        "--playlist-items", "1",
        "-f", "bestvideo/best",
        "--print", "%(height)s",
    ]
    cmd.extend(get_cookies_args())
    cmd.append(url)
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, encoding='utf-8', errors='ignore', timeout=30
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                height = int(line)
                if height > 0:
                    return height
    except Exception as e:
        log_line(f"Не удалось определить максимальное качество видео: {e}")
    return None

def choose_video_quality(ytdlp_bin, url):
    """
    Показывает пользователю меню выбора качества MP4 сразу после выбора
    формата (пункт "3"). Верхний пункт меню ВСЕГДА равен реальному
    максимальному качеству именно этого видео (через
    probe_max_video_height), а не захардкоженному значению — поэтому,
    например, 4K-ролик предложит "2160p (максимальное)", а не будет
    молча урезан до 1080p, как это было раньше.

    Возвращает:
      - int (высота в пикселях) — выбранный пользователем потолок качества,
        который затем передаётся в build_ytdlp_command* как max_height;
      - None — если определить максимальное качество не удалось; в этом
        случае используется наилучшее доступное качество без ограничения.
    """
    start_anim(tr("quality_probing"), style="dots")
    max_height = probe_max_video_height(ytdlp_bin, url)
    stop_anim()

    if not max_height:
        print(tr("quality_probe_failed"))
        return None

    options = [h for h in QUALITY_TIERS if h < max_height]
    options.insert(0, max_height)

    print(tr("quality_menu_title", height=max_height))
    for i, h in enumerate(options, start=1):
        if h == max_height:
            print(f"  {GREEN}{i}.{CLR} {WHITE}{h}p{CLR} ({tr('quality_max_label')})")
        else:
            print(f"  {GREEN}{i}.{CLR} {WHITE}{h}p{CLR}")
    print(tr("separator"))

    while True:
        raw = input(tr("quality_prompt", max_num=len(options))).strip()
        if not raw:
            return options[0]
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        print(tr("quality_invalid"))

def build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, tier=0, max_height=None, no_browser_cookies=False):
    output_template = "%(playlist_index)02d - %(title)s.%(ext)s" if is_playlist else "%(title)s.%(ext)s"
    pre_fmt, post_fmt = _format_specific_args(file_type, tier > 0, max_height)
    cmd = [ytdlp_bin] + pre_fmt + ["-o", output_template] + build_common_ytdlp_args(tier, no_browser_cookies) + post_fmt
    if not is_playlist:
        cmd.append("--no-playlist")
    cmd.append(url)
    return cmd

def build_ytdlp_command_multi(ytdlp_bin, urls, file_type, tier=0, max_height=None, no_browser_cookies=False):
    output_template = "%(title)s.%(ext)s"
    pre_fmt, post_fmt = _format_specific_args(file_type, tier > 0, max_height)
    cmd = [ytdlp_bin] + pre_fmt + ["-o", output_template] + build_common_ytdlp_args(tier, no_browser_cookies) + post_fmt
    cmd.append("--no-playlist")
    cmd.extend(urls)
    return cmd

def build_ytdlp_command_urls(ytdlp_bin, urls, file_type, tier=0, max_height=None, no_browser_cookies=False):
    # Как build_ytdlp_command_multi, но без --no-playlist: если среди
    # переданных ссылок окажется плейлист, yt-dlp обработает его целиком.
    output_template = "%(title)s.%(ext)s"
    pre_fmt, post_fmt = _format_specific_args(file_type, tier > 0, max_height)
    cmd = [ytdlp_bin] + pre_fmt + ["-o", output_template] + build_common_ytdlp_args(tier, no_browser_cookies) + post_fmt
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

def _worker_label(worker_id, track_no=None, item=None):
    label = tr("thread_label", id=worker_id)
    if track_no is not None:
        label += f" · #{track_no}"
    if item:
        label += f" ({item[0]}/{item[1]})"
    return label

def execute_playlist_worker(cmd, worker_id, print_lock, shared_error_logs,
                            mp=None, slot=None, track_no=None, expected_streams=1):
    """Запускает один процесс yt-dlp и ведёт ОДИН бар в строке `slot` общего блока `mp`.

    Возвращает (format_not_available, has_error, cookie_issue) — как и раньше.
    """
    slot = (worker_id - 1) if slot is None else slot
    base_track_no = track_no
    # Ключ статуса трека в общем счётчике. В резервном режиме (без списка
    # ссылок) номера элементов у воркеров пересекаются, поэтому ключ — по воркеру.
    key_base = base_track_no if base_track_no is not None else ("w", worker_id)
    # Если процесс обрабатывает плейлист ("Downloading item N of M"), каждый
    # элемент — отдельный трек со своим ключом статуса и своим бар-состоянием.
    item_mode = False
    item_failed = False
    cur_item = None

    def _label(item=None):
        return _worker_label(worker_id, base_track_no, item)

    try:
        try:
            process = subprocess.Popen(
                cmd, cwd=SAVE_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, encoding='utf-8', errors='ignore', bufsize=1
            )
        except Exception as e:
            with print_lock:
                shared_error_logs.append(tr("thread_start_err", id=worker_id, e=e))
            if mp:
                mp.begin_track(slot, _label())
                mp.finish_track(slot, key_base, False)
            return False, True, False

        if mp:
            mp.begin_track(slot, _label())

        tracker = TrackProgress(expected_streams)
        local_logs = collections.deque(maxlen=15)
        format_not_available = False
        has_error = False
        cookie_issue = False

        while True:
            line = process.stdout.readline()
            if not line:
                break    # EOF — без холостого цикла, пока процесс дозавершается
            line_str = line.strip()
            if not line_str:
                continue

            prog = parse_progress_line(line_str)

            # Строки прогресса в журнал не пишем (иначе они вытесняют реальные ошибки).
            if prog is None:
                local_logs.append(line_str)

                if is_retryable_ytdlp_error(line_str):
                    format_not_available = True

                if "ERROR:" in line_str or "Failed" in line_str:
                    has_error = True
                    item_failed = True

                if not cookie_issue and has_cookie_issue([line_str]):
                    cookie_issue = True

            if prog is not None:
                pct = tracker.update(prog[0], prog[1])
                if mp:
                    mp.update(slot, pct, tracker.speed_text)
                continue

            if "Downloading item" in line_str:
                m_item = _RE_ITEM.search(line_str)
                if m_item and mp:
                    n, total_items = int(m_item.group(1)), int(m_item.group(2))
                    # Предыдущий элемент плейлиста закончился — фиксируем его итог.
                    if cur_item is not None:
                        mp.finish_track(slot, (key_base, cur_item), not item_failed)
                    elif not item_mode and base_track_no is not None and total_items > 1:
                        # Одна ссылка оказалась плейлистом — в общем счёте это теперь N треков.
                        mp.add_total(total_items - 1)
                    item_mode = True
                    cur_item = n
                    item_failed = False
                    tracker = TrackProgress(expected_streams)
                    mp.begin_track(slot, _label((n, total_items)))
                continue

            if "format(s):" in line_str:
                fm = _RE_FORMATS.search(line_str)
                if fm:
                    tracker.set_expected(len(fm.group(1).split("+")))
                continue

            if "[download] Destination:" in line_str:
                tracker.new_stream()
                continue

            if "already been downloaded" in line_str:
                tracker.finish()
                if mp:
                    mp.set_stage(slot, tr("stage_exists"))
                continue

            stage = classify_post_stage(line_str)
            if stage and mp:
                tracker.finish()
                mp.set_stage(slot, tr(stage))

        returncode = process.wait()
        cookie_issue = cookie_issue or has_cookie_issue(local_logs)

        if mp:
            if item_mode and cur_item is not None:
                mp.finish_track(slot, (key_base, cur_item), returncode == 0 and not item_failed)
            elif not item_mode:
                mp.finish_track(slot, key_base, returncode == 0)

        with print_lock:
            shared_error_logs.extend(local_logs)
        return format_not_available, has_error, cookie_issue

    except Exception as e:
        with print_lock:
            shared_error_logs.append(tr("thread_err", id=worker_id, e=e))
        if mp:
            mp.finish_track(slot, key_base, False)
        return False, True, False

def run_tracks_parallel(ytdlp_bin, urls, file_type, builder, tier=0, max_height=None,
                        no_browser_cookies=False, shared_error_logs=None, print_lock=None,
                        numbering=None):
    """Параллельно качает `urls` — по одному процессу yt-dlp на ссылку.

    Ссылки раздаются воркерам через общую очередь: поток, быстро закончивший
    свой трек, сразу берёт следующий, а один "тяжёлый" трек не держит позади
    себя половину списка (как было при статическом делении entries[i::workers]).
    Каждый воркер ведёт одну строку-бар в общем блоке MultiProgress.

    Возвращает {url: (format_not_available, has_error, cookie_issue)}.
    """
    if not urls:
        return {}
    shared_error_logs = shared_error_logs if shared_error_logs is not None else []
    print_lock = print_lock or threading.Lock()
    numbering = numbering or {u: i for i, u in enumerate(urls, start=1)}
    workers = max(1, min(PLAYLIST_WORKERS, len(urls)))
    expected = expected_stream_count(file_type, tier, max_height)

    work_q = queue.Queue()
    for u in urls:
        work_q.put(u)
    results = {}
    results_lock = threading.Lock()

    # ВАЖНО: команды собираются ЗАРАНЕЕ, в основном потоке и до старта блока
    # прогресса. build_common_ytdlp_args -> get_cookies_args может напечатать
    # предупреждение про cookies; если это случится из потока воркера уже
    # посреди живого блока, лишние строки собьют перерисовку на месте.
    cmds = {u: builder(ytdlp_bin, [u], file_type, tier=tier, max_height=max_height,
                       no_browser_cookies=no_browser_cookies) for u in urls}
    mp = MultiProgress(workers, total_tracks=len(urls))

    def worker(slot):
        try:
            while True:
                try:
                    url = work_q.get_nowait()
                except queue.Empty:
                    return
                r = execute_playlist_worker(cmds[url], slot + 1, print_lock, shared_error_logs,
                                            mp=mp, slot=slot, track_no=numbering.get(url),
                                            expected_streams=expected)
                with results_lock:
                    results[url] = r
        finally:
            mp.set_idle(slot)

    mp.start()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(worker, s) for s in range(workers)]
            for f in futures:
                f.result()
    finally:
        mp.stop()
    return results

def _flags_from_results(results):
    """(format_not_available, has_errors, cookie_issue) по словарю результатов."""
    if not results:
        return False, True, False
    vals = list(results.values())
    return any(r[0] for r in vals), any(r[1] for r in vals), any(r[2] for r in vals)

def process_playlist_parallel(ytdlp_bin, url, file_type, platform, tier=0, max_height=None, no_browser_cookies=False):
    stop_anim()
    start_anim(tr("playlist_fetch"), style="dots")
    entries = extract_playlist_video_urls(ytdlp_bin, url)
    stop_anim()

    files_before = get_media_files_snapshot(SAVE_PATH)
    print_lock = threading.Lock()
    shared_error_logs = []

    if entries:
        entries = list(dict.fromkeys(entries))    # дубли в плейлисте не качаем дважды
        workers = max(1, min(PLAYLIST_WORKERS, len(entries)))
        print(tr("playlist_found", count=len(entries), workers=workers))
        numbering = {u: i for i, u in enumerate(entries, start=1)}

        def run(batch, t):
            return run_tracks_parallel(
                ytdlp_bin, batch, file_type, build_ytdlp_command_multi, tier=t,
                max_height=max_height, no_browser_cookies=no_browser_cookies,
                shared_error_logs=shared_error_logs, print_lock=print_lock, numbering=numbering)

        results = run(entries, tier)

        # Резервные клиенты YouTube перебираем только для ТЕХ треков, что упали
        # с ошибкой формата/сессии. Раньше повтор перекачивал весь плейлист
        # заново (а при --force-overwrites — ещё и перезаписывал готовые файлы).
        failed = [u for u in entries if results.get(u, (False, True, False))[0]]
        cur_tier = tier + 1
        while failed and cur_tier < len(PLAYER_CLIENT_TIERS):
            print(tr("fallback_start"))
            clear_ytdlp_cache(ytdlp_bin)
            retry = run(failed, cur_tier)
            results.update(retry)
            failed = [u for u in failed if retry.get(u, (False, True, False))[0]]
            cur_tier += 1

        _, has_errors, cookie_issue = _flags_from_results(results)
        # Уровни клиентов исчерпаны внутри — внешнему циклу повторять нечего.
        format_not_available = False
    else:
        workers = PLAYLIST_WORKERS
        print(tr("playlist_fallback", workers=workers))
        expected = expected_stream_count(file_type, tier, max_height)
        # Команды — до старта живого блока (см. комментарий в run_tracks_parallel).
        worker_cmds = []
        for i in range(workers):
            cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist=True, tier=tier, max_height=max_height, no_browser_cookies=no_browser_cookies)
            cmd.extend(["--playlist-items", f"{i + 1}::{workers}"])
            worker_cmds.append(cmd)
        mp = MultiProgress(workers, total_tracks=0)
        mp.start()
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = []
                for i, cmd in enumerate(worker_cmds):
                    futures.append(pool.submit(execute_playlist_worker, cmd, i + 1, print_lock, shared_error_logs,
                                               mp, i, None, expected))
                results = {i: f.result() for i, f in enumerate(futures)}
        finally:
            for i in range(workers):
                mp.set_idle(i)
            mp.stop()
        format_not_available, has_errors, cookie_issue = _flags_from_results(results)

    files_after = get_media_files_snapshot(SAVE_PATH)
    new_files = diff_media_snapshots(files_before, files_after)
    already_had_file = any(
        ("already exists" in l.lower()) or ("skipping" in l.lower()) or ("already downloaded" in l.lower()) or ("already been downloaded" in l.lower())
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
        if cookie_issue:
            print_cookie_issue_hint()

    return disk_confirmed, format_not_available, has_errors, cookie_issue

def download_urls_parallel(ytdlp_bin, urls, file_type, max_height=None):
    stop_anim()
    # Та же система, что используется для параллельной загрузки плейлиста
    # (run_tracks_parallel), но воркерам раздаются не элементы одного
    # плейлиста, а разные ссылки, введённые пользователем.
    files_before = get_media_files_snapshot(SAVE_PATH)
    print_lock = threading.Lock()
    shared_error_logs = []
    numbering = {u: i for i, u in enumerate(urls, start=1)}

    def run_batch(batch_urls, tier, no_browser_cookies=False):
        return run_tracks_parallel(
            ytdlp_bin, batch_urls, file_type, build_ytdlp_command_urls, tier=tier,
            max_height=max_height, no_browser_cookies=no_browser_cookies,
            shared_error_logs=shared_error_logs, print_lock=print_lock, numbering=numbering)

    print(tr("playlist_found", count=len(urls), workers=max(1, min(PLAYLIST_WORKERS, len(urls)))))
    no_browser_cookies = False
    results = run_batch(urls, tier=0, no_browser_cookies=no_browser_cookies)

    # Если проблема именно в чтении cookies из браузера (например, Chrome
    # открыт и блокирует свою базу), переключение "уровней клиента"
    # YouTube тут не поможет — причина не в клиенте, а в самих cookies.
    # Поэтому один раз пробуем повторить БЕЗ cookies — но только те ссылки,
    # которые на этом упали (раньше перекачивался весь пакет целиком).
    cookie_failed = [u for u in urls if results.get(u, (False, True, False))[2]]
    if cookie_failed and not no_browser_cookies and not os.path.exists(COOKIES_PATH):
        print(tr("cookie_retry_no_auth"))
        no_browser_cookies = True
        results.update(run_batch(cookie_failed, tier=0, no_browser_cookies=no_browser_cookies))

    # Перебираем ВСЕ уровни клиентов (см. PLAYER_CLIENT_TIERS) по очереди,
    # а не только один резервный вариант, — так шанс скачать конкретное
    # проблемное видео (возрастное ограничение, нестандартный набор
    # форматов и т.п.) сохраняется даже если первый резерв тоже не подошёл.
    # Повторяются только упавшие ссылки: уже скачанные не трогаем.
    failed = [u for u in urls if results.get(u, (False, True, False))[0]]
    tier = 1
    while failed and tier < len(PLAYER_CLIENT_TIERS):
        print(tr("fallback_start"))
        clear_ytdlp_cache(ytdlp_bin)
        retry = run_batch(failed, tier=tier, no_browser_cookies=no_browser_cookies)
        results.update(retry)
        failed = [u for u in failed if retry.get(u, (False, True, False))[0]]
        tier += 1

    # has_errors считаем по ИТОГОВЫМ результатам (с учётом успешных повторов);
    # раньше учитывался только последний проход.
    _, has_errors, _ = _flags_from_results(results)

    files_after = get_media_files_snapshot(SAVE_PATH)
    new_files = diff_media_snapshots(files_before, files_after)
    already_had_file = any(
        ("already exists" in l.lower()) or ("skipping" in l.lower()) or ("already downloaded" in l.lower()) or ("already been downloaded" in l.lower())
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

    return disk_confirmed, has_errors

def start_multi_download_process(urls, file_type, ytdlp_bin, max_height=None):
    cleaned = []
    for u in urls:
        u = clean_url(u)
        if u and u not in cleaned:
            cleaned.append(u)

    spotify_urls = []
    other_urls = []
    for u in cleaned:
        platform = get_platform(u)
        if platform == "Spotify":
            spotify_urls.append(u)
        elif platform:
            other_urls.append(u)
        else:
            print(tr("unsupported_platform"))

    if not spotify_urls and not other_urls:
        return

    print(tr("multi_urls_summary", count=len(spotify_urls) + len(other_urls), fmt=file_type.upper()))
    start_anim(tr("starting"))
    _t0 = time.time()

    success = True
    has_errors = False

    if other_urls:
        ok, errs = download_urls_parallel(ytdlp_bin, other_urls, file_type, max_height=max_height)
        success = success and ok
        has_errors = has_errors or errs

    for u in spotify_urls:
        start_download_process(u, file_type, ytdlp_bin, max_height=max_height, show_header=False)

    if other_urls:
        _elapsed = int(time.time() - _t0)
        _mins, _secs = divmod(_elapsed, 60)
        _time_str = f"{_mins}м {_secs}с" if CURRENT_LANG == "ru" else f"{_mins}m {_secs}s"
        print(tr("separator"))
        if success:
            if has_errors:
                print(tr("partial_success"))
            else:
                print(tr("success"))
            print(tr("saved_dir", path=SAVE_PATH))
            print(tr("result_time", elapsed=_time_str))
        else:
            print(tr("aborted"))
            if not os.path.exists(COOKIES_PATH):
                print(tr("aborted_cookie_hint"))
        print(tr("separator"))

def start_download_process(url, file_type, ytdlp_bin, max_height=None, show_header=True):
    url = clean_url(url)
    platform = get_platform(url)
    if not platform:
        print(tr("unsupported_platform"))
        return

    # show_header=False используется при пакетной загрузке нескольких ссылок
    # одного типа (например несколько Spotify-треков подряд из
    # start_multi_download_process) — источник и формат для всей пачки уже
    # были показаны один раз строкой выше ("multi_urls_summary"), и печатать
    # их заново перед каждым отдельным треком избыточно.
    if show_header:
        print(tr("source", platform=platform, fmt=file_type.upper()))
    start_anim(tr("starting"))
    _t0 = time.time()

    is_playlist = is_playlist_url(url)
    # Warn if URL contains both a video ID and a playlist ID
    try:
        _parsed_url = urlparse(url)
        _qs_url = parse_qs(_parsed_url.query)
        if "list" in _qs_url and "v" in _qs_url:
            stop_anim()
            print(tr("playlist_v_ignored"))
            start_anim(tr("starting"))
    except Exception:
        pass
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
            success, _, has_errors, _ = execute_and_stream_output(cmd, platform)
        except FileNotFoundError:
            print(tr("spotdl_not_found"))
            success = False
            has_errors = True

    else:
        tier = 0
        no_browser_cookies = False
        success, format_not_available, has_errors, cookie_issue = False, False, True, False

        if is_playlist and PLAYLIST_WORKERS > 1:
            success, format_not_available, has_errors, cookie_issue = process_playlist_parallel(ytdlp_bin, url, file_type, platform, tier=tier, max_height=max_height, no_browser_cookies=no_browser_cookies)
        else:
            cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, tier=tier, max_height=max_height, no_browser_cookies=no_browser_cookies)
            try:
                success, format_not_available, has_errors, cookie_issue = execute_and_stream_output(cmd, platform, expected_streams=expected_stream_count(file_type, tier, max_height))
            except FileNotFoundError:
                print(tr("ytdlp_not_found"))
                success = False
                format_not_available = False
                has_errors = True

        # Если браузерные cookies не читаются (например, Chrome открыт и
        # блокирует свою базу — "Could not copy Chrome cookie database"),
        # смена "уровня клиента" YouTube ниже никак не помогает: проблема
        # не в клиенте, а в самих cookies, и раньше скрипт просто сдавался
        # на этом этапе, даже если контент публичный и авторизация вообще
        # не нужна. Поэтому один раз пробуем повторить загрузку совсем
        # без cookies, прежде чем переходить к перебору клиентов.
        if not success and cookie_issue and not no_browser_cookies and not os.path.exists(COOKIES_PATH):
            print(tr("cookie_retry_no_auth"))
            no_browser_cookies = True
            if is_playlist and PLAYLIST_WORKERS > 1:
                success, format_not_available, has_errors, cookie_issue = process_playlist_parallel(ytdlp_bin, url, file_type, platform, tier=tier, max_height=max_height, no_browser_cookies=no_browser_cookies)
            else:
                cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, tier=tier, max_height=max_height, no_browser_cookies=no_browser_cookies)
                try:
                    success, format_not_available, has_errors, cookie_issue = execute_and_stream_output(cmd, platform, expected_streams=expected_stream_count(file_type, tier, max_height))
                except FileNotFoundError:
                    print(tr("ytdlp_not_found"))
                    success = False
                    format_not_available = False
                    has_errors = True

        # Перебираем ВСЕ уровни клиентов (PLAYER_CLIENT_TIERS) по очереди,
        # пока не получится либо не закончатся варианты. Раньше был всего
        # один резервный набор клиентов — если и он не подходил для
        # конкретного видео (возрастное ограничение, нестандартный набор
        # форматов и т.п.), скрипт сдавался. Теперь в конце цепочки есть
        # ещё "default" — встроенный в yt-dlp выбор клиента, который
        # поддерживают и обновляют мейнтейнеры под текущие защиты YouTube.
        tier += 1
        while not success and format_not_available and tier < len(PLAYER_CLIENT_TIERS):
            print(tr("fallback_start"))
            clear_ytdlp_cache(ytdlp_bin)
            if is_playlist and PLAYLIST_WORKERS > 1:
                success, format_not_available, has_errors, cookie_issue = process_playlist_parallel(ytdlp_bin, url, file_type, platform, tier=tier, max_height=max_height, no_browser_cookies=no_browser_cookies)
            else:
                retry_cmd = build_ytdlp_command(ytdlp_bin, url, file_type, is_playlist, tier=tier, max_height=max_height, no_browser_cookies=no_browser_cookies)
                try:
                    success, format_not_available, has_errors, cookie_issue = execute_and_stream_output(retry_cmd, platform, expected_streams=expected_stream_count(file_type, tier, max_height))
                except FileNotFoundError:
                    print(tr("ytdlp_not_found"))
                    success = False
                    has_errors = True
            tier += 1

    _elapsed = int(time.time() - _t0)
    _mins, _secs = divmod(_elapsed, 60)
    _time_str = f"{_mins}м {_secs}с" if CURRENT_LANG == "ru" else f"{_mins}m {_secs}s"

    print(tr("separator"))
    if success:
        if platform != "Spotify" and is_playlist and has_errors:
            print(tr("partial_success"))
        else:
            print(tr("success"))
        print(tr("saved_dir", path=SAVE_PATH))
        print(tr("result_time", elapsed=_time_str))
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
    # ── Log rotation: если лог > 1 МБ, архивируем ──
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1024 * 1024:
            bak = LOG_FILE + ".bak"
            try:
                if os.path.exists(bak):
                    os.remove(bak)
                os.rename(LOG_FILE, bak)
            except Exception:
                pass
    except Exception:
        pass

    ensure_save_directory()

    with ThreadPoolExecutor(max_workers=3) as pool:
        ytdlp_future = pool.submit(ensure_ytdlp)
        deno_future = pool.submit(ensure_deno)
        pool.submit(ensure_ffmpeg)
        ytdlp_bin = ytdlp_future.result()
        deno_future.result()

    threading.Thread(target=ensure_aria2c_background, daemon=True).start()

    # Обновление инструментов в фоне — не блокирует UI
    threading.Thread(target=update_tools, args=(ytdlp_bin,), daemon=True).start()
    threading.Thread(target=update_spotdl_dependencies_background, daemon=True).start()

    _BOX_W = 50
    _INNER = _BOX_W - 2

    while True:
        clear_screen()

        # ── Заголовок-рамка ──
        _subtitle = "Загрузчик медиа" if CURRENT_LANG == "ru" else "Media Downloader"
        _title = f"  \u25c6 NovaDL  v1.2.0  \u2014  {_subtitle}"
        _title_pad = max(0, _INNER - len(_title))
        print(f"{CYAN}\u2554{'=' * _INNER}\u2557{CLR}")
        print(f"{CYAN}\u2551{CLR}{BOLD}{CYAN}{_title}{' ' * _title_pad}{CYAN}\u2551{CLR}")
        print(f"{CYAN}\u255a{'=' * _INNER}\u255d{CLR}")
        print()

        # ── Статус ──
        _cookie_ok = os.path.exists(COOKIES_PATH)
        _cookie_icon = f"{GREEN}\u2713{CLR}" if _cookie_ok else f"{YELLOW}~{CLR}"
        _cookie_label = tr("cookie_active") if _cookie_ok else tr("cookie_browser")

        _ffmpeg_ok = bool(FFMPEG_DIR)
        _ffmpeg_icon = f"{GREEN}\u2713{CLR}" if _ffmpeg_ok else f"{RED}\u2717{CLR}"
        _ffmpeg_label = FFMPEG_DIR if FFMPEG_DIR else tr("ffmpeg_not_found_status")

        _lang_label = f"{GREEN}Русский (RU){CLR}" if CURRENT_LANG == "ru" else f"{GREEN}English (EN){CLR}"

        if CURRENT_LANG == "ru":
            _key_save, _key_cookie, _key_ffmpeg, _key_lang = "Сохранение", "Куки", "FFmpeg", "Язык"
        else:
            _key_save, _key_cookie, _key_ffmpeg, _key_lang = "Save path", "Cookies", "FFmpeg", "Language"

        _bullet = "\u25b8"
        print(f"  {WHITE}{_bullet} {_key_save:<12}{CLR} {YELLOW}{SAVE_PATH}{CLR}")
        print(f"  {WHITE}{_bullet} {_key_cookie:<12}{CLR} {_cookie_icon} {_cookie_label}")
        print(f"  {WHITE}{_bullet} {_key_ffmpeg:<12}{CLR} {_ffmpeg_icon} {_ffmpeg_label}")
        print(f"  {WHITE}{_bullet} {_key_lang:<12}{CLR} {_lang_label}")
        print()
        _hline = "\u2500" * _BOX_W
        print(f"{CYAN}{_hline}{CLR}")

        url_input = input(tr("url_prompt")).strip()
        if not url_input:
            break

        if url_input == '0':
            show_settings_menu()
            continue

        urls = url_input.split()

        # ── Определяем платформу и режим для отображения ──
        _first_clean = clean_url(urls[0])
        _platform_str = get_platform(_first_clean) or ("Неизвестно" if CURRENT_LANG == "ru" else "Unknown")
        if len(urls) > 1:
            _mode_str = tr("mode_multi")
        elif is_playlist_url(_first_clean):
            _mode_str = tr("mode_playlist")
        else:
            _mode_str = tr("mode_single")

        print()
        _plabel = tr("platform_label")
        _mlabel = tr("mode_label")
        _pipe = "\u2502"
        _hline2 = "\u2500" * _BOX_W
        print(f"  {WHITE}{_plabel}:{CLR} {CYAN}{_platform_str}{CLR}  {_pipe}  {WHITE}{_mlabel}:{CLR} {CYAN}{_mode_str}{CLR}")
        print(f"{CYAN}{_hline2}{CLR}")
        print(tr("choose_format"))
        print(tr("fmt_mp3"))
        print(tr("fmt_wav"))
        print(tr("fmt_mp4"))
        print(tr("separator"))

        choice = read_menu_choice()

        file_type = "mp3"
        if choice == '2': file_type = "wav"
        elif choice == '3': file_type = "mp4"

        # После выбора MP4 (пункт "3") запрашиваем у пользователя качество.
        # Верхний вариант меню всегда равен РЕАЛЬНОМУ максимальному
        # качеству именно этого видео (см. choose_video_quality /
        # probe_max_video_height) — раньше же качество было жёстко
        # ограничено 1080p независимо от того, что доступно на самом деле.
        # Для Spotify-ссылок качество видео не имеет смысла (spotdl всегда
        # отдаёт аудио), поэтому меню для них не показываем.
        max_height = None
        if choice == '3' and get_platform(urls[0]) != "Spotify":
            max_height = choose_video_quality(ytdlp_bin, urls[0])

        try:
            if len(urls) > 1:
                start_multi_download_process(urls, file_type, ytdlp_bin, max_height=max_height)
            else:
                start_download_process(urls[0], file_type, ytdlp_bin, max_height=max_height)
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
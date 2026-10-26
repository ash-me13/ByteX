import sys
import os
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import ctypes

logger = logging.getLogger("bytex.skills.resolver")

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

winreg = None
shell32 = None

if IS_WINDOWS:
    try:
        import winreg
        from ctypes import windll
        shell32 = windll.shell32
    except Exception as e:
        logger.warning(f"Failed to initialize Windows APIs in resolver: {e}")

class ResolutionStatus(str, Enum):
    FOUND = "FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"

@dataclass
class ApplicationRecord:
    display_name: str
    normalized_name: str
    aliases: List[str]
    target_type: str  # "shortcut" | "executable" | "protocol_uri" | "system_binary"
    target: str
    source: str
    proc_keywords: List[str]
    verified: bool = True

class UniversalApplicationResolver:
    """
    Universal Safe Windows Application Resolver.

    Responsibilities:
    1. Indexes trusted Windows application locations (Start Menu, Desktop, Registry App Paths, Built-ins, Protocol Handlers).
    2. Maps user intents and colloquial aliases (e.g. 'vs code' -> 'Visual Studio Code', 'chrome' -> 'Google Chrome').
    3. Guarantees zero execution of arbitrary AI-supplied paths or shell commands.
    4. Handles duplicates, confidence ranking, and genuine ambiguity detection.
    5. Caches indexed records with fast lookup and refresh capabilities.
    """

    CACHE_TTL_SECONDS = 300  # 5 minutes auto-refresh window

    def __init__(self):
        self._catalog: Dict[str, ApplicationRecord] = {}
        self._records: List[ApplicationRecord] = []
        self._alias_map: Dict[str, ApplicationRecord] = {}
        self._last_index_time: float = 0.0
        self.build_catalog()

    def build_catalog(self, force: bool = False):
        now = time.time()
        if not force and self._records and (now - self._last_index_time < self.CACHE_TTL_SECONDS):
            return

        self._catalog.clear()
        self._records.clear()
        self._alias_map.clear()

        if IS_MACOS:
            # 1. Standard Built-in macOS Applications
            macos_builtins = [
                ("calculator", "Calculator", "/System/Applications/Calculator.app", ["calculator", "calc"]),
                ("calc", "Calculator", "/System/Applications/Calculator.app", ["calculator", "calc"]),
                ("textedit", "TextEdit", "/System/Applications/TextEdit.app", ["textedit", "notepad"]),
                ("notepad", "TextEdit", "/System/Applications/TextEdit.app", ["textedit", "notepad"]),
                ("terminal", "Terminal", "/System/Applications/Utilities/Terminal.app", ["terminal"]),
                ("cmd", "Terminal", "/System/Applications/Utilities/Terminal.app", ["terminal", "cmd"]),
                ("safari", "Safari", "/Applications/Safari.app", ["safari"]),
                ("chrome", "Google Chrome", "/Applications/Google Chrome.app", ["chrome", "google chrome"]),
                ("code", "Visual Studio Code", "/Applications/Visual Studio Code.app", ["code", "visual studio code"]),
                ("vscode", "Visual Studio Code", "/Applications/Visual Studio Code.app", ["code", "visual studio code"]),
                ("system settings", "System Settings", "/System/Applications/System Settings.app", ["system settings", "system preferences"]),
                ("finder", "Finder", "/System/Library/CoreServices/Finder.app", ["finder"]),
            ]
            for norm, disp, target, procs in macos_builtins:
                if Path(target).exists():
                    rec = ApplicationRecord(
                        display_name=disp,
                        normalized_name=norm,
                        aliases=self._generate_aliases(disp) + [norm],
                        target_type="macos_app",
                        target=target,
                        source="macos_builtin",
                        proc_keywords=procs
                    )
                    self._add_record(rec)

            # 2. Discover .app Bundles across Standard macOS Application Locations
            search_dirs = [
                Path("/Applications"),
                Path("/System/Applications"),
                Path("/System/Applications/Utilities"),
                Path.home() / "Applications",
            ]
            for s_dir in search_dirs:
                if s_dir.exists() and s_dir.is_dir():
                    try:
                        for app_path in s_dir.glob("*.app"):
                            display_name = app_path.stem.strip()
                            norm = display_name.lower()
                            if any(bad in norm for bad in ["uninstall", "remove", "help", "readme"]):
                                continue
                            rec = ApplicationRecord(
                                display_name=display_name,
                                normalized_name=norm,
                                aliases=self._generate_aliases(display_name),
                                target_type="macos_app",
                                target=str(app_path.resolve()),
                                source="macos_applications",
                                proc_keywords=self._generate_proc_keywords(display_name)
                            )
                            self._add_record(rec)
                    except Exception as e:
                        logger.debug(f"Error scanning {s_dir}: {e}")

        elif IS_WINDOWS and winreg is not None:
            # 1. Registered Protocol Handlers (Highest confidence for modern apps)
            protocol_apps = [
                ("whatsapp", "WhatsApp", "whatsapp:", ["whatsapp", "whatsapp.root"]),
                ("spotify", "Spotify", "spotify:", ["spotify"]),
                ("discord", "Discord", "discord:", ["discord"]),
                ("steam", "Steam", "steam:", ["steam", "steamwebhelper"]),
            ]
            for norm, disp, uri, procs in protocol_apps:
                try:
                    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, norm) as key:
                        rec = ApplicationRecord(
                            display_name=disp,
                            normalized_name=norm,
                            aliases=self._generate_aliases(disp) + [norm],
                            target_type="protocol_uri",
                            target=uri,
                            source="protocol",
                            proc_keywords=procs
                        )
                        self._add_record(rec)
                except Exception:
                    pass

            # 2. Standard Built-in Windows Applications
            builtins = [
                ("chrome", "Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe" if Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe").exists() else "chrome.exe", ["chrome", "google chrome"]),
                ("google chrome", "Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe" if Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe").exists() else "chrome.exe", ["chrome", "google chrome"]),
                ("edge", "Microsoft Edge", "msedge.exe", ["msedge", "edge", "microsoft edge"]),
                ("msedge", "Microsoft Edge", "msedge.exe", ["msedge", "edge", "microsoft edge"]),
                ("microsoft edge", "Microsoft Edge", "msedge.exe", ["msedge", "edge", "microsoft edge"]),
                ("notepad", "Notepad", "notepad.exe", ["notepad"]),
                ("calculator", "Calculator", "calc.exe", ["calc", "calculator", "calculatorapp"]),
                ("calc", "Calculator", "calc.exe", ["calc", "calculator", "calculatorapp"]),
                ("mspaint", "Paint", "mspaint.exe", ["mspaint", "paint"]),
                ("paint", "Paint", "mspaint.exe", ["mspaint", "paint"]),
                ("explorer", "File Explorer", "explorer.exe", ["explorer"]),
                ("cmd", "Command Prompt", "cmd.exe", ["cmd"]),
                ("powershell", "PowerShell", "powershell.exe", ["powershell"]),
                ("taskmgr", "Task Manager", "taskmgr.exe", ["taskmgr"]),
            ]
            for norm, disp, target, procs in builtins:
                rec = ApplicationRecord(
                    display_name=disp,
                    normalized_name=norm,
                    aliases=self._generate_aliases(disp) + [norm],
                    target_type="system_binary",
                    target=target,
                    source="builtin",
                    proc_keywords=procs
                )
                self._add_record(rec)

            # 3. Start Menu Shortcuts (User & All Users) and Desktop Shortcuts
            search_dirs = [
                (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs", "start_menu_user"),
                (Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs", "start_menu_common"),
                (Path.home() / "Desktop", "desktop_user"),
                (Path.home() / "OneDrive" / "Desktop", "desktop_onedrive"),
                (Path(os.environ.get("PUBLIC", "")) / "Desktop", "desktop_public"),
            ]

            for s_dir, source in search_dirs:
                if s_dir.exists() and s_dir.is_dir():
                    for lnk in s_dir.rglob("*.lnk"):
                        display_name = lnk.stem.strip()
                        norm = display_name.lower()

                        # Filter out uninstaller/help/readme shortcuts
                        if any(bad in norm for bad in ["uninstall", "remove", "help", "documentation", "readme", "website", "manual"]):
                            continue

                        rec = ApplicationRecord(
                            display_name=display_name,
                            normalized_name=norm,
                            aliases=self._generate_aliases(display_name),
                            target_type="shortcut",
                            target=str(lnk.resolve()),
                            source=source,
                            proc_keywords=self._generate_proc_keywords(display_name)
                        )
                        self._add_record(rec)

            # 4. Registry App Paths
            for root_key in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    with winreg.OpenKey(root_key, r"Software\Microsoft\Windows\CurrentVersion\App Paths") as base_key:
                        num_subkeys = winreg.QueryInfoKey(base_key)[0]
                        for i in range(num_subkeys):
                            try:
                                subkey_name = winreg.EnumKey(base_key, i)
                                with winreg.OpenKey(base_key, subkey_name) as app_key:
                                    val, _ = winreg.QueryValueEx(app_key, "")
                                    if val and Path(val).exists():
                                        dname = subkey_name.replace(".exe", "").strip()
                                        norm = dname.lower()
                                        if norm in ["spotify_cli"]:
                                            continue  # skip internal cli helper in favor of main app
                                        rec = ApplicationRecord(
                                            display_name=dname.capitalize(),
                                            normalized_name=norm,
                                            aliases=self._generate_aliases(dname),
                                            target_type="executable",
                                            target=str(Path(val).resolve()),
                                            source="registry_app_paths",
                                            proc_keywords=[norm]
                                        )
                                        self._add_record(rec)
                            except Exception:
                                pass
                except Exception:
                    pass

            # 5. WindowsApps Execution Aliases
            win_apps_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
            if win_apps_dir.exists():
                for exe in win_apps_dir.glob("*.exe"):
                    dname = exe.stem.strip()
                    norm = dname.lower()
                    rec = ApplicationRecord(
                        display_name=dname.capitalize(),
                        normalized_name=norm,
                        aliases=self._generate_aliases(dname),
                        target_type="executable",
                        target=str(exe.resolve()),
                        source="windows_apps",
                        proc_keywords=[norm]
                    )
                    self._add_record(rec)

        self._last_index_time = now
        logger.info(f"[ByteX UniversalAppResolver] Indexed {len(self._records)} application records successfully.")

    def _add_record(self, record: ApplicationRecord):
        # Prevent lower priority duplicates from overwriting higher priority ones
        if record.normalized_name not in self._catalog:
            self._catalog[record.normalized_name] = record
            self._records.append(record)
        for alias in record.aliases:
            if alias not in self._alias_map:
                self._alias_map[alias] = record

    def _generate_aliases(self, name: str) -> List[str]:
        n = name.lower().strip()
        aliases = {n, n.replace(" ", ""), n.replace("-", " "), n.replace("_", " ")}

        if "visual studio code" in n or n == "code":
            aliases.update(["vs code", "vscode", "code", "visual studio code", "vsc"])
        if "google chrome" in n or n == "chrome":
            aliases.update(["chrome", "google chrome"])
        if "calculator" in n or n == "calc":
            aliases.update(["calc", "calculator", "calculator app"])
        if "paint" in n or "mspaint" in n:
            aliases.update(["paint", "mspaint", "ms paint"])
        if "file explorer" in n or n == "explorer":
            aliases.update(["explorer", "file explorer", "windows explorer"])
        if "microsoft edge" in n or n == "edge":
            aliases.update(["edge", "ms edge", "msedge", "microsoft edge"])
        if "whatsapp" in n:
            aliases.update(["whatsapp", "whatsapp desktop", "whats app"])
        if "spotify" in n:
            aliases.update(["spotify", "spotify music"])
        if "discord" in n:
            aliases.update(["discord"])
        if "steam" in n:
            aliases.update(["steam"])
        if "capcut" in n:
            aliases.update(["capcut", "cap cut"])
        if "brave" in n:
            aliases.update(["brave", "brave browser"])
        if "notepad" in n:
            aliases.update(["notepad", "notepad.exe"])

        return list(aliases)

    def _generate_proc_keywords(self, name: str) -> List[str]:
        n = name.lower().strip()
        kw = [n, n.replace(" ", ""), n.split()[0]]
        if "visual studio code" in n or n == "code":
            kw.extend(["code"])
        if "edge" in n or "msedge" in n or "microsoft edge" in n:
            kw.extend(["msedge", "edge", "microsoft edge"])
        if "chrome" in n:
            kw.extend(["chrome"])
        if "calculator" in n or "calc" in n:
            kw.extend(["calculator", "calc", "calculatorapp"])
        if "notepad" in n:
            kw.extend(["notepad"])
        if "whatsapp" in n:
            kw.extend(["whatsapp", "whatsapp.root"])
        if "spotify" in n:
            kw.extend(["spotify"])
        if "discord" in n:
            kw.extend(["discord"])
        if "steam" in n:
            kw.extend(["steam", "steamwebhelper"])
        if "capcut" in n:
            kw.extend(["capcut"])
        if "brave" in n:
            kw.extend(["brave"])
        return list(set(kw))

    def resolve(self, query: str) -> Tuple[ResolutionStatus, Optional[ApplicationRecord], List[ApplicationRecord]]:
        """
        Resolves a user-supplied application name to a validated ApplicationRecord.
        Returns: (ResolutionStatus, Optional[ApplicationRecord], List[CandidateRecords])
        """
        self.build_catalog()  # Ensure index is warm and valid
        q = query.strip().lower()
        if not q:
            return ResolutionStatus.NOT_FOUND, None, []

        # 1. Exact match in alias map (highest confidence)
        if q in self._alias_map:
            return ResolutionStatus.FOUND, self._alias_map[q], []

        # 2. Exact match in catalog
        if q in self._catalog:
            return ResolutionStatus.FOUND, self._catalog[q], []

        # 3. Substring / Token matching
        exact_matches = []
        partial_matches = []
        for rec in self._records:
            if q == rec.normalized_name or any(q == a for a in rec.aliases):
                exact_matches.append(rec)
            elif q in rec.normalized_name or any(q in a for a in rec.aliases):
                partial_matches.append(rec)

        if exact_matches:
            return ResolutionStatus.FOUND, exact_matches[0], []

        if len(partial_matches) == 1:
            return ResolutionStatus.FOUND, partial_matches[0], []

        if len(partial_matches) > 1:
            distinct_names = {p.display_name: p for p in partial_matches}
            if len(distinct_names) == 1:
                return ResolutionStatus.FOUND, list(distinct_names.values())[0], []
            else:
                # Genuine ambiguity: multiple distinct applications match
                return ResolutionStatus.AMBIGUOUS, None, list(distinct_names.values())[:3]

        return ResolutionStatus.NOT_FOUND, None, []

universal_app_resolver = UniversalApplicationResolver()

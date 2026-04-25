; Screenshot Sorter -- NSIS Installer Script
; Build: python installer/build_installer.py

Unicode True

!define APP_NAME      "Screenshot Sorter"
!define APP_VERSION   "1.0.0"
!define INSTALL_DIR   "$LOCALAPPDATA\ScreenshotSorter"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScreenshotSorter"
!define STARTUP_KEY   "Software\Microsoft\Windows\CurrentVersion\Run"

!include "MUI2.nsh"
!include "LogicLib.nsh"

SetCompressor /SOLID lzma
OutFile "Output\Install_ScreenshotSorter.exe"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel user

; --- MUI settings ---
!define MUI_ABORTWARNING
!define MUI_ICON   "assets\icon.ico"
!define MUI_UNICON "assets\icon.ico"

!define MUI_WELCOMEPAGE_TITLE "Screenshot Sorter Setup"
!define MUI_WELCOMEPAGE_TEXT  "This app automatically sorts your screenshots into folders using AI.$\r$\n$\r$\nOn first launch it will download AI models (~600 MB).$\r$\n$\r$\nClick Next to continue."

!define MUI_FINISHPAGE_RUN         "$INSTDIR\runtime\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-m screenshot_sorter.first_run"
!define MUI_FINISHPAGE_RUN_TEXT    "Launch Screenshot Sorter"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Russian"
!insertmacro MUI_LANGUAGE "English"

; ================================================================
Section "Install"

    SetOutPath "$INSTDIR"

    ; Python embeddable runtime
    SetOutPath "$INSTDIR\runtime"
    File /r "bootstrap\python\*.*"

    ; get-pip bootstrap
    SetOutPath "$INSTDIR\bootstrap"
    File "bootstrap\get-pip.py"

    ; Application source
    SetOutPath "$INSTDIR"
    File /r /x "__pycache__" /x "*.pyc" /x "installer" /x ".git" /x "*.egg-info" \
         "..\screenshot_sorter"
    File "..\config.yaml"
    File "..\pyproject.toml"

    ; .pth so embedded python finds our package
    FileOpen $0 "$INSTDIR\runtime\screenshot_sorter_app.pth" w
    FileWrite $0 "$INSTDIR$\r$\n"
    FileClose $0

    ; Icon
    SetOutPath "$INSTDIR\assets"
    File "assets\icon.ico"

    ; Install pip silently
    DetailPrint "Installing pip..."
    nsExec::ExecToLog '"$INSTDIR\runtime\python.exe" "$INSTDIR\bootstrap\get-pip.py" --quiet --no-warn-script-location'

    ; Install lightweight deps now (heavy ML libs install on first run)
    DetailPrint "Installing base dependencies..."
    nsExec::ExecToLog '"$INSTDIR\runtime\python.exe" -m pip install --quiet --no-warn-script-location watchdog>=4.0.0 Pillow>=10.0.0 imagehash>=4.3.1 click>=8.1.0 PyYAML>=6.0 pystray>=0.19.0'

    ; Uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Write a PowerShell script to create shortcuts, then run it
    FileOpen $0 "$INSTDIR\make_shortcuts.ps1" w
    FileWrite $0 "$$desktop = [Environment]::GetFolderPath('Desktop')$\r$\n"
    FileWrite $0 "$$startmenu = [Environment]::GetFolderPath('Programs')$\r$\n"
    FileWrite $0 "$$pythonw = '$INSTDIR\runtime\pythonw.exe'$\r$\n"
    FileWrite $0 "$$args = '-m screenshot_sorter.first_run'$\r$\n"
    FileWrite $0 "$$icon = '$INSTDIR\assets\icon.ico'$\r$\n"
    FileWrite $0 "$$ws = New-Object -COM WScript.Shell$\r$\n"
    FileWrite $0 "$$s = $$ws.CreateShortcut($$desktop + '\Screenshot Sorter.lnk')$\r$\n"
    FileWrite $0 "$$s.TargetPath = $$pythonw$\r$\n"
    FileWrite $0 "$$s.Arguments = $$args$\r$\n"
    FileWrite $0 "$$s.IconLocation = $$icon$\r$\n"
    FileWrite $0 "$$s.Save()$\r$\n"
    FileWrite $0 "New-Item -ItemType Directory -Force -Path ($$startmenu + '\Screenshot Sorter') | Out-Null$\r$\n"
    FileWrite $0 "$$s2 = $$ws.CreateShortcut($$startmenu + '\Screenshot Sorter\Screenshot Sorter.lnk')$\r$\n"
    FileWrite $0 "$$s2.TargetPath = $$pythonw$\r$\n"
    FileWrite $0 "$$s2.Arguments = $$args$\r$\n"
    FileWrite $0 "$$s2.IconLocation = $$icon$\r$\n"
    FileWrite $0 "$$s2.Save()$\r$\n"
    FileClose $0

    nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\make_shortcuts.ps1"'
    Delete "$INSTDIR\make_shortcuts.ps1"

    ; Autostart on Windows login
    WriteRegStr HKCU "${STARTUP_KEY}" "${APP_NAME}" \
        '"$INSTDIR\runtime\pythonw.exe" -m screenshot_sorter.first_run --silent'

    ; Add/Remove Programs
    WriteRegStr   HKCU "${UNINSTALL_KEY}" "DisplayName"     "${APP_NAME} ${APP_VERSION}"
    WriteRegStr   HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr   HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr   HKCU "${UNINSTALL_KEY}" "DisplayVersion"  "${APP_VERSION}"
    WriteRegStr   HKCU "${UNINSTALL_KEY}" "DisplayIcon"     "$INSTDIR\assets\icon.ico"
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify"        1
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair"        1

SectionEnd

; ================================================================
Section "Uninstall"

    nsExec::Exec 'taskkill /F /IM pythonw.exe'

    DeleteRegValue HKCU "${STARTUP_KEY}" "${APP_NAME}"
    DeleteRegKey   HKCU "${UNINSTALL_KEY}"

    RMDir /r "$INSTDIR\runtime"
    RMDir /r "$INSTDIR\bootstrap"
    RMDir /r "$INSTDIR\screenshot_sorter"
    RMDir /r "$INSTDIR\assets"
    Delete "$INSTDIR\config.yaml"
    Delete "$INSTDIR\pyproject.yaml"
    Delete "$INSTDIR\uninstall.exe"
    RMDir  "$INSTDIR"

    Delete "$DESKTOP\Screenshot Sorter.lnk"
    RMDir /r "$SMPROGRAMS\Screenshot Sorter"

    MessageBox MB_YESNO "Delete user settings and database?" IDNO +2
        Delete "$PROFILE\.screenshot_sorter_config.json"

SectionEnd

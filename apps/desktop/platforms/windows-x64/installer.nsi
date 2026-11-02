; Open DeepTutor for Windows installer. Built by package.mjs, which defines
; SOURCE (packaged app folder), OUTFILE, ICON, VERSION and FILEVERSION.
; Installs for the current user only, so no administrator prompt.

Unicode true
!include "MUI2.nsh"

!define APP "Open DeepTutor"
!define EXE "Open DeepTutor.exe"
!define REG "Software\Open DeepTutor"
!define UNINSTALL "Software\Microsoft\Windows\CurrentVersion\Uninstall\Open DeepTutor"

Name "${APP}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${REG}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Open DeepTutor for Windows v${VERSION}"

VIProductVersion "${FILEVERSION}"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "FileDescription" "Open DeepTutor for Windows v${VERSION} Setup"
VIAddVersionKey "CompanyName" "HKUDS"
VIAddVersionKey "LegalCopyright" "Copyright HKUDS. Licensed under Apache-2.0."
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${FILEVERSION}"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"

; The app's own files, never the whole folder: the user may have chosen a
; folder that holds other things. Learning data lives in
; %LOCALAPPDATA%\Open DeepTutor and survives upgrades and uninstalls.
!macro RemoveAppFiles
  RMDir /r "$INSTDIR\resources"
  RMDir /r "$INSTDIR\locales"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\d3dcompiler_47.dll"
  Delete "$INSTDIR\dxcompiler.dll"
  Delete "$INSTDIR\electron_wer.dll"
  Delete "$INSTDIR\ffmpeg.dll"
  Delete "$INSTDIR\vk_swiftshader.dll"
  Delete "$INSTDIR\vulkan-1.dll"
  Delete "$INSTDIR\chrome_100_percent.pak"
  Delete "$INSTDIR\chrome_200_percent.pak"
  Delete "$INSTDIR\resources.pak"
  Delete "$INSTDIR\snapshot_blob.bin"
  Delete "$INSTDIR\v8_context_snapshot.bin"
  Delete "$INSTDIR\icudtl.dat"
  Delete "$INSTDIR\vk_swiftshader_icd.json"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\LICENSES.chromium.html"
  Delete "$INSTDIR\version"
!macroend

Section
  SetOutPath "$INSTDIR"
  ; Replaces the previous version, including its bundled core.
  !insertmacro RemoveAppFiles
  File /r "${SOURCE}\*"
  WriteUninstaller "$INSTDIR\Uninstall ${APP}.exe"
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${EXE}"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${REG}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayName" "Open DeepTutor for Windows"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL}" "Publisher" "HKUDS"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${UNINSTALL}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL}" "UninstallString" '"$INSTDIR\Uninstall ${APP}.exe"'
  WriteRegDWORD HKCU "${UNINSTALL}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  !insertmacro RemoveAppFiles
  Delete "$INSTDIR\Uninstall ${APP}.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKCU "${UNINSTALL}"
  DeleteRegKey HKCU "${REG}"
SectionEnd

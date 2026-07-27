#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\DailyRecordOCR"
#endif
#ifndef OutputName
  #define OutputName "daily-record-ocr-lite-windows-x64-setup-UNSIGNED"
#endif

[Setup]
AppId={{D319B5C9-C3FB-49FD-B6D9-F4159758749F}
AppName=Daily Record OCR Lite
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\DailyRecordOCR
DefaultGroupName=Daily Record OCR Lite
OutputDir=..\..\artifacts
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName=Daily Record OCR Lite

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\手写配方识别"; Filename: "{app}\DailyRecordOCR.exe"
Name: "{autodesktop}\手写配方识别"; Filename: "{app}\DailyRecordOCR.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Run]
Filename: "{app}\DailyRecordOCR.exe"; Description: "启动手写配方识别"; Flags: nowait postinstall skipifsilent

; User jobs, knowledge, model caches, settings and secrets live under
; %LOCALAPPDATA%\DailyRecordOCR and are intentionally untouched by uninstall.

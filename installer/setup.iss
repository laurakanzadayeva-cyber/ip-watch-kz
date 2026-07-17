#define MyAppName "IP Watch KZ"
#define MyAppVersion "1.0"
#define MyAppPublisher "Serge Group KZ"
#define MyAppURL "http://localhost:8501"
#define MyAppExeName "IPWatchKZ.exe"
#define SourceDir "C:\Users\l.kanzadayeva\Desktop\Вайб_кодинг\IP Watch KZ"

[Setup]
AppId={{B4A2F3C1-7E8D-4F5A-9B1C-2D6E8F0A3C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir={#SourceDir}\installer\output
OutputBaseFilename=IPWatchKZ_Setup_v1.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SourceDir}\installer\icon.ico
UninstallDisplayIcon={app}\icon.ico
PrivilegesRequired=admin
DisableProgramGroupPage=yes
LicenseFile=
InfoAfterFile=

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительные задачи:"

[Files]
; Приложение
Source: "{#SourceDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "screenshots\*"
Source: "{#SourceDir}\laws\*"; DestDir: "{app}\laws"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.tmp"
Source: "{#SourceDir}\launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\installer\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
; Лаунчер .exe (без консоли)
Source: "{#SourceDir}\installer\IPWatchKZ.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить IP Watch KZ"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]

// Ищет python.exe на машине пользователя: реестр → PATH → стандартные папки
function FindPython(): String;
var
  PyExe: String;
  Versions: TArrayOfString;
  i: Integer;
  RegKey: String;
  LocalAppData: String;
begin
  Result := '';

  // 1. Реестр: HKCU и HKLM (стандартная установка с python.org)
  SetArrayLength(Versions, 8);
  Versions[0] := '3.14'; Versions[1] := '3.13'; Versions[2] := '3.12';
  Versions[3] := '3.11'; Versions[4] := '3.10'; Versions[5] := '3.9';
  Versions[6] := '3.8';  Versions[7] := '3.7';

  for i := 0 to GetArrayLength(Versions) - 1 do begin
    RegKey := 'SOFTWARE\Python\PythonCore\' + Versions[i] + '\InstallPath';
    if RegQueryStringValue(HKCU, RegKey, 'ExecutablePath', PyExe) then
      if FileExists(PyExe) then begin Result := PyExe; Exit; end;
    if RegQueryStringValue(HKLM, RegKey, 'ExecutablePath', PyExe) then
      if FileExists(PyExe) then begin Result := PyExe; Exit; end;
    // WOW6432Node (32-bit Python на 64-bit Windows)
    RegKey := 'SOFTWARE\WOW6432Node\Python\PythonCore\' + Versions[i] + '\InstallPath';
    if RegQueryStringValue(HKLM, RegKey, 'ExecutablePath', PyExe) then
      if FileExists(PyExe) then begin Result := PyExe; Exit; end;
  end;

  // 2. Стандартные папки LOCALAPPDATA и C:\
  LocalAppData := GetEnv('LOCALAPPDATA');
  for i := 0 to GetArrayLength(Versions) - 1 do begin
    // Programs\Python\Python3XX
    PyExe := LocalAppData + '\Programs\Python\Python' +
             StringReplace(Versions[i], '.', '', [rfReplaceAll]) + '\python.exe';
    if FileExists(PyExe) then begin Result := PyExe; Exit; end;
    // pythoncore-X.X-64 (Windows Store / специальные сборки)
    PyExe := LocalAppData + '\Python\pythoncore-' + Versions[i] + '-64\python.exe';
    if FileExists(PyExe) then begin Result := PyExe; Exit; end;
    PyExe := LocalAppData + '\Python\pythoncore-' + Versions[i] + '-32\python.exe';
    if FileExists(PyExe) then begin Result := PyExe; Exit; end;
    // C:\PythonXX
    PyExe := 'C:\Python' + StringReplace(Versions[i], '.', '', [rfReplaceAll]) + '\python.exe';
    if FileExists(PyExe) then begin Result := PyExe; Exit; end;
  end;

  // 3. Anaconda / Miniconda
  PyExe := GetEnv('USERPROFILE') + '\anaconda3\python.exe';
  if FileExists(PyExe) then begin Result := PyExe; Exit; end;
  PyExe := GetEnv('USERPROFILE') + '\miniconda3\python.exe';
  if FileExists(PyExe) then begin Result := PyExe; Exit; end;
  PyExe := 'C:\ProgramData\Anaconda3\python.exe';
  if FileExists(PyExe) then begin Result := PyExe; Exit; end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PyExe: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    PyExe := FindPython();
    if PyExe = '' then begin
      MsgBox(
        'Python не найден на этом компьютере.' + #13#10 +
        'Установите Python 3.10+ с сайта https://www.python.org/downloads/' + #13#10 +
        'и запустите IP Watch KZ повторно — зависимости установятся автоматически.',
        mbInformation, MB_OK);
      Exit;
    end;
    // Устанавливаем зависимости
    Exec(PyExe,
         '-m pip install -r "' + ExpandConstant('{app}') + '\requirements.txt" --quiet',
         ExpandConstant('{app}'),
         SW_SHOW, ewWaitUntilTerminated, ResultCode);
    if ResultCode <> 0 then
      MsgBox(
        'Не удалось установить зависимости автоматически.' + #13#10 +
        'Выполните в командной строке:' + #13#10 +
        '"' + PyExe + '" -m pip install streamlit playwright python-docx' + #13#10 +
        'Затем запустите IP Watch KZ.',
        mbError, MB_OK);
  end;
end;

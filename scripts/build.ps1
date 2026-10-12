$ErrorActionPreference = 'Stop'
$replayRoot = Split-Path -Parent $PSScriptRoot
$replayPython = (Get-Command python).Source
$replayPreviousPath = $env:PATH
Push-Location -LiteralPath $replayRoot
try {
    $env:PATH = (Split-Path -Parent $replayPython) + ';' + $env:SystemRoot + '\System32;' + $env:SystemRoot
    & $replayPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $replayPython scripts/fetch_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Corresponding source download failed.' }
    & $replayPython scripts/make_icon.py
    & $replayPython -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $replayPython -m PyInstaller --noconfirm --distpath dist --workpath build scripts/GT6Replay.spec
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    & $replayPython scripts/audit_release.py --package dist/GT6Replay
    if ($LASTEXITCODE -ne 0) { throw 'Release audit failed.' }
} finally {
    $env:PATH = $replayPreviousPath
    Pop-Location
}

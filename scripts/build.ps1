param(
    [string]$DistributionPath = 'dist',
    [string]$WorkPath = 'build/viewer',
    [switch]$SkipInstall
)
$ErrorActionPreference = 'Stop'
$replayRoot = Split-Path -Parent $PSScriptRoot
$replayPython = (Get-Command python).Source
$replayPreviousPath = $env:PATH
$replayDist = [System.IO.Path]::GetFullPath((Join-Path $replayRoot $DistributionPath))
$replayWork = [System.IO.Path]::GetFullPath((Join-Path $replayRoot $WorkPath))
foreach ($replayTarget in @($replayDist, $replayWork)) {
    if (-not $replayTarget.StartsWith($replayRoot.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Build output directories must stay inside this project.'
    }
}
Push-Location -LiteralPath $replayRoot
try {
    $env:PATH = (Split-Path -Parent $replayPython) + ';' + $env:SystemRoot + '\System32;' + $env:SystemRoot
    if (-not $SkipInstall) {
        & $replayPython -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    }
    & $replayPython -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & "$PSScriptRoot/build_decoder.ps1" -DistributionPath $DistributionPath -WorkPath 'build/decoder' -SkipInstall -SkipTests
    & $replayPython -m PyInstaller --noconfirm --distpath $replayDist --workpath $replayWork scripts/GT6Replay.spec
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    & $replayPython scripts/install_decoder.py $replayDist
    if ($LASTEXITCODE -ne 0) { throw 'Decoder installation failed.' }
    & $replayPython scripts/audit_release.py --package (Join-Path $replayDist 'GT6Replay')
    if ($LASTEXITCODE -ne 0) { throw 'Release audit failed.' }
} finally {
    $env:PATH = $replayPreviousPath
    Pop-Location
}

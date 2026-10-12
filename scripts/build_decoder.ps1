param(
    [string]$DistributionPath = 'dist',
    [string]$WorkPath = 'build/decoder',
    [switch]$SkipInstall,
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$replayRoot = Split-Path -Parent $PSScriptRoot
$replayPython = (Get-Command python).Source
$replayPreviousPath = $env:PATH
$replayDist = [System.IO.Path]::GetFullPath((Join-Path $replayRoot $DistributionPath))
$replayWork = [System.IO.Path]::GetFullPath((Join-Path $replayRoot $WorkPath))
$replayPrefix = $replayRoot.TrimEnd('\') + '\'
foreach ($replayTarget in @($replayDist, $replayWork)) {
    if (-not $replayTarget.StartsWith($replayPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Build output directories must stay inside this project.'
    }
}
Push-Location -LiteralPath $replayRoot
try {
    $env:PATH = (Split-Path -Parent $replayPython) + ';' + $env:SystemRoot + '\System32;' + $env:SystemRoot
    if (-not $SkipInstall) {
        & $replayPython -m pip install -r requirements-decoder-build.txt
        if ($LASTEXITCODE -ne 0) { throw 'Decoder dependency installation failed.' }
    }
    & $replayPython scripts/fetch_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Corresponding source download failed.' }
    & $replayPython scripts/collect_decoder_notices.py
    if ($LASTEXITCODE -ne 0) { throw 'Decoder notice collection failed.' }
    & $replayPython scripts/make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    if (-not $SkipTests) {
        & $replayPython -m unittest discover -s tests -p 'test_decoder*.py' -q
        if ($LASTEXITCODE -ne 0) { throw 'Decoder tests failed.' }
    }
    & $replayPython -m PyInstaller --noconfirm --distpath $replayDist --workpath $replayWork scripts/GT6ReplayDecoder.spec
    if ($LASTEXITCODE -ne 0) { throw 'Decoder build failed.' }
    $replayProgram = Join-Path $replayDist 'GT6ReplayDecoder'
    Copy-Item -LiteralPath LICENSE, THIRD_PARTY.md -Destination $replayProgram -Force
    Copy-Item -LiteralPath docs/decoder.md -Destination (Join-Path $replayProgram 'README.md') -Force
    & $replayPython scripts/audit_release.py --package $replayProgram
    if ($LASTEXITCODE -ne 0) { throw 'Decoder package audit failed.' }
    & $replayPython scripts/smoke_decoder.py $replayProgram --report (Join-Path $replayWork 'smoke.json')
    if ($LASTEXITCODE -ne 0) { throw 'Decoder executable checks failed.' }
} finally {
    $env:PATH = $replayPreviousPath
    Pop-Location
}

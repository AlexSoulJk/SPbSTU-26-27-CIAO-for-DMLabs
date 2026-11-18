[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$guideRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildRoot = Join-Path $guideRoot "build"
$texCacheRoot = Join-Path ([IO.Path]::GetTempPath()) "ciao-user-guide-texmf-cache"

New-Item -ItemType Directory -Force -Path `
    $buildRoot, `
    $texCacheRoot, `
    (Join-Path $buildRoot "chapters"), `
    (Join-Path $buildRoot "appendices") | Out-Null

# Keep LuaLaTeX's writable font cache outside the path with Cyrillic characters.
$env:TEXMFCACHE = $texCacheRoot
$env:TEXMFVAR = $texCacheRoot

Push-Location $guideRoot
try {
    latexmk `
        -lualatex `
        -interaction=nonstopmode `
        -halt-on-error `
        -file-line-error `
        -outdir=build `
        -jobname=user-guide `
        main.tex

    if ($LASTEXITCODE -ne 0) {
        throw "User guide build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "Built: $buildRoot\user-guide.pdf"


# Builds the Windows release of Afterglow Studio: tests -> PyInstaller -> self-test -> own-UI installer (setup\)
# -> zip (installer + install notes) -> release check (no concert-derived files) -> SHA-256. Version comes from APP_VERSION in app.py.
# Usage (from this folder):  powershell -ExecutionPolicy Bypass -File build_release.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = '.venv/Scripts/python.exe'
$ver = (Select-String -Path app.py -Pattern "^APP_VERSION = '([\d.]+)'").Matches[0].Groups[1].Value
$name = "Afterglow-Studio-$ver"
New-Item -ItemType Directory -Force release | Out-Null
$rel = Join-Path (Resolve-Path release) $name
$zip = "$rel-Windows.zip"
Write-Host "== Afterglow Studio $ver"

& $py -m unittest discover -s tests -q
if ($LASTEXITCODE) { throw 'unit tests failed' }

& $py -m PyInstaller --noconfirm --distpath dist --workpath build AfterglowStudio.spec
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

$st = Join-Path $env:TEMP 'afterglow_selftest.txt'
Remove-Item $st -ErrorAction SilentlyContinue
Start-Process -FilePath (Resolve-Path dist/AfterglowStudio/AfterglowStudio.exe).Path -ArgumentList '--selftest', $st -Wait
$last = Get-Content $st -Tail 1
Write-Host "self-test: $last"
if ($last -notmatch 'RESULT: OK') { throw 'frozen self-test failed' }

# single-file installer with our own UI (setup\setup_app.py + setup\ui): payload = the program built above
& $py -I -c "import sys, zipfile, pathlib; st = pathlib.Path('build/setup'); st.mkdir(parents=True, exist_ok=True); (st / 'version.txt').write_text(sys.argv[1], encoding='utf-8'); src = pathlib.Path('dist/AfterglowStudio'); z = zipfile.ZipFile(st / 'payload.zip', 'w', zipfile.ZIP_LZMA); [z.write(f, f.relative_to(src).as_posix()) for f in src.rglob('*') if f.is_file()]; z.write('../THIRD_PARTY_NOTICES.txt', 'THIRD_PARTY_NOTICES.txt'); z.close()" $ver
if ($LASTEXITCODE) { throw 'payload failed' }
& $py -m PyInstaller --noconfirm --distpath dist-setup --workpath build\setup-work setup\AfterglowSetup.spec
if ($LASTEXITCODE) { throw 'installer build failed' }
$setup = Resolve-Path "dist-setup\Afterglow-Studio-Setup-$ver.exe"
# append the program to the installer exe (read with zipfile at install time; not unpacked at every start)
& $py -I -c "import shutil, sys; f = open(sys.argv[1], 'ab'); shutil.copyfileobj(open('build/setup/payload.zip', 'rb'), f); f.close()" $setup
if ($LASTEXITCODE) { throw 'appending the payload failed' }
$tmpi = Join-Path $env:TEMP "afterglow_setup_check"
if (Test-Path $tmpi) { Remove-Item -Recurse -Force $tmpi }
$pi = Start-Process $setup -ArgumentList '--silent', '--no-shortcuts', '--keep-registry', '--dir', "`"$tmpi`"" -Wait -PassThru
if ($pi.ExitCode -or -not (Test-Path (Join-Path $tmpi 'AfterglowStudio.exe'))) { throw 'installer self-check failed' }
$pu = Start-Process (Join-Path $tmpi 'uninstall.exe') -ArgumentList '--uninstall', '--silent', '--no-shortcuts', '--keep-registry', '--dir', "`"$tmpi`"" -Wait -PassThru
Write-Host "installer self-check: install ok, uninstall exit $($pu.ExitCode)"

# release folder = what the zip holds: the installer and the install notes, nothing else
if (Test-Path $rel) { Remove-Item -Recurse -Force $rel }
New-Item -ItemType Directory -Path $rel | Out-Null
Copy-Item $setup $rel
foreach ($t in Get-ChildItem installer\readme -Filter *.txt) {      # install notes, {VERSION} filled in
    (Get-Content $t.FullName -Raw -Encoding UTF8).Replace('{VERSION}', $ver) | Set-Content (Join-Path $rel $t.Name) -Encoding UTF8
}
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $rel '*') -DestinationPath $zip
& $py release_check.py dist\AfterglowStudio $rel ..\firmware\dist
if ($LASTEXITCODE) { throw 'release check failed' }
foreach ($f in $setup, $zip) {
    $hh = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
    "$hh  $(Split-Path $f -Leaf)" | Set-Content "$f.sha256" -Encoding ASCII
}
Write-Host "done: $setup"
Write-Host "done: $zip"

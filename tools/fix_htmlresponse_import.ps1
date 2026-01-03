param(
  [string]$MainPath = ".\app\main.py"
)

$ErrorActionPreference = "Stop"

function Backup-File([string]$path) {
  if (!(Test-Path $path)) { throw "File not found: $path" }
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $bak = "$path.bak_$ts"
  Copy-Item $path $bak -Force
  Write-Host "Backup: $bak"
  return $bak
}

$bak = Backup-File $MainPath
$src = Get-Content $MainPath -Raw -ErrorAction Stop

# (1) 잘못 끼어든 단독 라인: ", HTMLResponse" 제거
$src = $src -replace '(?m)^\s*,\s*HTMLResponse\s*$\r?\n?', ''

# (2) fastapi.responses import 라인에 HTMLResponse를 "같은 줄"로 붙이기
if ($src -match '(?m)^from fastapi\.responses import (.+)$') {
  $line = ($Matches[0])
  $items = ($Matches[1]).Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }

  if ($items -notcontains "HTMLResponse") {
    $items += "HTMLResponse"
  }

  # 중복 제거 + 보기 좋게
  $items = $items | Select-Object -Unique

  $newLine = "from fastapi.responses import " + ($items -join ", ")
  $src = $src -replace [regex]::Escape($line), $newLine
} else {
  # responses import가 아예 없으면 한 줄 추가
  if ($src -match '(?m)^from fastapi import .+$') {
    $src = [regex]::Replace($src, '(?m)^(from fastapi import .+)$', "`$1`r`nfrom fastapi.responses import HTMLResponse", 1)
  } else {
    # 정말 최후: 파일 맨 위에 추가
    $src = "from fastapi.responses import HTMLResponse`r`n" + $src
  }
}

# (3) 컴파일 체크. 실패하면 백업 복구
$src | Set-Content -Encoding UTF8 $MainPath

try {
  & .\.venv\Scripts\python.exe -m py_compile $MainPath | Out-Null
  Write-Host "OK: fixed HTMLResponse import + compile passed"
} catch {
  Write-Host "ABORT: compile failed. Restoring backup." -ForegroundColor Red
  Copy-Item $bak $MainPath -Force
  throw
}

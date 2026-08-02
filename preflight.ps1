# Power Academy - PREFLIGHT
# Lives in:  E:\PowerAcademy\scripts\
# Run before any session:  .\preflight.ps1   (from scripts\, or anywhere)
#
# Checks the whole chain in ~10 seconds. Every check here exists because the
# corresponding failure has actually cost a session, and each one presented as a
# DATA problem rather than an infrastructure one:
#   - Caddy service stopped        -> dead source deep-links, looked like bad JSON
#   - extract_all wired to the old ripper -> UNK_FY-2026.txt transcripts
#   - fragmented text\ dirs        -> newly ripped calls invisible to the health check
#   - _earnings_index.json stale   -> "ripped, not yet built" silently wrong or missing
#
# Read-only. Changes nothing. Prints a fix command for anything that fails.

$ErrorActionPreference = 'SilentlyContinue'

# Resolve the project root from THIS script's own location, so it works whether it
# sits in scripts\ or in the project root, and follows the folder if it moves.
$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
if ((Split-Path $here -Leaf) -eq 'scripts') { $ROOT = Split-Path $here -Parent }
else { $ROOT = $here }
# Sanity check: the root must contain data\. If not, fall back to the known path so a
# copy run from Downloads still reports on the real project rather than on nothing.
if (-not (Test-Path (Join-Path $ROOT 'data'))) { $ROOT = 'E:\PowerAcademy' }

$SCRIPTS     = Join-Path $ROOT 'scripts'
$DATA        = Join-Path $ROOT 'data'
$DOCS        = Join-Path $ROOT 'documents'
$REPO        = Join-Path $ROOT 'app\poweracademy'
$TRANSCRIPTS = Join-Path $ROOT 'Documents\transcripts'
$TEXTDIR     = Join-Path $TRANSCRIPTS 'text'
$CAPIQ_XLSX  = Join-Path $DATA 'reports'

$script:pass = 0; $script:warn = 0; $script:fail = 0

function Say($status, $label, $detail, $fix) {
    switch ($status) {
        'PASS' { $c = 'Green';  $script:pass++ }
        'WARN' { $c = 'Yellow'; $script:warn++ }
        'FAIL' { $c = 'Red';    $script:fail++ }
        default { $c = 'DarkGray' }
    }
    Write-Host ("  {0,-4} " -f $status) -ForegroundColor $c -NoNewline
    Write-Host ("{0,-34} " -f $label) -NoNewline
    Write-Host $detail -ForegroundColor DarkGray
    if ($fix) { Write-Host ("       -> " + $fix) -ForegroundColor $c }
}
function Section($t) { Write-Host ''; Write-Host "  $t" -ForegroundColor Cyan; Write-Host ('  ' + ('-' * 68)) -ForegroundColor DarkGray }

Write-Host ''
Write-Host '  POWER ACADEMY - PREFLIGHT' -ForegroundColor White
Write-Host ("  " + (Get-Date -Format 'yyyy-MM-dd HH:mm') + "   root: " + $ROOT) -ForegroundColor DarkGray

# --------------------------------------------------------------- SERVICES ----
Section 'Services'

$caddy = Get-Service caddy -ErrorAction SilentlyContinue
if (-not $caddy) {
    Say 'FAIL' 'Caddy service' 'not installed' 'all /reports/, /credit/, /transcripts/ links will fail'
} elseif ($caddy.Status -ne 'Running') {
    Say 'FAIL' 'Caddy service' "status = $($caddy.Status)" 'Start-Service caddy   (admin)'
} else {
    Say 'PASS' 'Caddy service' 'running'
}

if ($caddy) {
    $mode = (Get-CimInstance Win32_Service -Filter "Name='caddy'").StartMode
    if ($mode -ne 'Auto') {
        Say 'WARN' 'Caddy start mode' "$mode - dies on reboot" 'Set-Service caddy -StartupType Automatic   (admin)'
    } else {
        Say 'PASS' 'Caddy start mode' 'Automatic'
    }
}

$p8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($p8080) { Say 'PASS' 'Port 8080 (documents)' 'listening' }
else        { Say 'FAIL' 'Port 8080 (documents)' 'nothing listening' 'deep-links -> ERR_CONNECTION_REFUSED' }

$p3001 = Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue
if ($p3001) {
    $h = $null
    try { $h = Invoke-RestMethod -Uri 'http://localhost:3001/api/health' -TimeoutSec 3 } catch { }
    if ($h) { Say 'PASS' 'Node API (3001)' 'healthy' }
    else    { Say 'WARN' 'Node API (3001)' 'listening but /api/health failed' }
} else {
    Say 'WARN' 'Node API (3001)' 'not running' '.\start.ps1'
}

$p3000 = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if ($p3000) { Say 'PASS' 'React dev (3000)' 'listening' }
else        { Say 'INFO' 'React dev (3000)' 'not running' }

# ------------------------------------------------------------ RIP WIRING ----
Section 'Extraction wiring'

$eaPath = Join-Path $SCRIPTS 'extract_all.py'
if (-not (Test-Path $eaPath)) {
    Say 'FAIL' 'extract_all.py' 'missing'
} else {
    $src = Get-Content $eaPath -Raw
    if ($src -match "RIP_SCRIPT\s*=\s*r'([^']+)'") {
        $target = Split-Path $Matches[1] -Leaf
        if ($target -eq 'rip.py') { Say 'PASS' 'extract_all -> ripper' $target }
        else { Say 'FAIL' 'extract_all -> ripper' "$target (RETIRED)" 'repoint RIP_SCRIPT to rip.py AND pass -r --out' }
    } else {
        Say 'WARN' 'extract_all -> ripper' 'RIP_SCRIPT not found in file'
    }

    if ($src -match "'-r'")     { Say 'PASS' 'extract_all passes -r'   'recursive' }
    else { Say 'FAIL' 'extract_all passes -r' 'MISSING' 'rip.py is not recursive by default -> rips ZERO files' }

    if ($src -match "'--out'")  { Say 'PASS' 'extract_all passes --out' 'single text dir' }
    else { Say 'WARN' 'extract_all passes --out' 'MISSING' 'output will fragment into per-quarter text\ dirs' }
}

foreach ($retired in @('rip_earnings.py','rip_text.py')) {
    $rp = Join-Path $SCRIPTS $retired
    if (Test-Path $rp) { Say 'WARN' "retired: $retired" 'still present' "Rename-Item '$rp' '$retired.retired'" }
    else               { Say 'PASS' "retired: $retired" 'gone' }
}

# ----------------------------------------------------------- TRANSCRIPTS ----
Section 'Transcripts'

if (-not (Test-Path $TEXTDIR)) {
    Say 'FAIL' 'transcripts\text' 'missing'
} else {
    $txt = @(Get-ChildItem $TEXTDIR -Filter '*.txt' -ErrorAction SilentlyContinue)
    Say 'PASS' 'ripped .txt files' "$($txt.Count) in one dir"

    # Fragmentation: any OTHER dir named text under transcripts
    $frag = @(Get-ChildItem $TRANSCRIPTS -Directory -Recurse -Filter 'text' -ErrorAction SilentlyContinue |
              Where-Object { $_.FullName -ne $TEXTDIR })
    if ($frag.Count -gt 0) {
        Say 'WARN' 'fragmented text\ dirs' "$($frag.Count) extra" 'rerun rip.py with --out to consolidate'
        foreach ($f in $frag) { Write-Host ("         " + $f.FullName) -ForegroundColor DarkGray }
    } else {
        Say 'PASS' 'fragmented text\ dirs' 'none'
    }

    $bad = @($txt | Where-Object { $_.Name -like 'UNK_*' -or $_.Name -like '*_FY-*' })
    if ($bad.Count -gt 0) {
        Say 'WARN' 'suspect names (UNK_ / _FY-)' "$($bad.Count)" 'old-ripper artifacts; verify then delete'
        foreach ($b in $bad) { Write-Host ("         " + $b.Name) -ForegroundColor DarkGray }
    } else {
        Say 'PASS' 'suspect names (UNK_ / _FY-)' 'none'
    }

    # Index vs earnings_calls.json
    $idxPath = Join-Path $TEXTDIR '_earnings_index.json'
    $ecPath  = Join-Path $DATA 'earnings_calls.json'
    if (-not (Test-Path $idxPath)) {
        Say 'FAIL' '_earnings_index.json' 'MISSING' 'python rip.py <transcripts> -r --out <text> --force'
    } else {
        $idx = $null
        try { $idx = Get-Content $idxPath -Raw | ConvertFrom-Json } catch { }
        $idxN = @($idx).Count
        if ($idxN -lt 1) {
            Say 'FAIL' '_earnings_index.json' 'empty/unreadable' 'rerun rip.py with --force (deleting it alone does NOT rebuild it)'
        } else {
            Say 'PASS' '_earnings_index.json' "$idxN rows"
        }

        if (Test-Path $ecPath) {
            $ec = $null
            try { $ec = Get-Content $ecPath -Raw | ConvertFrom-Json } catch { }
            if ($ec) {
                $n = 0
                foreach ($t in $ec.calls.PSObject.Properties) { $n += @($t.Value).Count }
                Say 'PASS' 'earnings_calls.json' "$n calls / $(@($ec.calls.PSObject.Properties).Count) tickers"
                if ($idxN -gt 0 -and $idxN -lt $n) {
                    Say 'WARN' 'index vs built calls' "index $idxN < built $n" 'index likely stale - rerun rip.py --force'
                }
            } else {
                Say 'FAIL' 'earnings_calls.json' 'unreadable JSON'
            }
        } else {
            Say 'FAIL' 'earnings_calls.json' 'missing'
        }
    }
}

# ------------------------------------------------------------ ORPHAN TXT ---
# A .txt on disk that appears in NEITHER index is left over from an older ripper
# or an older naming scheme. Harmless to read, but it inflates counts and hides
# what is actually current.
if (Test-Path $TEXTDIR) {
    $allTxt = @(Get-ChildItem $TEXTDIR -Filter '*.txt' -ErrorAction SilentlyContinue)
    $known = @()
    $ei = Join-Path $TEXTDIR '_earnings_index.json'
    if (Test-Path $ei) {
        try { $known += @((Get-Content $ei -Raw | ConvertFrom-Json) | ForEach-Object { $_.out_file }) } catch { }
    }
    $ri = Join-Path $TEXTDIR '_rip_index.json'
    if (Test-Path $ri) {
        try { $known += @((Get-Content $ri -Raw | ConvertFrom-Json).files | ForEach-Object { $_.out_txt }) } catch { }
    }
    $known = @($known | Where-Object { $_ })
    $orphans = @($allTxt | Where-Object { $known -notcontains $_.Name })
    if ($orphans.Count -gt 0) {
        Say 'WARN' 'orphan .txt (in no index)' "$($orphans.Count) of $($allTxt.Count)" 'older rip leftovers; verify then delete'
        foreach ($o in $orphans) { Write-Host ("         " + $o.Name) -ForegroundColor DarkGray }
    } else {
        Say 'PASS' 'orphan .txt (in no index)' "none of $($allTxt.Count)"
    }
}

# ------------------------------------------------------------ CAPIQ XLSX ----
Section 'CapIQ workbooks'

if (-not (Test-Path $CAPIQ_XLSX)) {
    Say 'FAIL' 'data\reports' 'missing'
} else {
    $wb = @(Get-ChildItem $CAPIQ_XLSX -Filter '*.xlsx' | Where-Object { $_.Name -notlike '~$*' })
    if ($wb.Count -eq 23) { Say 'PASS' 'workbook count' '23 (one per ticker)' }
    else { Say 'WARN' 'workbook count' "$($wb.Count) (expected 23)" 'duplicate vintages? each ticker should have exactly one' }

    # crude duplicate-ticker detection: same leading name, different date suffix
    $stems = $wb | ForEach-Object { ($_.BaseName -replace '_Report_\d{2}-\d{2}-\d{4}$','') }
    $dupes = @($stems | Group-Object | Where-Object Count -gt 1)
    if ($dupes.Count -gt 0) {
        Say 'WARN' 'duplicate workbooks' "$($dupes.Count) name(s) with >1 vintage" 'delete the older file - sort order decides which wins'
        foreach ($d in $dupes) { Write-Host ("         " + $d.Name) -ForegroundColor DarkGray }
    } else {
        Say 'PASS' 'duplicate workbooks' 'none'
    }
}

# -------------------------------------------------------------- DATA FILES --
Section 'Data files'

$expect = @('capiq_export.json','executives_export.json','earnings_calls.json','rra_states.json',
            'precedents.json','live_deals.json','broker_research.json','moodys_credit.json',
            'sp_credit.json','fitch_credit.json','ferc_opco.json','ferc_manual.json',
            'rate_base_ip.json','guidance_ip.json','bank_scorecard.json')
$missing = @()
foreach ($f in $expect) { if (-not (Test-Path (Join-Path $DATA $f))) { $missing += $f } }
if ($missing.Count -eq 0) { Say 'PASS' 'core data files' "$($expect.Count) present" }
else { Say 'WARN' 'core data files' "$($missing.Count) missing: $($missing -join ', ')" }

$bsplit = Join-Path $DATA 'broker_research'
if (Test-Path $bsplit) {
    $per = @(Get-ChildItem $bsplit -Filter '*.json')
    $mono = Get-Item (Join-Path $DATA 'broker_research.json') -ErrorAction SilentlyContinue
    if ($mono -and $per.Count -gt 0) {
        $stale = @($per | Where-Object { $_.LastWriteTime -lt $mono.LastWriteTime })
        if ($stale.Count -gt 0) { Say 'WARN' 'per-ticker broker split' "$($stale.Count) older than master" 'python scripts\split_broker_json.py' }
        else { Say 'PASS' 'per-ticker broker split' "$($per.Count) files, current" }
    }
} else {
    Say 'WARN' 'per-ticker broker split' 'folder missing' 'python scripts\split_broker_json.py'
}

# --------------------------------------------------------- BROKER ALIASES --
# The same house under two names ("Wolfe" vs "Wolfe Research") reads as two separate
# brokers, so a superseded note survives into consensus instead of being excluded.
# Latest-per-broker silently stops working.
$brPath = Join-Path $DATA 'broker_research.json'
if (Test-Path $brPath) {
    $names = @{}
    try {
        $br = Get-Content $brPath -Raw | ConvertFrom-Json
        foreach ($tk in $br.PSObject.Properties) {
            foreach ($rep in @($tk.Value.reports)) {
                if ($rep.broker) { $names[$rep.broker] = 1 }
            }
            $fe = $tk.Value.financial_estimates
            if ($fe -and $fe.metrics) {
                foreach ($m in $fe.metrics.PSObject.Properties) {
                    if ($m.Value.by_broker) {
                        foreach ($b in $m.Value.by_broker.PSObject.Properties) { $names[$b.Name] = 1 }
                    }
                }
            }
        }
    } catch { }
    $arr = @($names.Keys)
    $pairs = @()
    foreach ($a in $arr) {
        foreach ($b in $arr) {
            if ($a -ne $b -and $b.ToLower().StartsWith($a.ToLower() + ' ')) { $pairs += ($a + '  <->  ' + $b) }
        }
    }
    if ($pairs.Count -gt 0) {
        Say 'WARN' 'broker name variants' "$($pairs.Count) pair(s)" 'same house under 2 names breaks latest-per-broker'
        foreach ($p in ($pairs | Sort-Object -Unique)) { Write-Host ("         " + $p) -ForegroundColor DarkGray }
    } else {
        Say 'PASS' 'broker name variants' "none across $($arr.Count) houses"
    }
}

# ---------------------------------------------------------------- TOOLING --
Section 'Tooling'

$tess = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
if (Test-Path $tess) { Say 'PASS' 'Tesseract' 'present (rip.py adds to PATH)' }
else { Say 'WARN' 'Tesseract' 'not at default path' 'OCR fallback on scanned PDFs will fail' }

Push-Location $REPO
$branch = git rev-parse --abbrev-ref HEAD 2>$null
$dirty  = git status --porcelain 2>$null
Pop-Location
if ($branch) {
    if ($dirty) { Say 'WARN' 'git' "$branch - uncommitted changes" 'git add -A; git commit -m "..."' }
    else        { Say 'PASS' 'git' "$branch - clean" }
} else {
    Say 'INFO' 'git' 'not a repo / git unavailable'
}

# ---------------------------------------------------------------- SUMMARY --
Write-Host ''
Write-Host ('  ' + ('=' * 68)) -ForegroundColor DarkGray
Write-Host "  PASS $script:pass" -ForegroundColor Green -NoNewline
Write-Host "   WARN $script:warn" -ForegroundColor Yellow -NoNewline
Write-Host "   FAIL $script:fail" -ForegroundColor Red
if ($script:fail -gt 0) { Write-Host '  Fix the FAIL items before extracting - they cause silent bad data.' -ForegroundColor Red }
elseif ($script:warn -gt 0) { Write-Host '  Safe to work; warnings are drift worth clearing.' -ForegroundColor Yellow }
else { Write-Host '  All clear.' -ForegroundColor Green }
Write-Host ''
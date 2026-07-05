# download_gas_territories.ps1
# Downloads HIFLD Natural Gas Service Territories from NASA NCCS mirror
# Uses Windows native HTTP (Invoke-WebRequest) which handles IPv4/IPv6 correctly
# 
# Run: .\download_gas_territories.ps1 -OutDir E:\PowerAcademy\data
#
param(
    [string]$OutDir = "E:\PowerAcademy\data"
)

$BASE = "https://maps.nccs.nasa.gov/mapping/rest/services/hifld_open/energy/FeatureServer/29/query"
$STATES = @("FL","TX","NH","CT","MA","RI","NY","NJ","PA","MD","VA","NC","SC",
            "GA","AL","MS","LA","AR","OK","MO","IL","MI","WI","MN","IA","KS",
            "OH","KY","IN","WV","TN","CA","OR","HI","AZ","CO","UT","NM")

$whereClause = ($STATES | ForEach-Object { "STATE='$_'" }) -join " OR "
$encoded = [uri]::EscapeDataString($whereClause)

$allFeatures = @()
$offset = 0
$pageSize = 1000
$page = 1

Write-Host "Downloading Natural Gas Service Territories from NASA NCCS..."

do {
    $url = "$BASE`?where=$encoded&outFields=NAME,HIFLDID,STATE,SUPPLIER,TYPE,CUSTOMERS&outSR=4326&f=geojson&resultOffset=$offset&resultRecordCount=$pageSize"
    Write-Host "  Page $page (offset=$offset)..." -NoNewline
    
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 60
        $data = $response.Content | ConvertFrom-Json
        $features = $data.features
        Write-Host " $($features.Count) features"
        $allFeatures += $features
        $offset += $pageSize
        $page++
        if ($features.Count -lt $pageSize) { break }
        Start-Sleep -Milliseconds 300
    } catch {
        Write-Host " ERROR: $_"
        break
    }
} while ($true)

Write-Host "Total features: $($allFeatures.Count)"

# Build GeoJSON
$geojson = @{
    type = "FeatureCollection"
    features = $allFeatures
    _source = "HIFLD Natural Gas Service Territories via NASA NCCS mirror"
    _downloaded = (Get-Date -Format "yyyy-MM-dd")
    _states = $STATES
}

$outPath = Join-Path $OutDir "gas_territories_raw.geojson"
$geojson | ConvertTo-Json -Depth 20 -Compress | Out-File -FilePath $outPath -Encoding utf8

$sizeMB = [math]::Round((Get-Item $outPath).Length / 1MB, 1)
Write-Host "Saved: $outPath ($sizeMB MB)"
Write-Host ""
Write-Host "Now run:"
Write-Host "  python download_gis_layers_v2.py --out $OutDir --only gas_territories"
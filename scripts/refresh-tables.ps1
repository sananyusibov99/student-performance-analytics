# Refresh the open model one table at a time (data only), then recalculate.
# Prints progress per table so a slow or failing table is visible; already loaded tables are kept.
param([string[]]$Only)
$ErrorActionPreference = "Stop"
$base = "$env:TEMP\tom_nuget\microsoft.analysisservices.retail.amd64\lib\net45"
Add-Type -Path "$base\Microsoft.AnalysisServices.Core.dll"
Add-Type -Path "$base\Microsoft.AnalysisServices.Tabular.dll"
$pf = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$port = ([IO.File]::ReadAllText($pf.FullName, [Text.Encoding]::Unicode)).Trim()
$server = New-Object Microsoft.AnalysisServices.Tabular.Server
$server.Connect("Data Source=localhost:$port;Timeout=7200")
$model = $server.Databases[0].Model
$RT = [Microsoft.AnalysisServices.Tabular.RefreshType]
try {
    # small tables first, so the biggest load comes last
    $tables = $model.Tables | Where-Object { $_.Partitions[0].SourceType -eq "M" -and (-not $Only -or $Only -contains $_.Name) } |
        Sort-Object { (Get-Item -LiteralPath (Join-Path (Resolve-Path "$PSScriptRoot\..\data\model") ($_.Description -replace '^Source: data\\model\\', ''))).Length }
    foreach ($t in $tables) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $t.RequestRefresh($RT::DataOnly)
        $model.SaveChanges() | Out-Null
        "{0,-18} {1,5} s" -f $t.Name, [int]$sw.Elapsed.TotalSeconds
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $model.RequestRefresh($RT::Calculate)
    $model.SaveChanges() | Out-Null
    "recalculate        {0,5} s" -f [int]$sw.Elapsed.TotalSeconds
    "DONE"
}
catch { "FAILED: $($_.Exception.Message)"; exit 1 }
finally { $server.Disconnect() }

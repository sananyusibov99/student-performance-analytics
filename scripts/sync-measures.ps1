# Sync the Metrics measures in the open Power BI model with model_logic.json without rebuilding tables.
$ErrorActionPreference = "Stop"
$base = "$env:TEMP\tom_nuget\microsoft.analysisservices.retail.amd64\lib\net45"
Add-Type -Path "$base\Microsoft.AnalysisServices.Core.dll"
Add-Type -Path "$base\Microsoft.AnalysisServices.Tabular.dll"
$NS = "Microsoft.AnalysisServices.Tabular"
$logic = Get-Content "$PSScriptRoot\model_logic.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$pf = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$port = ([IO.File]::ReadAllText($pf.FullName, [Text.Encoding]::Unicode)).Trim()
$server = New-Object "$NS.Server"; $server.Connect("Data Source=localhost:$port")
$mt = $server.Databases[0].Model.Tables["Metrics"]
try {
    $changed = 0
    foreach ($x in $logic.measures) {
        $me = $mt.Measures[$x[0]]
        if (-not $me) { $me = New-Object "$NS.Measure"; $me.Name = $x[0]; $mt.Measures.Add($me) }
        if ($me.Expression -ne $x[3] -or $me.FormatString -ne $x[2] -or $me.DisplayFolder -ne $x[1] -or $me.Description -ne $x[4]) {
            $me.Expression = $x[3]; $me.FormatString = $x[2]; $me.DisplayFolder = $x[1]; $me.Description = $x[4]; $changed++
        }
    }
    $server.Databases[0].Model.SaveChanges() | Out-Null
    "Measures updated: $changed"
}
catch { $server.Databases[0].Model.UndoLocalChanges(); "FAILED: $($_.Exception.Message)"; exit 1 }
finally { $server.Disconnect() }

$base = "$env:TEMP\tom_nuget\microsoft.analysisservices.retail.amd64\lib\net45"
Add-Type -Path "$base\Microsoft.AnalysisServices.Core.dll"
Add-Type -Path "$base\Microsoft.AnalysisServices.Tabular.dll"
$pid2 = (Get-Process msmdsrv).Id
$pf = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$port = ([IO.File]::ReadAllText($pf.FullName, [Text.Encoding]::Unicode)).Trim()
"PORT $port"
$s = New-Object Microsoft.AnalysisServices.Tabular.Server
$s.Connect("Data Source=localhost:$port")
"DBs: $($s.Databases.Count)"
if ($s.Databases.Count) { $db=$s.Databases[0]; "DB $($db.Name) compat $($db.CompatibilityLevel)"
 foreach($t in $db.Model.Tables){ "T [$($t.Name)] cols=$($t.Columns.Count) meas=$($t.Measures.Count)"; foreach($p in $t.Partitions){ "  src: $($p.Source.Expression)" } } }
$s.Disconnect()

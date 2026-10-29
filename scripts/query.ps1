param([string]$q)
# a path to a .dax file avoids shell quoting problems with 'Table Name' references
if (Test-Path -LiteralPath $q) { $q = Get-Content -LiteralPath $q -Raw -Encoding UTF8 }
Add-Type -Path "$env:TEMP\tom_nuget\microsoft.analysisservices.adomdclient.retail.amd64\lib\net45\Microsoft.AnalysisServices.AdomdClient.dll"
$pf = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$port = ([IO.File]::ReadAllText($pf.FullName, [Text.Encoding]::Unicode)).Trim()
$c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port"); $c.Open()
$cmd = $c.CreateCommand(); $cmd.CommandText = $q; $r = $cmd.ExecuteReader()
$h = @(); for ($i=0; $i -lt $r.FieldCount; $i++) { $h += $r.GetName($i) }; $h -join " | "
while ($r.Read()) { $v=@(); for ($i=0; $i -lt $r.FieldCount; $i++) { $v += "$($r.GetValue($i))" }; $v -join " | " }
$r.Close(); $c.Close()

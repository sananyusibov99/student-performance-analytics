# Rebuild the open Power BI model as a star schema from data\model\*.csv.
# Inputs: model_spec.json (columns and types, from make_model_spec.py) and model_logic.json
# (table names, sort orders, relationships, calculated columns, measures).
param(
    [string]$DataFolder = (Resolve-Path "$PSScriptRoot\..\data\model").Path + "\",
    # metadata only; load data afterwards with refresh-tables.ps1 (table by table, with progress)
    [switch]$NoRefresh
)
$ErrorActionPreference = "Stop"
$base = "$env:TEMP\tom_nuget\microsoft.analysisservices.retail.amd64\lib\net45"
Add-Type -Path "$base\Microsoft.AnalysisServices.Core.dll"
Add-Type -Path "$base\Microsoft.AnalysisServices.Tabular.dll"
$NS = "Microsoft.AnalysisServices.Tabular"
$DT = [Microsoft.AnalysisServices.Tabular.DataType]

$spec  = Get-Content "$PSScriptRoot\model_spec.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$logic = Get-Content "$PSScriptRoot\model_logic.json" -Raw -Encoding UTF8 | ConvertFrom-Json

$pf = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$port = ([IO.File]::ReadAllText($pf.FullName, [Text.Encoding]::Unicode)).Trim()
# Timeout (seconds) covers the full refresh of the larger dataset
$server = New-Object "$NS.Server"; $server.Connect("Data Source=localhost:$port;Timeout=7200")
$model = $server.Databases[0].Model

function Set-Ann($obj, $name, $value) {
    if ($obj.Annotations.Contains($name)) { $obj.Annotations[$name].Value = $value }
    else { $a = New-Object "$NS.Annotation"; $a.Name = $name; $a.Value = $value; $obj.Annotations.Add($a) }
}
function Prop($o, $n) { $o.PSObject.Properties[$n] }

try {
    # ---- clear the old flat model ----
    foreach ($r in @($model.Relationships)) { $model.Relationships.Remove($r) }
    foreach ($t in @($model.Tables)) { $model.Tables.Remove($t) }
    foreach ($e in @($model.Expressions)) { $model.Expressions.Remove($e) }

    # ---- data folder parameter ----
    $p = New-Object "$NS.NamedExpression"; $p.Name = "DataFolder"; $p.Kind = [Microsoft.AnalysisServices.Tabular.ExpressionKind]::M
    $p.Expression = """$DataFolder"" meta [IsParameterQuery=true, Type=""Text"", IsParameterQueryRequired=true]"
    $p.Description = "Folder with the star-schema CSV files (data\model)"
    Set-Ann $p "PBI_ResultType" "Text"
    $model.Expressions.Add($p)

    # ---- tables from CSV ----
    $order = @("DataFolder")
    foreach ($csv in $spec.PSObject.Properties) {
        $name = (Prop $logic.tables $csv.Name).Value
        $order += $name
        $cols = $csv.Value
        $types = ($cols | ForEach-Object {
            $mt = switch ($_[1]) { "Int64" { "Int64.Type" } "Double" { "type number" } "DateTime" { "type date" } "Boolean" { "type logical" } default { "type text" } }
            "{""$($_[0])"", $mt}"
        }) -join ", "
        $steps = ""; $prev = "Typed"; $i = 0
        $ord = Prop $logic.orders $name
        if ($ord) {
            foreach ($o in $ord.Value.PSObject.Properties) {
                $i++; $list = ($o.Value | ForEach-Object { """$_""" }) -join ", "
                $steps += ",`n    Ord$i = Table.AddColumn($prev, ""$($o.Name) Order"", each List.PositionOf({$list}, [$($o.Name)]) + 1, Int64.Type)"
                $prev = "Ord$i"
            }
        }
        $m = @"
let
    Source = Csv.Document(File.Contents(DataFolder & "$($csv.Name).csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted)),
    Typed = Table.TransformColumnTypes(Blanks, {$types}, "en-US")$steps
in
    $prev
"@
        $t = New-Object "$NS.Table"; $t.Name = $name
        $t.Description = "Source: data\model\$($csv.Name).csv"
        $part = New-Object "$NS.Partition"; $part.Name = $name
        $src = New-Object "$NS.MPartitionSource"; $src.Expression = $m; $part.Source = $src
        $t.Partitions.Add($part)
        $rename = Prop $logic.columnNames $name
        foreach ($c in $cols) {
            # friendly model name where columnNames defines one; SourceColumn stays the CSV header
            $friendly = if ($rename -and (Prop $rename.Value $c[0])) { (Prop $rename.Value $c[0]).Value } else { $c[0] }
            $dc = New-Object "$NS.DataColumn"; $dc.Name = $friendly; $dc.SourceColumn = $c[0]
            $dc.DataType = $DT::($c[1])
            if ($c[1] -ne "String" -and $c[1] -ne "Boolean") { $dc.SummarizeBy = [Microsoft.AnalysisServices.Tabular.AggregateFunction]::None }
            if ($c[0] -like "*_key") { $dc.IsHidden = $true }
            if ($c[1] -eq "DateTime") { $dc.FormatString = "yyyy-mm-dd" }
            $t.Columns.Add($dc)
        }
        if ($ord) {
            foreach ($o in $ord.Value.PSObject.Properties) {
                $oc = New-Object "$NS.DataColumn"; $oc.Name = "$($o.Name) Order"; $oc.SourceColumn = "$($o.Name) Order"
                $oc.DataType = $DT::Int64; $oc.IsHidden = $true
                $oc.SummarizeBy = [Microsoft.AnalysisServices.Tabular.AggregateFunction]::None
                $t.Columns.Add($oc)
                $t.Columns[$o.Name].SortByColumn = $oc
            }
        }
        $key = Prop $logic.keys $name
        if ($key) { $t.Columns[$key.Value].IsKey = $true }
        Set-Ann $t "PBI_ResultType" "Table"
        Set-Ann $t "PBI_NavigationStepName" "Navigation"
        $model.Tables.Add($t)
    }
    $model.Tables["Date"].DataCategory = "Time"

    # ---- relationships (many -> one, single direction) ----
    foreach ($r in $logic.relationships) {
        $rel = New-Object "$NS.SingleColumnRelationship"
        $rel.Name = "$($r[0])_$($r[1])"
        $rel.FromColumn = $model.Tables[$r[0]].Columns[$r[1]]
        $rel.ToColumn = $model.Tables[$r[2]].Columns[$r[3]]
        $rel.FromCardinality = [Microsoft.AnalysisServices.Tabular.RelationshipEndCardinality]::Many
        $rel.ToCardinality = [Microsoft.AnalysisServices.Tabular.RelationshipEndCardinality]::One
        $model.Relationships.Add($rel)
    }

    # ---- calculated columns and bands ----
    function Add-Calc($table, $name, $type, $expr, $folder) {
        $c = New-Object "$NS.CalculatedColumn"; $c.Name = $name; $c.Expression = $expr
        $c.DataType = $DT::$type; if ($folder) { $c.DisplayFolder = $folder }
        $model.Tables[$table].Columns.Add($c); $c
    }
    foreach ($cc in $logic.calcColumns) { [void](Add-Calc $cc[0] $cc[1] $cc[2] $cc[3] $null) }
    foreach ($b in $logic.bands) {
        $table, $label, $col, $edges, $labels = $b
        $lbl = "SWITCH ( TRUE (), ISBLANK ( '$table'[$col] ), BLANK ()"; $ordx = "SWITCH ( TRUE (), ISBLANK ( '$table'[$col] ), BLANK ()"
        for ($i = 0; $i -lt $edges.Count; $i++) {
            $lbl += ", '$table'[$col] < $($edges[$i]), ""$($labels[$i])"""
            $ordx += ", '$table'[$col] < $($edges[$i]), $($i + 1)"
        }
        $lbl += ", ""$($labels[-1])"" )"; $ordx += ", $($labels.Count) )"
        $l = Add-Calc $table $label "String" $lbl "Bands"
        $o = Add-Calc $table "$label Order" "Int64" $ordx "Bands"; $o.IsHidden = $true
        $l.SortByColumn = $o
    }
    # sort-by may target calculated columns, so it runs after they exist
    foreach ($s in $logic.sortBy) { $model.Tables[$s[0]].Columns[$s[1]].SortByColumn = $model.Tables[$s[0]].Columns[$s[2]] }
    foreach ($h in $logic.hidden) { $model.Tables[$h[0]].Columns[$h[1]].IsHidden = $true }

    # ---- measures ----
    $mt = New-Object "$NS.Table"; $mt.Name = "Metrics"; $mt.Description = "KPI measures"
    $mp = New-Object "$NS.Partition"; $mp.Name = "Metrics"
    $ms = New-Object "$NS.CalculatedPartitionSource"; $ms.Expression = "ROW ( ""x"", BLANK () )"; $mp.Source = $ms
    $mt.Partitions.Add($mp)
    $hc = New-Object "$NS.CalculatedTableColumn"; $hc.Name = "x"; $hc.SourceColumn = "[x]"; $hc.IsNameInferred = $true; $hc.IsHidden = $true
    $hc.DataType = $DT::String; $mt.Columns.Add($hc)
    foreach ($x in $logic.measures) {
        $me = New-Object "$NS.Measure"; $me.Name = $x[0]; $me.DisplayFolder = $x[1]
        $me.FormatString = $x[2]; $me.Expression = $x[3]; $me.Description = $x[4]
        $mt.Measures.Add($me)
    }
    $model.Tables.Add($mt)

    Set-Ann $model "PBI_QueryOrder" ("[" + (($order | ForEach-Object { """$_""" }) -join ",") + "]")
    $model.SaveChanges() | Out-Null
    "Metadata saved: $($model.Tables.Count) tables, $($model.Relationships.Count) relationships, $($logic.measures.Count) measures"
    if ($NoRefresh) { return }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full)
    $model.SaveChanges() | Out-Null
    "Refresh done in $([int]$sw.Elapsed.TotalSeconds) s"
}
catch {
    $model.UndoLocalChanges()
    "FAILED: $($_.Exception.Message)"
    exit 1
}
finally { $server.Disconnect() }

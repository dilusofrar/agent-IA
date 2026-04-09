param(
    [string]$CsvPath = "",
    [string]$TemplatePath = "",
    [string]$OutputPath = "",
    [string]$ModulePath = "",
    [string]$WorksheetName = "Folha1"
)

$vbsPath = Join-Path $PSScriptRoot "testar_macro_planilha.vbs"

$arguments = @(
    ('"' + $vbsPath + '"')
    ('"' + $CsvPath + '"')
    ('"' + $TemplatePath + '"')
    ('"' + $OutputPath + '"')
    ('"' + $ModulePath + '"')
    ('"' + $WorksheetName + '"')
)

& cscript //nologo @arguments
exit $LASTEXITCODE

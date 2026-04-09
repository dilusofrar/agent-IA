Option Explicit

Const MAX_RETRIES = 20
Const RETRY_DELAY_MS = 500

Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")

Dim scriptFolder, projectRoot
scriptFolder = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(scriptFolder)

Dim csvPath, templatePath, outputPath, modulePath, worksheetName
csvPath = ResolveArgument(0, projectRoot & "\data\outputs\DIEGO_LUCAS_SOARES_DE_FREITAS_ARAUJO_extraido.csv")
templatePath = ResolveArgument(1, projectRoot & "\data\templates\HORAS.xlsm")
outputPath = ResolveArgument(2, projectRoot & "\data\outputs\HORAS_teste_macro.xlsm")
modulePath = ResolveArgument(3, projectRoot & "\docs\vba_importar_pontos.bas")
worksheetName = ResolveArgument(4, "Folha1")

If Not fso.FileExists(csvPath) Then
    WScript.Echo "CSV nao encontrado: " & csvPath
    WScript.Quit 1
End If

If Not fso.FileExists(templatePath) Then
    WScript.Echo "Planilha modelo nao encontrada: " & templatePath
    WScript.Quit 1
End If

If Not fso.FileExists(modulePath) Then
    WScript.Echo "Modulo VBA nao encontrado: " & modulePath
    WScript.Quit 1
End If

On Error Resume Next
If fso.FileExists(outputPath) Then
    fso.DeleteFile outputPath, True
End If
On Error GoTo 0

fso.CopyFile templatePath, outputPath, True

Dim excel, workbook, worksheet
Set excel = CreateObject("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
excel.ScreenUpdating = False
excel.EnableEvents = False
excel.AutomationSecurity = 1

Set workbook = RetryOpenWorkbook(excel, outputPath)
If workbook Is Nothing Then
    SafeQuit excel, workbook
    WScript.Echo "Nao foi possivel abrir a planilha no Excel."
    WScript.Quit 2
End If

Set worksheet = RetryGetWorksheet(workbook, worksheetName)
If worksheet Is Nothing Then
    SafeQuit excel, workbook
    WScript.Echo "Nao foi possivel localizar a planilha '" & worksheetName & "'."
    WScript.Quit 3
End If

RetryActivateSheet worksheet
RetryRemoveModule workbook, "ImportarPontos"

If Not RetryImportModule(workbook, modulePath) Then
    SafeQuit excel, workbook
    WScript.Echo "Falha ao importar o modulo VBA. Verifique se o Excel confia no acesso ao projeto VBA."
    WScript.Quit 4
End If

If Not RetryRunMacro(excel, workbook.Name, csvPath, worksheetName) Then
    SafeQuit excel, workbook
    WScript.Echo "Falha ao executar o macro automatizado."
    WScript.Quit 5
End If

RetrySaveWorkbook workbook

WScript.Echo "Arquivo de teste gerado: " & outputPath
PrintValidation worksheet, "16/abr"
PrintValidation worksheet, "17/abr"
PrintValidation worksheet, "05/mai"
PrintValidation worksheet, "15/mai"

SafeQuit excel, workbook
WScript.Quit 0

Function ResolveArgument(index, fallbackValue)
    If WScript.Arguments.Count > index Then
        If Trim(WScript.Arguments(index)) <> "" Then
            ResolveArgument = WScript.Arguments(index)
            Exit Function
        End If
    End If

    ResolveArgument = fallbackValue
End Function

Function RetryOpenWorkbook(excelApp, workbookPath)
    Dim attempt
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        Set RetryOpenWorkbook = excelApp.Workbooks.Open(workbookPath)
        If Err.Number = 0 Then
            Exit Function
        End If
        Set RetryOpenWorkbook = Nothing
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Function

Function RetryGetWorksheet(book, name)
    Dim attempt
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        Set RetryGetWorksheet = book.Worksheets(name)
        If Err.Number = 0 Then
            Exit Function
        End If
        Set RetryGetWorksheet = Nothing
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Function

Sub RetryActivateSheet(sheet)
    Dim attempt
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        sheet.Activate
        If Err.Number = 0 Then
            Exit Sub
        End If
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Sub

Sub RetryRemoveModule(book, moduleName)
    Dim attempt, component
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        Set component = book.VBProject.VBComponents.Item(moduleName)
        If Err.Number <> 0 Then
            Err.Clear
            Exit Sub
        End If
        book.VBProject.VBComponents.Remove component
        If Err.Number = 0 Then
            Exit Sub
        End If
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Sub

Function RetryImportModule(book, moduleFile)
    Dim attempt
    RetryImportModule = False
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        book.VBProject.VBComponents.Import moduleFile
        If Err.Number = 0 Then
            RetryImportModule = True
            Exit Function
        End If
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Function

Function RetryRunMacro(excelApp, workbookName, csvFile, targetSheet)
    Dim attempt
    RetryRunMacro = False
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        excelApp.Run "'" & workbookName & "'!PreencherHorariosDeArquivo", csvFile, targetSheet, True
        If Err.Number = 0 Then
            RetryRunMacro = True
            Exit Function
        End If
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Function

Sub RetrySaveWorkbook(book)
    Dim attempt
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        book.Save
        If Err.Number = 0 Then
            Exit Sub
        End If
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Sub

Function RetryFindRow(sheet, valueToFind)
    Dim attempt, foundCell
    RetryFindRow = 0
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        Set foundCell = sheet.Columns(5).Find(valueToFind)
        If Err.Number = 0 Then
            If Not foundCell Is Nothing Then
                RetryFindRow = foundCell.Row
            End If
            Exit Function
        End If
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Function

Function RetryCellText(sheet, rowNumber, columnNumber)
    Dim attempt
    RetryCellText = ""
    For attempt = 1 To MAX_RETRIES
        On Error Resume Next
        RetryCellText = sheet.Cells(rowNumber, columnNumber).Text
        If Err.Number = 0 Then
            Exit Function
        End If
        Err.Clear
        WScript.Sleep RETRY_DELAY_MS
    Next
    On Error GoTo 0
End Function

Sub PrintValidation(sheet, label)
    Dim rowNumber, entrada, saida
    rowNumber = RetryFindRow(sheet, label)
    If rowNumber = 0 Then
        WScript.Echo "Validacao: data " & label & " nao encontrada na coluna E."
        Exit Sub
    End If

    entrada = RetryCellText(sheet, rowNumber, 6)
    saida = RetryCellText(sheet, rowNumber, 9)
    WScript.Echo "Validacao: " & label & " | linha " & rowNumber & " | entrada=" & entrada & " | saida=" & saida
End Sub

Sub SafeQuit(excelApp, book)
    On Error Resume Next
    If Not book Is Nothing Then
        book.Close True
    End If
    If Not excelApp Is Nothing Then
        excelApp.Quit
    End If
    On Error GoTo 0
End Sub

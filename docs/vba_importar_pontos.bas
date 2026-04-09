Attribute VB_Name = "ImportarPontos"
Option Explicit

Sub PreencherHorariosExatos()
    Dim caminhoCSV As Variant

    caminhoCSV = Application.GetOpenFilename("Arquivos CSV (*.csv), *.csv", , "Selecione o arquivo CSV de cartao ponto")
    If caminhoCSV = False Then
        MsgBox "Nenhum arquivo selecionado. Operacao cancelada.", vbExclamation
        Exit Sub
    End If

    PreencherHorariosDeArquivo CStr(caminhoCSV)
End Sub

Sub PreencherHorariosDeArquivo(ByVal caminhoCSV As String, Optional ByVal nomePlanilha As String = "", Optional ByVal modoSilencioso As Boolean = False)
    Dim mesesMap As Object
    Dim dadosCSV As Object
    Dim fso As Object
    Dim arquivoCSV As Object
    Dim cabecalho As String
    Dim linha As String
    Dim colunas As Variant
    Dim dataOriginal As String
    Dim entrada As String
    Dim saida As String
    Dim partes As Variant
    Dim dia As String
    Dim mesEn As String
    Dim mesPt As String
    Dim dataPt As String
    Dim planilha As Worksheet
    Dim registrosPreenchidos As Long
    Dim ultimaLinha As Long
    Dim i As Long
    Dim valorCelula As String
    Dim chave As Variant
    Dim horarios As Variant

    Set mesesMap = CreateObject("Scripting.Dictionary")
    mesesMap.CompareMode = vbTextCompare
    mesesMap.Add "jan", "jan"
    mesesMap.Add "feb", "fev"
    mesesMap.Add "mar", "mar"
    mesesMap.Add "apr", "abr"
    mesesMap.Add "may", "mai"
    mesesMap.Add "jun", "jun"
    mesesMap.Add "jul", "jul"
    mesesMap.Add "aug", "ago"
    mesesMap.Add "sep", "set"
    mesesMap.Add "oct", "out"
    mesesMap.Add "nov", "nov"
    mesesMap.Add "dec", "dez"

    Set dadosCSV = CreateObject("Scripting.Dictionary")
    dadosCSV.CompareMode = vbTextCompare

    If Len(Trim$(caminhoCSV)) = 0 Then
        If Not modoSilencioso Then
            MsgBox "Caminho do CSV nao informado.", vbExclamation
        End If
        Exit Sub
    End If

    Set fso = CreateObject("Scripting.FileSystemObject")
    If Not fso.FileExists(caminhoCSV) Then
        If Not modoSilencioso Then
            MsgBox "Arquivo CSV nao encontrado: " & caminhoCSV, vbExclamation
        End If
        Exit Sub
    End If

    Set arquivoCSV = fso.OpenTextFile(caminhoCSV, 1)

    If arquivoCSV.AtEndOfStream Then
        arquivoCSV.Close
        If Not modoSilencioso Then
            MsgBox "O arquivo CSV esta vazio.", vbExclamation
        End If
        Exit Sub
    End If

    cabecalho = arquivoCSV.ReadLine

    Do Until arquivoCSV.AtEndOfStream
        linha = Trim$(arquivoCSV.ReadLine)
        If linha <> vbNullString Then
            colunas = Split(linha, ",")
            If UBound(colunas) >= 2 Then
                dataOriginal = Trim$(colunas(0))
                entrada = Trim$(colunas(1))
                saida = Trim$(colunas(2))

                partes = Split(dataOriginal, "/")
                If UBound(partes) >= 1 Then
                    dia = partes(0)
                    mesEn = LCase$(partes(1))

                    If mesesMap.Exists(mesEn) Then
                        mesPt = mesesMap(mesEn)
                    Else
                        mesPt = mesEn
                    End If

                    dataPt = dia & "/" & mesPt
                    dadosCSV(dataPt) = Array(entrada, saida)
                End If
            End If
        End If
    Loop

    arquivoCSV.Close

    If dadosCSV.Count = 0 Then
        If Not modoSilencioso Then
            MsgBox "Nenhum dado valido encontrado no CSV. Verifique o formato do arquivo.", vbExclamation
        End If
        Exit Sub
    End If

    Set planilha = ObterPlanilhaDestino(nomePlanilha)
    If planilha Is Nothing Then
        If Not modoSilencioso Then
            MsgBox "Nao foi possivel localizar a planilha de destino.", vbExclamation
        End If
        Exit Sub
    End If

    registrosPreenchidos = 0
    ultimaLinha = planilha.Cells(planilha.Rows.Count, 5).End(xlUp).Row

    For i = 1 To ultimaLinha
        valorCelula = LCase$(Trim$(planilha.Cells(i, 5).Text))
        If valorCelula <> vbNullString Then
            For Each chave In dadosCSV.Keys
                If InStr(1, valorCelula, LCase$(CStr(chave)), vbTextCompare) > 0 Then
                    horarios = dadosCSV(chave)
                    planilha.Cells(i, 6).Value = horarios(0)
                    planilha.Cells(i, 9).Value = horarios(1)
                    registrosPreenchidos = registrosPreenchidos + 1
                    Exit For
                End If
            Next chave
        End If
    Next i

    If Not modoSilencioso Then
        MsgBox "Preenchimento concluido. " & registrosPreenchidos & " registros foram preenchidos.", vbInformation
    End If
End Sub

Private Function ObterPlanilhaDestino(Optional ByVal nomePlanilha As String = "") As Worksheet
    If Len(Trim$(nomePlanilha)) > 0 Then
        On Error Resume Next
        Set ObterPlanilhaDestino = ThisWorkbook.Worksheets(nomePlanilha)
        On Error GoTo 0
        Exit Function
    End If

    If Not ActiveSheet Is Nothing Then
        Set ObterPlanilhaDestino = ActiveSheet
        Exit Function
    End If

    On Error Resume Next
    Set ObterPlanilhaDestino = ThisWorkbook.Worksheets("Folha1")
    On Error GoTo 0
End Function

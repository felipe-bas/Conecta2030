
    Set WshShell = WScript.CreateObject("WScript.Shell")
    command = "cmd /c title SCP_Transfer_53 & echo Sending obu_alert_server... & scp -o StrictHostKeyChecking=no C:\Users\ferob\Downloads\conecta2030\obu_alert_server root@192.168.0.53:/tmp/obu_alert_server"
    WshShell.Run command
    
    WScript.Sleep 1500
    
    success = False
    For i = 1 To 10
        If WshShell.AppActivate("SCP_Transfer_53") Then
            success = True
            Exit For
        End If
        WScript.Sleep 500
    Next
    
    If success Then
        WScript.Sleep 500
        WshShell.SendKeys "Conect@24"
        WshShell.SendKeys "{ENTER}"
    End If
    
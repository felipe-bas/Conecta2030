
    Set WshShell = WScript.CreateObject("WScript.Shell")
    
    ' Launch CMD and run SSH
    ' /k keeps the window open
    ' Added -o StrictHostKeyChecking=no to prevent yes/no prompt blocking the password
    command = "cmd /k title RSU_Server_Console & color 0A & echo Connecting to RSU_Server_Console... & ssh -t -o StrictHostKeyChecking=no root@192.168.0.56 ""/tmp/fac_alert_server"""
    WshShell.Run command
    
    ' Wait for the window to appear
    WScript.Sleep 2000 
    
    ' Activate the window by title
    success = False
    For i = 1 To 20  ' Increased retries to 10 seconds total
        If WshShell.AppActivate("RSU_Server_Console") Then
            success = True
            Exit For
        End If
        WScript.Sleep 500
    Next
    
    If success Then
        ' Wait for SSH to initialize and prompt for password
        WScript.Sleep 2000
        ' Send Password
        WshShell.SendKeys "Conect@2024"
        WshShell.SendKeys "{ENTER}"
    End If
    
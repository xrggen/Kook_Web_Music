param([string]$OutputPath = (Join-Path $PSScriptRoot '../wechat-miniapp/assets/kook-console.png'))
Add-Type -AssemblyName System.Drawing
$taskIconPath = [IO.Path]::GetFullPath($OutputPath)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskIconPath)) | Out-Null
$taskBitmap = New-Object Drawing.Bitmap 96,96
$taskGraphics = [Drawing.Graphics]::FromImage($taskBitmap)
$taskGraphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
$taskGraphics.Clear([Drawing.Color]::FromArgb(238,245,255))
$taskPen = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(22,119,255)),4
$taskBrush = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(22,119,255))
$taskGraphics.DrawRectangle($taskPen,24,29,48,45)
$taskGraphics.DrawLine($taskPen,48,18,48,29)
$taskGraphics.FillEllipse($taskBrush,44,13,8,8)
$taskGraphics.DrawLine($taskPen,17,41,17,61)
$taskGraphics.DrawLine($taskPen,79,41,79,61)
$taskGraphics.FillEllipse($taskBrush,34,40,8,8)
$taskGraphics.FillEllipse($taskBrush,54,40,8,8)
$taskGraphics.DrawLine($taskPen,35,61,61,61)
$taskBitmap.Save($taskIconPath,[Drawing.Imaging.ImageFormat]::Png)
$taskBrush.Dispose(); $taskPen.Dispose(); $taskGraphics.Dispose(); $taskBitmap.Dispose()
Write-Output 'Generated KOOK native tool icon'

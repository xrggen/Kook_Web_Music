param([string]$OutputDirectory = (Join-Path $PSScriptRoot '../wechat-miniapp/assets/ui'))
# Source-owned, reproducible 24-unit line icons. No fonts, emoji or remote assets.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$iconOutputRoot = [IO.Path]::GetFullPath($OutputDirectory)
$iconPalette = @{
    light = @{ accent = '#6758e7'; muted = '#7a8493' }
    dark = @{ accent = '#7467f4'; muted = '#7f8794' }
}
$iconNames = @('server','more','activity','users','settings','lock','help','logout','arrow-left','music','user','play','channel')
function Draw-Line([single]$x1,[single]$y1,[single]$x2,[single]$y2) { $iconGraphics.DrawLine($iconPen,$x1,$y1,$x2,$y2) }
function Draw-Circle([single]$x,[single]$y,[single]$size) { $iconGraphics.DrawEllipse($iconPen,$x,$y,$size,$size) }
function Draw-RoundRect([single]$x,[single]$y,[single]$width,[single]$height,[single]$radius = 2) {
    $shape = [Drawing.Drawing2D.GraphicsPath]::new()
    try {
        $diameter = 2 * $radius
        $shape.AddArc($x,$y,$diameter,$diameter,180,90)
        $shape.AddArc(($x+$width-$diameter),$y,$diameter,$diameter,270,90)
        $shape.AddArc(($x+$width-$diameter),($y+$height-$diameter),$diameter,$diameter,0,90)
        $shape.AddArc($x,($y+$height-$diameter),$diameter,$diameter,90,90)
        $shape.CloseFigure(); $iconGraphics.DrawPath($iconPen,$shape)
    } finally { $shape.Dispose() }
}
function Draw-Polyline([single[]]$coordinates) {
    for ($index = 0; $index -lt $coordinates.Length - 2; $index += 2) {
        Draw-Line $coordinates[$index] $coordinates[$index+1] $coordinates[$index+2] $coordinates[$index+3]
    }
}
foreach ($theme in @('light','dark')) {
    foreach ($tone in @('accent','muted')) {
        $iconFolder = Join-Path (Join-Path $iconOutputRoot $theme) $tone
        [IO.Directory]::CreateDirectory($iconFolder) | Out-Null
        foreach ($iconName in $iconNames) {
            $iconBitmap = [Drawing.Bitmap]::new(96,96,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
            $iconGraphics = [Drawing.Graphics]::FromImage($iconBitmap)
            $iconColor = [Drawing.ColorTranslator]::FromHtml($iconPalette[$theme][$tone])
            $iconPen = [Drawing.Pen]::new($iconColor,1.8)
            $iconBrush = [Drawing.SolidBrush]::new($iconColor)
            try {
                $iconGraphics.Clear([Drawing.Color]::Transparent)
                $iconGraphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
                $iconGraphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $iconGraphics.ScaleTransform(4,4)
                $iconPen.StartCap = $iconPen.EndCap = [Drawing.Drawing2D.LineCap]::Round
                $iconPen.LineJoin = [Drawing.Drawing2D.LineJoin]::Round
                switch ($iconName) {
                    server {
                        Draw-RoundRect 3 3 18 7; Draw-RoundRect 3 14 18 7
                        $iconGraphics.FillEllipse($iconBrush,6,5.5,2,2); $iconGraphics.FillEllipse($iconBrush,6,16.5,2,2)
                        Draw-Line 12 6.5 17.5 6.5; Draw-Line 12 17.5 17.5 17.5
                    }
                    more { Draw-RoundRect 3 3 7 7 1.5; Draw-RoundRect 14 3 7 7 1.5; Draw-RoundRect 3 14 7 7 1.5; Draw-RoundRect 14 14 7 7 1.5 }
                    activity { Draw-Polyline @(2,12,6,12,9,5,14,19,17,12,22,12) }
                    users {
                        Draw-Circle 5 3.5 6; $iconGraphics.DrawArc($iconPen,2,13,12,11,180,180)
                        $iconGraphics.DrawArc($iconPen,13,4,6,6,255,220); $iconGraphics.DrawArc($iconPen,13,13,9,10,250,110)
                    }
                    settings {
                        Draw-Circle 6 6 12; Draw-Circle 9.5 9.5 5
                        for ($tooth = 0; $tooth -lt 8; $tooth++) {
                            $angle = $tooth * [Math]::PI / 4
                            Draw-Line (12+6.5*[Math]::Cos($angle)) (12+6.5*[Math]::Sin($angle)) (12+9*[Math]::Cos($angle)) (12+9*[Math]::Sin($angle))
                        }
                    }
                    lock {
                        Draw-RoundRect 5 10 14 11 2; $iconGraphics.DrawArc($iconPen,8,3,8,14,180,180)
                        $iconGraphics.FillEllipse($iconBrush,11,14,2,2); Draw-Line 12 15 12 17
                    }
                    help {
                        Draw-Circle 2.5 2.5 19
                        $iconGraphics.DrawBezier($iconPen,9,8,9,5,16,5,15,9)
                        $iconGraphics.DrawBezier($iconPen,15,9,14.5,11,12,10.5,12,13)
                        $iconGraphics.FillEllipse($iconBrush,11.1,16,1.8,1.8)
                    }
                    logout { Draw-Polyline @(10,3,4,3,4,21,10,21); Draw-Line 9 12 21 12; Draw-Polyline @(17,8,21,12,17,16) }
                    arrow-left { Draw-Line 4 12 21 12; Draw-Polyline @(10,5,3,12,10,19) }
                    music {
                        Draw-Polyline @(8,17,8,5,20,3,20,15)
                        Draw-Line 8 9 20 7
                        $iconGraphics.FillEllipse($iconBrush,3,15,5,4); $iconGraphics.FillEllipse($iconBrush,15,13,5,4)
                    }
                    user { Draw-Circle 8 3 8; $iconGraphics.DrawArc($iconPen,4,14,16,12,180,180); Draw-Line 4 20 20 20 }
                    play { Draw-Circle 2.5 2.5 19; Draw-Polyline @(10,7.5,16,12,10,16.5,10,7.5) }
                    channel {
                        Draw-Polyline @(4,9,8,9,13,5,13,19,8,15,4,15,4,9)
                        $iconGraphics.DrawArc($iconPen,10,7,7,10,280,160); $iconGraphics.DrawArc($iconPen,9,3,12,18,290,140)
                    }
                }
                $iconBitmap.Save((Join-Path $iconFolder ($iconName+'.png')),[Drawing.Imaging.ImageFormat]::Png)
            } finally { $iconBrush.Dispose(); $iconPen.Dispose(); $iconGraphics.Dispose(); $iconBitmap.Dispose() }
        }
    }
}
Write-Output ('Generated {0} native line icons in {1}' -f ($iconNames.Count * 4),$iconOutputRoot)

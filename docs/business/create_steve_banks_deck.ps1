$ErrorActionPreference = "Stop"

$root = "C:\Users\might\OneDrive\Desktop\InspectorPro"
$outPath = Join-Path $root "AI-Drawing-Inspector\docs\business\InspectorPro_Steve_Banks_Conversation_Deck.pptx"
$savedPath = $outPath
$renderDir = Join-Path $root "AI-Drawing-Inspector\docs\business\steve_banks_render"
$logoPath = Join-Path $root "InspectorPro_TitleBlock_Logo_Transparent_1200w.png"
$prototypePath = Join-Path $root "pic3.png"

New-Item -ItemType Directory -Force -Path (Split-Path $outPath) | Out-Null
New-Item -ItemType Directory -Force -Path $renderDir | Out-Null

function OleColor([int]$r, [int]$g, [int]$b) {
    return ($r -bor ($g -shl 8) -bor ($b -shl 16))
}

$C = @{
    Navy     = OleColor 12 24 36
    Ink      = OleColor 19 28 39
    Blue     = OleColor 45 164 232
    BlueDark = OleColor 24 112 166
    Teal     = OleColor 28 103 128
    Steel    = OleColor 92 116 138
    PaleBlue = OleColor 230 244 252
    PaleGray = OleColor 244 247 250
    MidGray  = OleColor 214 222 230
    DarkGray = OleColor 73 84 96
    White    = OleColor 255 255 255
    Orange   = OleColor 226 142 50
    Green    = OleColor 0 151 103
}

$ppLayoutBlank = 12
$ppSaveAsOpenXMLPresentation = 24
$msoTrue = -1
$msoFalse = 0
$msoShapeRectangle = 1
$msoShapeRoundedRectangle = 5
$msoShapeOval = 9
$msoConnectorCurve = 3
$msoLineSolid = 1
$msoLineDash = 4
$msoArrowheadTriangle = 3
$ppAlignLeft = 1
$ppAlignCenter = 2

function Lerp-Byte([int]$a, [int]$b, [double]$t) {
    return [int][Math]::Round($a + (($b - $a) * $t))
}

function Get-ViewportGradientColor([double]$p) {
    $edge = @(238, 243, 247)
    $mid = @(210, 219, 227)
    $center = @(183, 195, 204)

    if ($p -le 0.28) {
        $from = $edge; $to = $mid; $t = $p / 0.28
    } elseif ($p -le 0.50) {
        $from = $mid; $to = $center; $t = ($p - 0.28) / 0.22
    } elseif ($p -le 0.72) {
        $from = $center; $to = $mid; $t = ($p - 0.50) / 0.22
    } else {
        $from = $mid; $to = $edge; $t = ($p - 0.72) / 0.28
    }

    return OleColor `
        (Lerp-Byte $from[0] $to[0] $t) `
        (Lerp-Byte $from[1] $to[1] $t) `
        (Lerp-Byte $from[2] $to[2] $t)
}

function Add-ViewportBackground($slide) {
    $bands = 80
    $bandHeight = 540 / $bands
    for ($i = 0; $i -lt $bands; $i++) {
        $p = ($i + 0.5) / $bands
        $band = $slide.Shapes.AddShape($msoShapeRectangle, 0, ($i * $bandHeight), 960, ($bandHeight + 0.8))
        $band.Fill.ForeColor.RGB = Get-ViewportGradientColor $p
        $band.Line.Visible = $msoFalse
    }
}

function Invoke-ComRetry([scriptblock]$action) {
    $lastError = $null
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
        try {
            return & $action
        } catch {
            $lastError = $_
            $message = $_.Exception.Message
            if ($message -notmatch "Call was rejected|RPC_E_CALL_REJECTED") {
                throw
            }
            Start-Sleep -Milliseconds (250 * ($attempt + 1))
        }
    }
    throw $lastError
}

function Set-TextStyle($shape, [double]$size, $color, [bool]$bold = $false, [int]$align = 1) {
    Invoke-ComRetry {
        $tr = $shape.TextFrame.TextRange
        $tr.Font.Name = "Aptos"
        $tr.Font.Size = $size
        $tr.Font.Color.RGB = $color
        $tr.Font.Bold = if ($bold) { -1 } else { 0 }
        $tr.ParagraphFormat.Alignment = $align
        $shape.TextFrame.WordWrap = $msoTrue
    } | Out-Null
}

function Add-Text($slide, [string]$text, [double]$x, [double]$y, [double]$w, [double]$h, [double]$size, $color, [bool]$bold = $false, [int]$align = 1) {
    $shape = $slide.Shapes.AddTextbox(1, $x, $y, $w, $h)
    Invoke-ComRetry {
        try {
            $shape.TextFrame.TextRange.Text = $text
        } catch {
            $shape.TextFrame2.TextRange.Text = $text
        }
        $shape.TextFrame.MarginLeft = 0
        $shape.TextFrame.MarginRight = 0
        $shape.TextFrame.MarginTop = 0
        $shape.TextFrame.MarginBottom = 0
    } | Out-Null
    Set-TextStyle $shape $size $color $bold $align
    return $shape
}

function Add-Header($slide, [string]$eyebrow = "Engineering intelligence for every manufacturing workflow.") {
    if (Test-Path $logoPath) {
        $slide.Shapes.AddPicture($logoPath, $msoFalse, $msoTrue, 28, 18, 118, 34) | Out-Null
    } else {
        Add-Text $slide "InspectorPro" 28 18 140 32 18 $C.Ink $true | Out-Null
    }
    Add-Text $slide $eyebrow 710 25 220 18 8.5 $C.Steel $false $ppAlignLeft | Out-Null
    $line = $slide.Shapes.AddLine(28, 62, 932, 62)
    $line.Line.ForeColor.RGB = $C.MidGray
    $line.Line.Weight = 1
}

function Add-Title($slide, [string]$title, [string]$subtitle = "") {
    Add-Text $slide $title 48 82 700 48 27 $C.Ink $true | Out-Null
    if ($subtitle) {
        Add-Text $slide $subtitle 50 126 760 34 12.5 $C.DarkGray $false | Out-Null
    }
}

function Add-Card($slide, [string]$title, [string]$body, [double]$x, [double]$y, [double]$w, [double]$h, $accentColor = $null) {
    if ($null -eq $accentColor) { $accentColor = $C.Blue }
    $card = $slide.Shapes.AddShape($msoShapeRoundedRectangle, $x, $y, $w, $h)
    $card.Fill.ForeColor.RGB = $C.White
    $card.Line.ForeColor.RGB = $C.MidGray
    $card.Line.Weight = 1
    $bar = $slide.Shapes.AddShape($msoShapeRectangle, $x, $y, 5, $h)
    $bar.Fill.ForeColor.RGB = $accentColor
    $bar.Line.Visible = $msoFalse
    Add-Text $slide $title ($x + 15) ($y + 12) ($w - 24) 18 12.5 $C.Ink $true | Out-Null
    Add-Text $slide $body ($x + 15) ($y + 36) ($w - 25) ($h - 42) 10 $C.DarkGray $false | Out-Null
}

function Add-FlatCard($slide, [string]$title, [string]$body, [double]$x, [double]$y, [double]$w, [double]$h, $accentColor = $null) {
    if ($null -eq $accentColor) { $accentColor = $C.Blue }
    $card = $slide.Shapes.AddShape($msoShapeRectangle, $x, $y, $w, $h)
    $card.Fill.ForeColor.RGB = $C.White
    $card.Line.ForeColor.RGB = $C.MidGray
    $card.Line.Weight = 0.9
    $bar = $slide.Shapes.AddShape($msoShapeRectangle, $x, $y, 4, $h)
    $bar.Fill.ForeColor.RGB = $accentColor
    $bar.Line.Visible = $msoFalse
    Add-Text $slide $title ($x + 14) ($y + 11) ($w - 24) 16 11.8 $C.Ink $true | Out-Null
    Add-Text $slide $body ($x + 14) ($y + 33) ($w - 25) ($h - 38) 9.4 $C.DarkGray $false | Out-Null
}

function Add-Pill($slide, [string]$text, [double]$x, [double]$y, [double]$w, [double]$h, $fillColor, $fontColor = $null) {
    if ($null -eq $fontColor) { $fontColor = $C.White }
    $pill = $slide.Shapes.AddShape($msoShapeRoundedRectangle, $x, $y, $w, $h)
    $pill.Fill.ForeColor.RGB = $fillColor
    $pill.Line.Visible = $msoFalse
    Add-Text $slide $text ($x + 10) ($y + 5) ($w - 20) ($h - 8) 10 $fontColor $true $ppAlignCenter | Out-Null
}

function Add-Connector($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2, $color, [bool]$dashed = $false, [double]$weight = 1.4, [bool]$arrow = $false) {
    $line = $slide.Shapes.AddLine($x1, $y1, $x2, $y2)
    $line.Line.ForeColor.RGB = $color
    $line.Line.Weight = $weight
    $line.Line.DashStyle = if ($dashed) { $msoLineDash } else { $msoLineSolid }
    if ($arrow) {
        $line.Line.EndArrowheadStyle = $msoArrowheadTriangle
    }
    return $line
}

function Add-DoubleConnector($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2, $color, [bool]$dashed = $false, [double]$weight = 1.4) {
    $line = Add-Connector $slide $x1 $y1 $x2 $y2 $color $dashed $weight $true
    $line.Line.BeginArrowheadStyle = $msoArrowheadTriangle
    return $line
}

function Add-CurveConnector($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2, $color, [bool]$dashed = $false, [double]$weight = 1.4, [bool]$arrow = $false) {
    $line = $slide.Shapes.AddConnector($msoConnectorCurve, $x1, $y1, $x2, $y2)
    $line.Line.ForeColor.RGB = $color
    $line.Line.Weight = $weight
    $line.Line.DashStyle = if ($dashed) { $msoLineDash } else { $msoLineSolid }
    if ($arrow) {
        $line.Line.EndArrowheadStyle = $msoArrowheadTriangle
    }
    return $line
}

function Add-DeptNode($slide, [string]$text, [double]$x, [double]$y, [double]$w, [double]$h, $fillColor, $lineColor = $null, $fontColor = $null) {
    if ($null -eq $lineColor) { $lineColor = $C.MidGray }
    if ($null -eq $fontColor) { $fontColor = $C.Ink }
    $node = $slide.Shapes.AddShape($msoShapeRoundedRectangle, $x, $y, $w, $h)
    $node.Fill.ForeColor.RGB = $fillColor
    $node.Line.ForeColor.RGB = $lineColor
    $node.Line.Weight = 1
    Add-Text $slide $text ($x + 5) ($y + 6) ($w - 10) ($h - 10) 8.4 $fontColor $true $ppAlignCenter | Out-Null
    return $node
}

function Add-Footer($slide, [string]$text) {
    Add-Text $slide $text 48 507 860 18 9 $C.Steel $false $ppAlignCenter | Out-Null
}

$ppt = $null
$pres = $null
try {
    $ppt = New-Object -ComObject PowerPoint.Application
    $ppt.Visible = $msoTrue
    $pres = $ppt.Presentations.Add($msoTrue)
    $pres.PageSetup.SlideWidth = 960
    $pres.PageSetup.SlideHeight = 540

    # Title slide
    $s = $pres.Slides.Add(1, $ppLayoutBlank)
    Add-ViewportBackground $s
    if (Test-Path $logoPath) {
        $s.Shapes.AddPicture($logoPath, $msoFalse, $msoTrue, 252, 118, 456, 130) | Out-Null
    } else {
        Add-Text $s "InspectorPro" 260 132 440 80 44 $C.Ink $true $ppAlignCenter | Out-Null
    }
    Add-Text $s "Cross-functional product-context AI for manufacturing" 160 275 640 34 20 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Text $s "Connecting CAD, drawings, FAI, BOM, suppliers, and department knowledge into role-aware manufacturing decisions." 170 322 620 42 13.5 $C.DarkGray $false $ppAlignCenter | Out-Null
    Add-Pill $s "Conversation deck for Steve Banks / Improving Minnesota" 286 400 388 30 $C.BlueDark
    Add-Text $s "June 2026" 410 454 140 18 10.5 $C.Steel $false $ppAlignCenter | Out-Null

    # Slide 1
    $s = $pres.Slides.Add(2, $ppLayoutBlank)
    Add-ViewportBackground $s
    Add-Header $s "Conversation deck for Steve Banks / Improving Minnesota."
    Add-Text $s "Before: scattered context" 42 84 410 28 18 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Text $s "Data exists, but it is loosely connected or only searchable." 62 119 370 22 10.5 $C.DarkGray $false $ppAlignCenter | Out-Null

    $beforeBox = $s.Shapes.AddShape($msoShapeRoundedRectangle, 30, 154, 460, 250)
    $beforeBox.Fill.ForeColor.RGB = $C.PaleGray
    $beforeBox.Line.ForeColor.RGB = $C.MidGray
    $beforeBox.Line.Weight = 1.2

    # Fishbone branches are drawn first so the boxes sit cleanly on top.
    Add-Connector $s 90 188 238 275 $C.Steel $true 1.9 | Out-Null
    Add-Connector $s 247 188 238 275 $C.Steel $true 1.9 | Out-Null
    Add-Connector $s 402 188 238 275 $C.Steel $true 1.9 | Out-Null
    Add-Connector $s 90 365 238 275 $C.Steel $true 1.9 | Out-Null
    Add-Connector $s 402 275 238 275 $C.Steel $true 1.9 | Out-Null

    Add-DeptNode $s "Engineering" 34 171 112 34 $C.White $C.MidGray | Out-Null
    Add-DeptNode $s "Manufacturing" 187 171 120 34 $C.White $C.MidGray | Out-Null
    Add-DeptNode $s "Machine shops" 340 171 124 34 $C.White $C.MidGray | Out-Null
    Add-DeptNode $s "Quality / FAI" 34 348 112 34 $C.White $C.MidGray | Out-Null
    Add-DeptNode $s "Service / Sales" 187 348 120 34 $C.White $C.MidGray | Out-Null
    Add-DeptNode $s "Purchasing" 340 348 124 34 $C.White $C.MidGray | Out-Null
    Add-DeptNode $s "Suppliers" 346 258 112 34 $C.White $C.MidGray | Out-Null
    $cadBefore = $s.Shapes.AddShape($msoShapeRoundedRectangle, 156, 248, 164, 54)
    $cadBefore.Fill.ForeColor.RGB = $C.White
    $cadBefore.Line.ForeColor.RGB = $C.Steel
    $cadBefore.Line.Weight = 2.0
    Add-Text $s "CAD / Product" 184 266 108 18 12.5 $C.Ink $true $ppAlignCenter | Out-Null

    Add-Text $s "Example query" 58 418 100 18 10.8 $C.Ink $true | Out-Null
    Add-Text $s "Mounting-hole diameter out of tolerance.`nCan we still use this part?" 58 440 155 32 7.8 $C.Ink $true | Out-Null
    Add-Connector $s 240 438 240 404 $C.Steel $true 1.8 $true | Out-Null
    Add-Connector $s 264 404 264 438 $C.Steel $true 1.8 $true | Out-Null
    Add-Text $s "limited context -> email loop, delayed disposition" 298 426 170 34 8.8 $C.DarkGray $false | Out-Null

    Add-Text $s "After: InspectorPro product-context layer" 520 84 390 28 18 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Text $s "The product travels with context, so agents reason across`ndepartments and organizations." 550 119 330 38 10.5 $C.DarkGray $false $ppAlignCenter | Out-Null
    $afterBox = $s.Shapes.AddShape($msoShapeRoundedRectangle, 505, 154, 410, 250)
    $afterBox.Fill.ForeColor.RGB = $C.PaleBlue
    $afterBox.Line.ForeColor.RGB = $C.Blue
    $afterBox.Line.Weight = 1.9
    Add-Text $s "InspectorPro context environment" 620 168 195 20 10.8 $C.BlueDark $true $ppAlignCenter | Out-Null

    Add-Connector $s 590 205 714 277 $C.Blue $false 2.2 | Out-Null
    Add-Connector $s 720 205 714 277 $C.Blue $false 2.2 | Out-Null
    Add-Connector $s 848 205 714 277 $C.Blue $false 2.2 | Out-Null
    Add-Connector $s 590 365 714 277 $C.Blue $false 2.2 | Out-Null
    Add-Connector $s 720 365 714 277 $C.Blue $false 2.2 | Out-Null
    Add-Connector $s 848 365 714 277 $C.Blue $false 2.2 | Out-Null
    Add-Connector $s 850 277 714 277 $C.Green $false 2.3 | Out-Null

    Add-DeptNode $s "Engineering" 535 188 112 34 $C.White $C.Blue | Out-Null
    Add-DeptNode $s "Manufacturing" 660 188 120 34 $C.White $C.Blue | Out-Null
    Add-DeptNode $s "Machine shops" 792 188 112 34 $C.White $C.Blue | Out-Null
    Add-DeptNode $s "Quality / FAI" 535 348 112 34 $C.White $C.Blue | Out-Null
    Add-DeptNode $s "Service / Sales" 660 348 120 34 $C.White $C.Blue | Out-Null
    Add-DeptNode $s "Purchasing" 792 348 112 34 $C.White $C.Blue | Out-Null
    Add-DeptNode $s "Suppliers" 812 260 112 34 $C.White $C.Green | Out-Null
    $cadAfter = $s.Shapes.AddShape($msoShapeRoundedRectangle, 630, 250, 168, 54)
    $cadAfter.Fill.ForeColor.RGB = $C.White
    $cadAfter.Line.ForeColor.RGB = $C.Blue
    $cadAfter.Line.Weight = 2.2
    Add-Text $s "CAD / Product" 658 268 110 18 12.5 $C.Ink $true $ppAlignCenter | Out-Null

    Add-Text $s "Same query" 535 418 90 18 10.8 $C.BlueDark $true | Out-Null
    Add-Text $s "same mounting-hole question" 535 442 145 18 8.2 $C.Ink $true | Out-Null
    Add-Connector $s 700 438 700 404 $C.Blue $false 2.2 $true | Out-Null
    Add-Connector $s 724 404 724 438 $C.Blue $false 2.2 $true | Out-Null
    Add-Text $s "Agent checks assembly role + dimension function.`naccept, rework, or escalate with evidence" 750 420 165 48 8.4 $C.DarkGray $false | Out-Null
    Add-Footer $s "InspectorPro - discussion deck - June 2026"

    # Slide 2
    $s = $pres.Slides.Add(3, $ppLayoutBlank)
    Add-ViewportBackground $s
    Add-Header $s
    Add-Title $s "The supplier disposition problem" "When FAI finds a deviation, the supplier often has the measurement - but not the product context."

    Add-Card $s "1. Package sent" "CAD, drawing, specs, and purchase requirements are sent to the supplier." 48 178 150 112 $C.Blue
    Add-Card $s "2. Part made" "The shop manufactures the part and completes first article inspection." 225 178 150 112 $C.Teal
    Add-Card $s "3. FAI deviation" "A feature is out of tolerance, such as a mounting-hole diameter." 402 178 150 112 $C.Orange
    Add-Card $s "4. Missing context" "The supplier may not know the assembly role, mating parts, or function of that dimension." 579 178 150 112 $C.Steel
    Add-Card $s "5. Decision stalls" "Work stops for clarification: scrap, rework, accept, or escalate?" 756 178 150 112 $C.Green

    Add-Connector $s 198 234 225 234 $C.Steel $false 1.8 $true | Out-Null
    Add-Connector $s 375 234 402 234 $C.Steel $false 1.8 $true | Out-Null
    Add-Connector $s 552 234 579 234 $C.Steel $false 1.8 $true | Out-Null
    Add-Connector $s 729 234 756 234 $C.Steel $false 1.8 $true | Out-Null

    Add-Text $s "The supplier knows:" 100 332 160 22 13 $C.Ink $true | Out-Null
    Add-Text $s "measured value`ntolerance`ninspection result" 102 360 160 54 11 $C.DarkGray $false | Out-Null

    Add-Text $s "The supplier may not know:" 332 332 210 22 13 $C.Ink $true | Out-Null
    Add-Text $s "what the feature does`nwhat assembly fit it affects`nwhether the deviation matters" 334 360 230 54 11 $C.DarkGray $false | Out-Null

    Add-Card $s "Demo setup" "InspectorPro uses CAD, drawing, FAI, and assembly/function context to answer: keep, rework, scrap, or escalate with evidence." 612 330 260 92 $C.Blue
    Add-Text $s "Core pain: disposition decisions get delayed because product function does not travel with the part." 92 455 780 30 15.5 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Footer $s "This is the workflow the FAI supplier demo is meant to prove."

    # Slide 3
    $s = $pres.Slides.Add(4, $ppLayoutBlank)
    Add-ViewportBackground $s
    Add-Header $s
    Add-Text $s "Product context compounds across the manufacturing lifecycle" 48 82 850 34 24.5 $C.Ink $true | Out-Null
    Add-Text $s "CAD starts the context layer; each department adds and reuses product understanding." 50 120 820 22 12.2 $C.DarkGray $false | Out-Null

    Add-Text $s "CAD / product context backbone" 380 275 200 14 9.3 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Connector $s 78 304 900 304 $C.PaleBlue $false 7.5 $false | Out-Null
    Add-Connector $s 78 304 900 304 $C.BlueDark $false 2.4 $true | Out-Null

    $stopXs = @(135, 285, 435, 585, 735, 865)
    $stopY = 304
    $stopColors = @($C.Blue, $C.Green, $C.Orange, $C.Teal, $C.BlueDark, $C.Steel)

    Add-Connector $s 135 292 135 250 $C.Blue $false 1.1 $false | Out-Null
    Add-Connector $s 285 316 285 360 $C.Green $false 1.1 $false | Out-Null
    Add-Connector $s 435 292 435 260 $C.Orange $false 1.1 $false | Out-Null
    Add-Connector $s 585 316 585 360 $C.Teal $false 1.1 $false | Out-Null
    Add-Connector $s 735 292 735 250 $C.BlueDark $false 1.1 $false | Out-Null
    Add-Connector $s 865 316 865 360 $C.Steel $false 1.1 $false | Out-Null

    Add-FlatCard $s "Engineering" "Checks drawings, features, compare, and DFM.`nValue: cleaner releases; fewer late changes." 44 160 250 90 $C.Blue
    Add-FlatCard $s "Purchasing" "Purchased/custom split, replacement search, cost and lead-time signals.`nValue: faster sourcing; less engineering back-and-forth." 145 360 260 96 $C.Green
    Add-FlatCard $s "Manufacturing" "Process maps, assembly sequence, in-house and supplier capability.`nValue: faster prototypes; less scrap/rework." 325 160 250 100 $C.Orange
    Add-FlatCard $s "Quality / Supplier" "FAI consequence analysis and disposition evidence.`nValue: faster accept/rework/scrap decisions." 435 360 250 86 $C.Teal
    Add-FlatCard $s "Sales / Training" "Role-aware product coaching and two-way onboarding.`nValue: faster product knowledge transfer." 625 160 260 90 $C.BlueDark
    Add-FlatCard $s "Service / Operations" "Service guidance plus facility flow, capacity, and clearance.`nValue: better field support and layout decisions." 695 360 235 96 $C.Steel

    for ($i = 0; $i -lt $stopXs.Count; $i++) {
        $diam = 23
        $circle = $s.Shapes.AddShape($msoShapeOval, ($stopXs[$i] - ($diam / 2)), ($stopY - ($diam / 2)), $diam, $diam)
        $circle.Fill.ForeColor.RGB = $C.White
        $circle.Line.ForeColor.RGB = $stopColors[$i]
        $circle.Line.Weight = 2.0
        Add-Text $s ([string]($i + 1)) ($stopXs[$i] - 7) ($stopY - 7) 14 14 9.6 $C.Ink $true $ppAlignCenter | Out-Null
    }

    Add-Text $s "The value is accumulated product understanding reused across departments - not a collection of disconnected demos." 88 474 784 22 13.2 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Footer $s "InspectorPro compounds CAD context around how the product is made, sourced, inspected, sold, serviced, and improved."

    # Slide 4
    $s = $pres.Slides.Add(5, $ppLayoutBlank)
    Add-ViewportBackground $s
    Add-Header $s
    Add-Text $s "Market reach: CAD-driven manufacturers, multi-seat expansion" 48 82 850 34 23.5 $C.Ink $true | Out-Null
    Add-Text $s "The buyer is not just engineering. The same product context becomes useful across the manufacturing organization." 50 120 820 22 12.2 $C.DarkGray $false | Out-Null

    Add-FlatCard $s "Where InspectorPro fits" "Companies that make physical products from CAD and need product knowledge to move across teams." 54 174 245 92 $C.Blue
    Add-Text $s "Representative markets" 72 302 180 18 11.3 $C.Ink $true | Out-Null
    Add-Text $s "Medical devices`nIndustrial equipment`nAerospace / defense`nAutomotive / mobility`nElectronics / high-tech equipment`nContract manufacturers / machine shops" 74 330 230 98 10.4 $C.DarkGray $false | Out-Null

    $marketCore = $s.Shapes.AddShape($msoShapeRoundedRectangle, 350, 188, 258, 222)
    $marketCore.Fill.ForeColor.RGB = $C.PaleBlue
    $marketCore.Line.ForeColor.RGB = $C.Blue
    $marketCore.Line.Weight = 2.0
    Add-Text $s "One shared product-context layer" 380 212 198 24 15.2 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Text $s "CAD + drawing + BOM + FAI + assembly + supplier evidence" 386 246 186 42 11.2 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Text $s "The same product understanding supports different decisions depending on who is asking." 382 314 194 52 10.7 $C.DarkGray $false $ppAlignCenter | Out-Null

    Add-Connector $s 300 234 350 234 $C.Steel $false 2.0 $true | Out-Null
    Add-Connector $s 608 234 660 234 $C.Steel $false 2.0 $true | Out-Null

    Add-Text $s "Expansion users inside one account" 660 174 250 18 11.3 $C.Ink $true | Out-Null
    $seatItems = @(
        @("Engineering", 660, 208, $C.Blue),
        @("Manufacturing", 800, 208, $C.Orange),
        @("Quality", 660, 250, $C.Teal),
        @("Purchasing", 800, 250, $C.Green),
        @("Suppliers", 660, 292, $C.Steel),
        @("Service", 800, 292, $C.Teal),
        @("Sales / Training", 660, 334, $C.BlueDark),
        @("Operations", 800, 334, $C.Steel)
    )
    foreach ($item in $seatItems) {
        Add-DeptNode $s $item[0] ([double]$item[1]) ([double]$item[2]) 120 30 $C.White $item[3] | Out-Null
    }

    Add-Text $s "Land with one workflow" 143 454 190 22 13.2 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Connector $s 332 465 408 465 $C.Steel $false 1.8 $true | Out-Null
    Add-Text $s "Expand across departments" 410 454 220 22 13.2 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Connector $s 630 465 706 465 $C.Steel $false 1.8 $true | Out-Null
    Add-Text $s "Become a product-context system" 704 454 230 22 13.2 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Footer $s "Market logic: one CAD-driven product account can create many role-specific use cases and seats."

    # Slide 5
    $s = $pres.Slides.Add(6, $ppLayoutBlank)
    Add-ViewportBackground $s
    Add-Header $s
    Add-Text $s "Product data in, role-specific answers out" 48 82 650 48 27 $C.Ink $true | Out-Null
    Add-Text $s "InspectorPro converts product files into shared context for role-aware agents." 50 126 560 26 12.5 $C.DarkGray $false | Out-Null

    Add-Card $s "Product data injection" "CAD model + drawing / PDF`nBOM + specifications`nFAI / inspection evidence`nAssembly context`nFactory capacity" 54 238 190 124 $C.Blue

    Add-Connector $s 250 300 314 300 $C.Steel $false 2.3 $true | Out-Null

    $engine = $s.Shapes.AddShape($msoShapeRoundedRectangle, 316, 206, 232, 170)
    $engine.Fill.ForeColor.RGB = $C.White
    $engine.Line.ForeColor.RGB = $C.Blue
    $engine.Line.Weight = 2.0
    Add-Text $s "InspectorPro" 348 226 168 24 17 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Text $s "Context + reasoning engine" 352 252 160 18 10.5 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Text $s "- feature + dimension mapping`n- product semantics`n- prompting + workflow logic`n- RAG / trusted references`n- fine-tuning path" 342 284 180 82 10.7 $C.DarkGray $false | Out-Null
    Add-Text $s "turns files into product understanding" 344 354 178 16 8.8 $C.Steel $false $ppAlignCenter | Out-Null

    Add-Connector $s 552 300 604 300 $C.Blue $false 2.3 $true | Out-Null

    $agentBox = $s.Shapes.AddShape($msoShapeRoundedRectangle, 604, 190, 86, 252)
    $agentBox.Fill.ForeColor.RGB = $C.PaleBlue
    $agentBox.Line.ForeColor.RGB = $C.Blue
    $agentBox.Line.Weight = 2.0
    Add-Text $s "Role-aware`nAI agents" 615 212 64 40 10.5 $C.BlueDark $true $ppAlignCenter | Out-Null
    Add-Pill $s "Agent 1" 615 278 64 24 $C.Blue
    Add-Pill $s "Agent 2" 615 320 64 24 $C.Teal
    Add-Pill $s "Agent 3" 615 362 64 24 $C.Green
    Add-Text $s "same context`ndifferent answer" 613 410 68 26 8.5 $C.DarkGray $false $ppAlignCenter | Out-Null

    $deptX = 766
    $deptW = 132
    $deptH = 28
    $deptItems = @(
        @("Manufacturing", 204, $C.Orange),
        @("Sales", 238, $C.BlueDark),
        @("Purchasing", 272, $C.Green),
        @("Service", 306, $C.Teal),
        @("Engineering", 340, $C.Blue),
        @("Production", 374, $C.Steel),
        @("Machine shops", 408, $C.Orange)
    )
    foreach ($item in $deptItems) {
        $label = $item[0]
        $y = [double]$item[1]
        $color = $item[2]
        Add-DoubleConnector $s 696 ($y + ($deptH / 2)) ($deptX - 12) ($y + ($deptH / 2)) $color $false 1.7 | Out-Null
        Add-DeptNode $s $label $deptX $y $deptW $deptH $C.White $color | Out-Null
        Add-Connector $s ($deptX + $deptW) ($y + ($deptH / 2)) 928 ($y + ($deptH / 2)) $C.Green $true 1.2 $true | Out-Null
    }

    Add-Connector $s 928 436 928 174 $C.Green $true 1.6 $true | Out-Null
    Add-Connector $s 928 174 508 174 $C.Green $true 1.6 $true | Out-Null
    Add-Text $s "new context from use" 660 156 150 16 9 $C.Green $true $ppAlignCenter | Out-Null
    $reviewGate = $s.Shapes.AddShape($msoShapeRoundedRectangle, 338, 154, 170, 40)
    $reviewGate.Fill.ForeColor.RGB = $C.White
    $reviewGate.Line.ForeColor.RGB = $C.Orange
    $reviewGate.Line.Weight = 1.6
    Add-Text $s "Human review gate" 360 162 126 14 10.2 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Text $s "approved context only" 362 179 122 12 8.3 $C.DarkGray $false $ppAlignCenter | Out-Null
    Add-Connector $s 338 174 154 174 $C.Green $true 1.6 $true | Out-Null
    Add-Connector $s 154 174 154 238 $C.Green $true 1.6 $true | Out-Null

    Add-Connector $s 374 404 374 378 $C.Orange $false 1.6 $true | Out-Null
    Add-Connector $s 432 404 432 378 $C.Orange $false 1.6 $true | Out-Null
    Add-Connector $s 490 404 490 378 $C.Orange $false 1.6 $true | Out-Null
    Add-Text $s "company vision / mission / product strategy" 330 410 210 16 9.5 $C.Orange $true $ppAlignCenter | Out-Null

    Add-Text $s "Questions and answers move both ways. New notes, decisions, and issues flow back through human review before becoming product context." 92 468 775 34 12 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Footer $s "The prototype is not just a viewer; it is a role-aware product-context system."

    # Slide 6
    $s = $pres.Slides.Add(7, $ppLayoutBlank)
    Add-ViewportBackground $s
    Add-Header $s
    Add-Title $s "Pilot proof: shorten real manufacturing decisions" "After the demo, the next step is a narrow pilot that measures whether product context changes decisions."

    Add-Card $s "1. Select real cases" "5-10 parts or assemblies.`nCAD + drawings + BOM + FAI.`nAt least one supplier or internal disposition issue." 58 178 250 118 $C.Blue
    Add-Card $s "2. Run controlled workflows" "Drawing readiness.`nFAI consequence analysis.`nSupplier clarification.`nHuman-reviewed answers only." 355 178 250 118 $C.Teal
    Add-Card $s "3. Measure the delta" "Time to answer.`nEmail clarification loops.`nMissed context found.`nEvidence quality and failure cases." 652 178 250 118 $C.Green

    Add-Connector $s 308 237 355 237 $C.Steel $false 2.0 $true | Out-Null
    Add-Connector $s 605 237 652 237 $C.Steel $false 2.0 $true | Out-Null

    Add-Text $s "What has to be true for the pilot to matter?" 72 342 360 24 15 $C.Ink $true | Out-Null
    Add-Pill $s "Repeatable install" 74 382 145 30 $C.BlueDark
    Add-Pill $s "Trusted evidence" 236 382 138 30 $C.Teal
    Add-Pill $s "Faster disposition" 392 382 150 30 $C.Green
    Add-Pill $s "Lower rework risk" 560 382 142 30 $C.Orange
    Add-Pill $s "Clear next workflow" 720 382 150 30 $C.Steel

    Add-Text $s "Success is not broad deployment. Success is proving that one real workflow gets faster, clearer, and more defensible." 98 452 760 28 15 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Footer $s "A good pilot turns the prototype from an interesting demo into evidence for a customer, partner, or investor conversation."

    # Slide 7
    $s = $pres.Slides.Add(8, $ppLayoutBlank)
    Add-ViewportBackground $s
    Add-Header $s
    Add-Title $s "What I would value from this conversation" "The ask is guidance, introductions, and path clarity - not a forced close."
    Add-Card $s "Market read" "Where does this fit best: product company, pilot-led enterprise sale, startup program, or strategic partnership?" 58 176 260 105 $C.Blue
    Add-Card $s "Pilot introductions" "Who are 1-3 manufacturers where drawing, FAI, supplier handoffs, or revision context create real pain?" 350 176 260 105 $C.Teal
    Add-Card $s "Startup path" "Is CodeLaunch, an Improving relationship, or another Minnesota ecosystem path worth pursuing?" 642 176 260 105 $C.Green
    Add-Card $s "Investor/operator intros" "If the product story is credible, who should see the 12-month pilot-readiness plan?" 203 318 260 105 $C.Orange
    Add-Card $s "Partnership advice" "If technical hardening help makes sense, define it cleanly while preserving core InspectorPro IP." 495 318 260 105 $C.Steel
    Add-Text $s "Question for Steve: What proof would make InspectorPro worth introducing to a manufacturer or investor?" 98 466 760 28 16 $C.Ink $true $ppAlignCenter | Out-Null
    Add-Footer $s "Best outcome: clear next step, warm introductions, or a scoped follow-up conversation."

    try {
        $pres.SaveAs($outPath, $ppSaveAsOpenXMLPresentation)
        $script:savedPath = $outPath
    } catch {
        $fallbackPath = Join-Path (Split-Path $outPath) "InspectorPro_Steve_Banks_Conversation_Deck_layout_review.pptx"
        $pres.SaveAs($fallbackPath, $ppSaveAsOpenXMLPresentation)
        $script:savedPath = $fallbackPath
    }

    for ($i = 1; $i -le $pres.Slides.Count; $i++) {
        $png = Join-Path $renderDir ("slide_{0:D2}.png" -f $i)
        $pres.Slides.Item($i).Export($png, "PNG", 1600, 900) | Out-Null
    }
} catch {
    Write-Host ("PowerPoint generation failed at line {0}: {1}" -f $_.InvocationInfo.ScriptLineNumber, $_.InvocationInfo.Line)
    Write-Host ("Error details: {0}" -f $_.Exception.Message)
    Write-Error $_
    throw
} finally {
    if ($pres -ne $null) {
        try { $pres.Close() | Out-Null } catch { }
    }
    if ($ppt -ne $null) {
        try { $ppt.Quit() | Out-Null } catch { }
    }
}

Write-Host "Created $savedPath"
Write-Host "Rendered previews to $renderDir"

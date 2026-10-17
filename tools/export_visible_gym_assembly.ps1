param([Parameter(Mandatory=$true)][string]$Source, [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$owned = $false
$opened = $false
$sw = $null
$previous = $null
$interop = [Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot '../.runtime/additional-gym-import-20261004/bin/SolidWorks.Interop.sldworks.dll'))
function Call-Sw($object, [string]$interface, [string]$method, [object[]]$values=@()) {
    $type = $interop.GetType('SolidWorks.Interop.sldworks.'+$interface,$true)
    $result = $type.GetMethod($method).Invoke($object,$values)
    return ,$result
}
try {
    try { $sw = [Runtime.InteropServices.Marshal]::GetActiveObject('SldWorks.Application') }
    catch { $sw = New-Object -ComObject SldWorks.Application; $owned = $true }
    Write-Output 'Connected to SolidWorks'
    $active = Call-Sw $sw ISldWorks get_ActiveDoc
    if ($null -ne $active) { $previous = Call-Sw $active IModelDoc2 GetTitle }
    if ($null -ne (Call-Sw $sw ISldWorks GetOpenDocumentByName @($Source))) { throw 'Close the import source before extracting; active documents will not be modified.' }
    $openArgs = [object[]]@($Source,2,3,'',0,0)
    $doc = Call-Sw $sw ISldWorks OpenDoc6 $openArgs
    $errors = $openArgs[4]; $warnings = $openArgs[5]
    Write-Output "Opened assembly: errors=$errors warnings=$warnings"
    if ($null -eq $doc) { throw "Assembly open failed: $errors" }
    $opened = $true
    $resolve = Call-Sw $doc IAssemblyDoc ResolveAllLightWeightComponents @($false)
    Write-Output 'Resolved components'
    $included = [Collections.Generic.List[object]]::new()
    $excluded = [Collections.Generic.List[object]]::new()
    foreach ($component in (Call-Sw $doc IAssemblyDoc GetComponents @($false))) {
        $name = Call-Sw $component IComponent2 get_Name2
        Write-Output "Inspecting $name"
        $hidden = $false
        $parent = $component
        while ($null -ne $parent) {
            if ((Call-Sw $parent IComponent2 IsHidden @($false)) -or (Call-Sw $parent IComponent2 IsSuppressed)) { $hidden = $true; break }
            $parent = Call-Sw $parent IComponent2 GetParent
        }
        if ($hidden) { $excluded.Add(@{name=$name; reason='hidden-or-suppressed-component-or-ancestor'}); continue }
        $model = Call-Sw $component IComponent2 GetModelDoc2
        if ($null -eq $model) { throw "Unresolved visible component: $name" }
        $partPath = Call-Sw $component IComponent2 GetPathName
        if (-not $partPath.ToLowerInvariant().EndsWith('.sldprt')) { continue }
        $meshes = [Collections.Generic.List[object]]::new()
        foreach ($kind in @(0,1)) {
            foreach ($body in (Call-Sw $model IPartDoc GetBodies2 @($kind,$true))) {
                if ($null -eq $body) { continue }
                $face = Call-Sw $body IBody2 GetFirstFace
                $faces = 0
                $triangles = [Collections.Generic.List[double]]::new()
                while ($null -ne $face) {
                    $vertices = Call-Sw $face IFace2 GetTessTriangles @($true)
                    if ($null -eq $vertices -or $vertices.Length -lt 9) { throw "Untessellated visible face: $name" }
                    foreach ($v in $vertices) { $triangles.Add([double]$v) }
                    $faces++
                    $face = Call-Sw $face IFace2 GetNextFace
                }
                $meshes.Add(@{faces=$faces; vertices=$triangles.ToArray(); sheet=($kind -eq 1)})
            }
        }
        if ($meshes.Count -eq 0) { throw "Missing visible geometry: $name" }
        $transform = Call-Sw $component IComponent2 get_Transform2
        $included.Add(@{name=$name; transform=(Call-Sw $transform IMathTransform get_ArrayData); meshes=$meshes.ToArray()})
    }
    if ($included.Count -eq 0 -or $excluded.Count -eq 0) { throw 'Expected visible bag and hidden wall components' }
    @{included=$included.ToArray(); excluded=$excluded.ToArray(); sourceUnits='m'; readOnly=$true;
      visibilityChanged=$false; errors=$errors; warnings=$warnings; resolveResult=$resolve} |
        ConvertTo-Json -Depth 12 -Compress | Set-Content -LiteralPath $Output -Encoding UTF8
} catch {
    Write-Output ($_.Exception.Message + "`n" + $_.ScriptStackTrace)
    throw
} finally {
    try { if ($opened) { $null=Call-Sw $sw ISldWorks CloseDoc @((Call-Sw $doc IModelDoc2 GetTitle)) } } catch { Write-Output "Close: $_" }
    try { if ($null -ne $previous) { $null=Call-Sw $sw ISldWorks ActivateDoc3 @($previous,$false,0,0) } } catch { Write-Output "Restore: $_" }
    try { if ($owned -and $null -ne $sw) { $null=Call-Sw $sw ISldWorks ExitApp } } catch { Write-Output "Exit: $_" }
}

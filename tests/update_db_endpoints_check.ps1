# Offline tests: intercept all network and deployment commands.
$ErrorActionPreference = 'Stop'
$global:DbUrlTestCase = ''
$global:DbUrlTestCalls = @()
$global:DbUrlTestReads = 0
function gcloud.cmd {
    $global:DbUrlTestCalls += ,@($args)
    $global:LASTEXITCODE = 0
    if ($args[1] -eq 'revisions') {
        $member = if ($global:DbUrlTestCase -eq 'wrong-revision') { 'https://old.trycloudflare.com' } else { 'https://member.trycloudflare.com' }
        return (@{spec=@{containers=@(@{env=@(
            @{name='MEMBER_DATABASE_URL';value=$member},
            @{name='PRODUCT_DATABASE_URL';value='https://product.trycloudflare.com'}
        )})}} | ConvertTo-Json -Depth 8)
    }
    if ($args[2] -eq 'update') { return '{}' }
    $global:DbUrlTestReads++
    $rev = if ($global:DbUrlTestReads -eq 1) {'old'} else {'new'}
    return (@{status=@{latestReadyRevisionName=$rev;latestCreatedRevisionName=$rev;traffic=@(@{revisionName=$rev;percent=100})}} | ConvertTo-Json -Depth 5)
}
function Invoke-WebRequest {
    param($Uri,$TimeoutSec,$MaximumRedirection,[switch]$UseBasicParsing)
    if ($global:DbUrlTestCase -eq 'dead') { throw 'DNS failed' }
    if ($global:DbUrlTestCase -eq 'single-port' -and $Uri -like '*/api/products*') { throw '404 products not available' }
    if ($global:DbUrlTestCase -eq 'member401' -and $Uri -like '*/member-database/health') { throw '401' }
    $body = if ($Uri -like '*/api/products*') { '{"products":[]}' }
        elseif ($Uri -like '*product*') { '{"service":"product-db"}' }
        else { '{"service":"member-database"}' }
    return @{StatusCode=200;Headers=@{'Content-Type'='application/json'};Content=$body}
}
$target = Join-Path $PSScriptRoot '../update-db-url.ps1'
$passed = 0
foreach ($name in @('dry','invalid','dead','single-port','success','wrong-revision','member401')) {
    $global:DbUrlTestCase=$name; $global:DbUrlTestCalls=@(); $global:DbUrlTestReads=0; $failed=$false
    $options = @{NewUrl='https://member.trycloudflare.com';ProductUrl='https://product.trycloudflare.com'}
    if ($name -eq 'dry') { $options.DryRun=$true }
    if ($name -eq 'invalid') { $options.NewUrl='https://user:password@example.com/path' }
    if ($name -eq 'single-port') { $options.Remove('ProductUrl') }
    try { & $target @options } catch { $failed=$true }
    $updates = @($global:DbUrlTestCalls | Where-Object { $_[2] -eq 'update' })
    $expectedFailure = $name -notin @('dry','success')
    if ($failed -ne $expectedFailure) { throw "FAIL $name result" }
    if ($name -in @('dry','invalid','dead','single-port') -and $global:DbUrlTestCalls.Count -ne 0) { throw "FAIL $name mutated" }
    if ($name -in @('success','wrong-revision','member401')) {
        if ($updates.Count -ne 1) { throw "FAIL $name update count" }
        $expected='--update-env-vars=MEMBER_DATABASE_URL=https://member.trycloudflare.com,PRODUCT_DATABASE_URL=https://product.trycloudflare.com'
        if ($updates[0] -notcontains $expected) { throw "FAIL $name simultaneous update" }
    }
    $passed++; Write-Host "PASS $name"
}
Write-Host "$passed/7 passed (offline; no deployment)"

[CmdletBinding()]
param(
    [string]$ResourceGroupName = 'rg-reserving-dev',
    [string]$AppName
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Install Azure CLI and sign in with az login before deploying.'
}

if (-not $AppName) {
    $appNames = @(az webapp list --resource-group $ResourceGroupName --query '[].name' --output tsv --only-show-errors)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list apps in '$ResourceGroupName'. Check your sign-in, subscription and resource group."
    }
    if ($appNames.Count -ne 1) {
        throw "Expected one web app in '$ResourceGroupName'; found $($appNames.Count). Deploy infrastructure first, or specify -AppName."
    }
    $AppName = $appNames[0].Trim()
}

$hostname = az webapp show --resource-group $ResourceGroupName --name $AppName --query defaultHostName --output tsv --only-show-errors
if ($LASTEXITCODE -ne 0 -or -not $hostname) {
    throw "Could not find web app '$AppName' in '$ResourceGroupName'."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$artifactDirectory = Join-Path $projectRoot '.artifacts'
$zipPath = Join-Path $artifactDirectory 'reserving-api.zip'
$sourceFiles = @(
    (Join-Path $projectRoot 'main.py'),
    (Join-Path $projectRoot 'requirements.txt')
)

# Include only application source at the ZIP root; Azure installs Linux dependencies.
New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
Compress-Archive -LiteralPath $sourceFiles -DestinationPath $zipPath -Force

Write-Host "Deploying FastAPI to '$AppName' in '$ResourceGroupName'..."

# Startup and dependency build settings are managed by the Bicep deployment.
# Submit asynchronously to avoid the Kudu HTTP timeout during remote builds.
# Azure CLI still polls the asynchronous build and returns its final Kudu status.
Write-Host "Submitting asynchronous deployment for '$AppName' in '$ResourceGroupName'..."
$deploymentJson = az webapp deploy --resource-group $ResourceGroupName --name $AppName --src-path $zipPath --type zip --async true --track-status false --timeout 900000 --output json --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw "API deployment failed. Inspect deployment logs for '$AppName' in Azure App Service."
}

try {
    $deployment = ($deploymentJson -join [Environment]::NewLine) | ConvertFrom-Json
}
catch {
    throw 'Azure CLI returned invalid deployment JSON. Check deployment logs before retrying.'
}
if ($deployment -is [array] -or $deployment -isnot [pscustomobject] -or [string]::IsNullOrWhiteSpace([string]$deployment.id)) {
    throw 'Azure CLI did not return a deployment ID. Check deployment logs before retrying.'
}
if ($deployment.status -ne 4) {
    throw "Deployment '$($deployment.id)' has not succeeded (status '$($deployment.status)'). Check deployment logs before retrying."
}

Write-Host "API deployed: https://$hostname"
Write-Host "Postman GET:  https://$hostname/hello?name=Jane"
Write-Host "Health check: https://$hostname/health"
Write-Host "API docs:     https://$hostname/docs"

using '../main.bicep'

param appName = 'reserving'
param environmentName = 'prod'

// Initial settings; choose production capacity when deployment requirements are known.
param appServiceSkuName = 'B1'
param appServicePythonVersion = '3.12'

// Add production-specific app settings as the API grows.
// Omit location to use the target resource group's location.

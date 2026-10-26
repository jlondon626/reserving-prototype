using '../main.bicep'

param appName = 'reserving'
param environmentName = 'dev'

param appServiceSkuName = 'B1'
param appServicePythonVersion = '3.12'

// Add development-specific app settings as the API grows.
// Omit location to use the target resource group's location.

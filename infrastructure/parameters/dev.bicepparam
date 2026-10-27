using '../main.bicep'

param appName = 'reserving'
param environmentName = 'dev'

param appServiceSkuName = 'B1'
param appServicePythonVersion = '3.12'

// Initial administrator: the tenant-local object ID of the signed-in Azure user.
// These identify an Entra principal; they are not SQL credentials or passwords.
param sqlEnabled = true
param sqlAdministratorLogin = 'Jack London'
param sqlAdministratorObjectId = '836d6760-d102-44fc-8f06-cda12875ae7f'
param sqlAdministratorPrincipalType = 'User'

// Add development-specific app settings as the API grows.
// Omit location to use the target resource group's location.

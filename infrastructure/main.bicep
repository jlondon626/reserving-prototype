targetScope = 'resourceGroup'

@description('Application name used as the basis for resource names and tags.')
param appName string = 'reserving'

@description('Environment name, for example dev or prod.')
param environmentName string

@description('Azure region for resources. Defaults to the target resource group location.')
param location string = resourceGroup().location

@description('Additional resource tags. Application and environment tags are set centrally.')
param tags object = {}

@description('Dedicated Linux App Service SKU, Basic or higher, supporting Always On.')
param appServiceSkuName string = 'B1'

@description('Python minor version available in App Service.')
param appServicePythonVersion string = '3.12'

@description('Application startup command for the FastAPI entry point.')
param appServiceStartupCommand string = 'python -m uvicorn main:app --host 0.0.0.0 --port 8000'

@description('Build Python source and install dependencies during deployment.')
param appServiceBuildDuringDeployment bool = true

@description('Additional web app settings. Use Key Vault references for credentials and keep secret values out of parameter files.')
@secure()
param appServiceAppSettings object = {}

@description('Provision the development Azure SQL free-offer server and database. Configure an Entra administrator when enabled.')
param sqlEnabled bool = false

@description('Display name of the Microsoft Entra SQL administrator. Required when SQL is enabled.')
param sqlAdministratorLogin string = ''

@description('Tenant-local object ID of the Microsoft Entra SQL administrator. Required when SQL is enabled; this is not a client/application ID.')
param sqlAdministratorObjectId string = ''

@description('Type of the Microsoft Entra SQL administrator.')
@allowed([
  'User'
  'Group'
])
param sqlAdministratorPrincipalType string = 'User'

@description('Name of the application SQL database within the logical server.')
param sqlDatabaseName string = '${appName}-${environmentName}'

// Each service module will adapt this prefix to its resource naming requirements.
var namePrefix = '${appName}-${environmentName}'
var commonTags = union(tags, {
  application: appName
  environment: environmentName
})

// Implement the remaining modules' resources and inputs before uncommenting their calls.
// Pass module outputs into other modules' inputs when they depend on each other.

// module monitoring './modules/monitoring.bicep' = {
//   name: '${deployment().name}-monitoring'
//   params: {
//     namePrefix: namePrefix
//     location: location
//     tags: commonTags
//   }
// }

module appService './modules/app-service.bicep' = {
  name: '${deployment().name}-app-service'
  params: {
    namePrefix: namePrefix
    location: location
    tags: commonTags
    skuName: appServiceSkuName
    pythonVersion: appServicePythonVersion
    startupCommand: appServiceStartupCommand
    buildDuringDeployment: appServiceBuildDuringDeployment
    additionalAppSettings: appServiceAppSettings
  }
}

module sql './modules/sql.bicep' = if (sqlEnabled) {
  name: '${deployment().name}-sql'
  params: {
    namePrefix: namePrefix
    location: location
    tags: commonTags
    administratorLogin: sqlAdministratorLogin
    administratorObjectId: sqlAdministratorObjectId
    administratorPrincipalType: sqlAdministratorPrincipalType
    databaseName: sqlDatabaseName
  }
}

// module cosmosDb './modules/cosmos-db.bicep' = {
//   name: '${deployment().name}-cosmos-db'
//   params: {
//     namePrefix: namePrefix
//     location: location
//     tags: commonTags
//   }
// }

// module apiManagement './modules/api-management.bicep' = {
//   name: '${deployment().name}-api-management'
//   params: {
//     namePrefix: namePrefix
//     location: location
//     tags: commonTags
//   }
// }

@description('Shared naming, location and tags used for resource deployment.')
output deploymentContext object = {
  namePrefix: namePrefix
  location: location
  tags: commonTags
}

@description('HTTPS URL of the web app.')
output appServiceUrl string = appService.outputs.appUrl

@description('Name of the web app for application code deployment.')
output appServiceName string = appService.outputs.appName

@description('Resource ID of the web app.')
output appServiceResourceId string = appService.outputs.appResourceId

@description('Managed identity principal ID for downstream access grants.')
output appServicePrincipalId string = appService.outputs.principalId

@description('Logical SQL server name, or empty when SQL is disabled.')
output sqlServerName string = sqlEnabled ? sql!.outputs.serverName : ''

@description('Logical SQL server resource ID, or empty when SQL is disabled.')
output sqlServerResourceId string = sqlEnabled ? sql!.outputs.serverResourceId : ''

@description('SQL server hostname without credentials, or empty when SQL is disabled.')
output sqlServerFqdn string = sqlEnabled ? sql!.outputs.serverFqdn : ''

@description('Application SQL database name, or empty when SQL is disabled.')
output sqlDatabaseName string = sqlEnabled ? sql!.outputs.databaseName : ''

@description('Application SQL database resource ID, or empty when SQL is disabled.')
output sqlDatabaseResourceId string = sqlEnabled ? sql!.outputs.databaseResourceId : ''

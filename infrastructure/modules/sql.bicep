targetScope = 'resourceGroup'

@description('Shared resource name prefix. Leaves room for the SQL server suffix and deterministic unique string.')
@minLength(1)
@maxLength(45)
param namePrefix string

@description('Azure region for the logical server and database.')
param location string = resourceGroup().location

@description('Tags applied to the logical server and database.')
param tags object = {}

@description('Display name of the Microsoft Entra user or group administering SQL.')
@minLength(1)
param administratorLogin string

@description('Microsoft Entra object ID of the SQL administrator. This is not the application/client ID.')
@minLength(36)
@maxLength(36)
param administratorObjectId string

@description('Type of Microsoft Entra principal administering SQL.')
@allowed([
  'User'
  'Group'
])
param administratorPrincipalType string = 'User'

@description('Name of the application database within the logical SQL server.')
@minLength(1)
@maxLength(128)
param databaseName string = 'reserving'

var sqlServerName = '${toLower(namePrefix)}-sql-${uniqueString(resourceGroup().id, namePrefix)}'

resource server 'Microsoft.Sql/servers@2025-01-01' = {
  name: sqlServerName
  location: location
  tags: tags
  properties: {
    version: '12.0'
    minimalTlsVersion: '1.2'
    // Step 1 provisions resources only. Network access is configured separately.
    publicNetworkAccess: 'Disabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true
      login: administratorLogin
      sid: administratorObjectId
      principalType: administratorPrincipalType
      tenantId: tenant().tenantId
    }
  }
}

resource database 'Microsoft.Sql/servers/databases@2025-01-01' = {
  parent: server
  name: databaseName
  location: location
  tags: tags
  sku: {
    name: 'GP_S_Gen5'
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: 2
  }
  properties: {
    maxSizeBytes: 34359738368 // 32 GiB, within the free tier's storage limit.
    useFreeLimit: true
    // Pause at the monthly allowance instead of enabling billed overage.
    freeLimitExhaustionBehavior: 'AutoPause'
    requestedBackupStorageRedundancy: 'Local'
    zoneRedundant: false
    readScale: 'Disabled'
    // The free tier determines minimum capacity and its idle auto-pause delay.
  }
}

resource shortTermRetention 'Microsoft.Sql/servers/databases/backupShortTermRetentionPolicies@2025-01-01' = {
  parent: database
  name: 'default'
  properties: {
    retentionDays: 7
  }
}

@description('Name of the SQL logical server.')
output serverName string = server.name

@description('Resource ID of the SQL logical server.')
output serverResourceId string = server.id

@description('Fully qualified SQL server hostname for future database connections.')
output serverFqdn string = server.properties.fullyQualifiedDomainName

@description('Name of the application database.')
output databaseName string = database.name

@description('Resource ID of the application database.')
output databaseResourceId string = database.id

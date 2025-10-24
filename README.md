# Azure Resource Graph MCP Server

A Model Context Protocol (MCP) server that provides AI assistants with powerful capabilities to query and analyze Azure resources using the Azure Resource Graph REST API.

## Overview

This MCP server enables LLMs to:
- Execute KQL (Kusto Query Language) queries against Azure resources
- Search for resources with simplified filters
- Query resource history and track changes over time
- Explore Azure infrastructure across subscriptions and management groups
- Analyze resource configurations, locations, and tags

## Features

### 🔍 **Core Tools**

1. **`azure_resource_graph_query`** - Execute custom KQL queries
   - Full KQL support for complex resource analysis
   - Cross-subscription and management group queries
   - Facet support for additional statistics
   - Pagination for large result sets

2. **`azure_resource_graph_search_resources`** - Simplified resource search
   - Filter by resource type, location, resource group
   - Name pattern matching and tag filtering
   - No KQL knowledge required

3. **`azure_resource_graph_history`** - Resource change tracking
   - Historical snapshots of resource configurations
   - Track modifications over time
   - Compliance and audit capabilities

4. **`azure_resource_graph_operations`** - List available operations
   - Discover Azure Resource Graph API capabilities
   - Operation descriptions and metadata

### 📊 **Response Formats**
- **Markdown**: Human-readable formatted output
- **JSON**: Machine-readable structured data

### 🔧 **Advanced Features**
- Proper pagination with continuation tokens
- Character limit handling (25,000 chars) with truncation
- Comprehensive error handling with actionable guidance
- Azure AD authentication support (CLI and Service Principal)
- Query validation and optimization suggestions

## Installation

### Prerequisites

- Python 3.8 or higher
- Azure CLI (for authentication) OR Azure Service Principal credentials
- Access to Azure subscriptions with appropriate permissions

### Setup

1. **Clone or download the MCP server files:**
   ```bash
   # Download the server files
   curl -O https://example.com/azure_resource_graph_mcp.py
   curl -O https://example.com/requirements.txt
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure authentication (choose one method):**

   **Option A: Azure CLI (Recommended for development)**
   ```bash
   az login
   ```

   **Option B: Service Principal (Recommended for production)**
   ```bash
   export AZURE_CLIENT_ID="your-client-id"
   export AZURE_CLIENT_SECRET="your-client-secret" 
   export AZURE_TENANT_ID="your-tenant-id"
   ```

4. **Test the server:**
   ```bash
   python azure_resource_graph_mcp.py --help
   ```

## Authentication

### Azure CLI Authentication

The easiest method for development and testing:

```bash
# Login to Azure
az login

# Verify access
az account show

# List accessible subscriptions
az account list --output table
```

### Service Principal Authentication

For production deployments, use environment variables:

```bash
# Set environment variables
export AZURE_CLIENT_ID="12345678-1234-1234-1234-123456789abc"
export AZURE_CLIENT_SECRET="your-secret-value"
export AZURE_TENANT_ID="87654321-4321-4321-4321-cba987654321"
```

### Required Azure Permissions

The authentication principal needs these permissions:
- **Reader** role on subscriptions/management groups to query
- **Microsoft.ResourceGraph/resources/read** permission
- **Microsoft.ResourceGraph/operations/read** permission
- For history queries: access to preview features

## Usage Examples

### Basic Resource Queries

**List all virtual machines:**
```
Tool: azure_resource_graph_query
Query: Resources | where type =~ 'Microsoft.Compute/virtualMachines' | project name, location, resourceGroup | limit 10
```

**Count resources by type:**
```
Tool: azure_resource_graph_query  
Query: Resources | summarize count() by type | order by count_ desc
```

**Find resources by tag:**
```
Tool: azure_resource_graph_query
Query: Resources | where tags['environment'] =~ 'production' | project name, type, location
```

### Simplified Resource Search

**Find all storage accounts:**
```
Tool: azure_resource_graph_search_resources
resource_type: Microsoft.Storage/storageAccounts
include_properties: true
```

**Find production resources in East US:**
```
Tool: azure_resource_graph_search_resources
location: eastus
tag_filter: environment=production
limit: 50
```

### Resource History Tracking

**Track VM changes:**
```
Tool: azure_resource_graph_history
Query: Resources | where type =~ 'Microsoft.Compute/virtualMachines' | where name == 'my-vm'
interval: PT24H
```

### Advanced KQL Examples

**Complex analysis with facets:**
```
Tool: azure_resource_graph_query
Query: Resources | where type =~ 'Microsoft.Compute/virtualMachines' | project name, location, resourceGroup, properties.storageProfile.osDisk.osType
Facets: [
  {
    "expression": "location",
    "options": {"$top": 5, "sortOrder": "desc"}
  },
  {
    "expression": "properties.storageProfile.osDisk.osType", 
    "options": {"$top": 3}
  }
]
```

## Integration with Claude Desktop

Add this configuration to your Claude Desktop config file:

### macOS/Linux: `~/.config/claude-desktop/config.json`
### Windows: `%APPDATA%\Claude\config.json`

```json
{
  "mcpServers": {
    "azure-resource-graph": {
      "command": "python",
      "args": ["/path/to/azure_resource_graph_mcp.py"],
      "env": {
        "AZURE_CLIENT_ID": "your-client-id",
        "AZURE_CLIENT_SECRET": "your-client-secret",
        "AZURE_TENANT_ID": "your-tenant-id"
      }
    }
  }
}
```

## Query Language Reference

This server uses KQL (Kusto Query Language) - the same query language used in Azure Monitor, Log Analytics, and Azure Data Explorer.

### Common KQL Operators

- **`where`** - Filter rows: `where type =~ 'Microsoft.Compute/virtualMachines'`
- **`project`** - Select columns: `project name, location, resourceGroup`
- **`summarize`** - Aggregate data: `summarize count() by location`
- **`order`** - Sort results: `order by name asc`
- **`limit`** - Limit results: `limit 100`
- **`extend`** - Add calculated columns: `extend size = properties.hardwareProfile.vmSize`

### Useful Resource Properties

- **`id`** - Full resource ID
- **`name`** - Resource name
- **`type`** - Resource type (e.g., 'Microsoft.Compute/virtualMachines')
- **`location`** - Azure region
- **`resourceGroup`** - Resource group name
- **`subscriptionId`** - Subscription GUID
- **`tags`** - Resource tags (dictionary)
- **`properties`** - Resource-specific properties

### Example Queries

```kql
// Find all resources in a specific resource group
Resources | where resourceGroup =~ 'my-rg'

// Count resources by location
Resources | summarize count() by location | order by count_ desc

// Find unused storage accounts (no tags)
Resources 
| where type =~ 'Microsoft.Storage/storageAccounts'
| where isnull(tags) or array_length(bag_keys(tags)) == 0

// Complex VM analysis
Resources
| where type =~ 'Microsoft.Compute/virtualMachines'
| extend vmSize = properties.hardwareProfile.vmSize
| extend osType = properties.storageProfile.osDisk.osType
| project name, location, resourceGroup, vmSize, osType
| summarize count() by vmSize, osType
```

## Error Handling

The server provides comprehensive error handling with actionable guidance:

### Common Issues and Solutions

**Authentication Errors:**
- Ensure `az login` is completed
- Verify environment variables are set correctly
- Check Azure permissions

**Query Errors:**
- Validate KQL syntax
- Check resource type names (case-sensitive)
- Verify property paths in queries

**Permission Errors:**
- Ensure Reader access on subscriptions
- Verify Resource Graph permissions
- Check management group access

**Timeout Errors:**
- Reduce query scope
- Add filters to limit results
- Use pagination for large datasets

## Troubleshooting

### Debug Mode

Enable debug logging:
```bash
export PYTHONPATH="."
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from azure_resource_graph_mcp import mcp
"
```

### Test Authentication

```bash
# Test Azure CLI auth
az account get-access-token --resource https://management.azure.com/

# Test service principal auth
curl -X POST https://login.microsoftonline.com/$AZURE_TENANT_ID/oauth2/v2.0/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=$AZURE_CLIENT_ID&client_secret=$AZURE_CLIENT_SECRET&scope=https://management.azure.com/.default"
```

### Verify Permissions

```bash
# List accessible subscriptions
az account list --query "[].{Name:name, SubscriptionId:id, State:state}" --output table

# Test Resource Graph access
az graph query -q "Resources | limit 1"
```

## Performance Optimization

### Query Optimization Tips

1. **Use specific filters early:**
   ```kql
   Resources | where type =~ 'Microsoft.Compute/virtualMachines' | where location =~ 'eastus'
   ```

2. **Project only needed columns:**
   ```kql
   Resources | project name, location, type
   ```

3. **Use limits appropriately:**
   ```kql
   Resources | limit 100
   ```

4. **Leverage pagination:**
   ```json
   {
     "options": {
       "$top": 100,
       "$skip": 0
     }
   }
   ```

### Response Size Management

- Character limit: 25,000 characters
- Automatic truncation with guidance
- JSON format for complete data
- Pagination support for large datasets

## API Reference

### Tool: azure_resource_graph_query

Execute custom KQL queries against Azure Resource Graph.

**Parameters:**
- `query` (required): KQL query string
- `subscriptions` (optional): List of subscription IDs
- `management_groups` (optional): List of management group names
- `facets` (optional): Additional statistics requests
- `options` (optional): Pagination and formatting options
- `response_format` (optional): 'markdown' or 'json'

**Example:**
```json
{
  "query": "Resources | where type =~ 'Microsoft.Compute/virtualMachines' | limit 5",
  "subscriptions": ["sub1-guid", "sub2-guid"],
  "response_format": "markdown"
}
```

### Tool: azure_resource_graph_search_resources

Simplified resource search without KQL knowledge.

**Parameters:**
- `resource_type` (optional): Filter by resource type
- `location` (optional): Filter by Azure region
- `resource_group` (optional): Filter by resource group
- `name_filter` (optional): Filter by name pattern
- `tag_filter` (optional): Filter by tags
- `subscriptions` (optional): List of subscription IDs
- `limit` (optional): Maximum results (1-1000)
- `include_properties` (optional): Include detailed properties
- `response_format` (optional): 'markdown' or 'json'

**Example:**
```json
{
  "resource_type": "Microsoft.Storage/storageAccounts",
  "location": "eastus",
  "tag_filter": "environment=production",
  "limit": 50
}
```

### Tool: azure_resource_graph_history

Query resource history and changes over time.

**Parameters:**
- `query` (required): KQL query for history
- `subscriptions` (optional): List of subscription IDs
- `management_groups` (optional): List of management group names
- `interval` (optional): Time interval (ISO 8601)
- `options` (optional): Query options
- `response_format` (optional): 'markdown' or 'json'

### Tool: azure_resource_graph_operations

List available Azure Resource Graph operations.

**Parameters:**
- `response_format` (optional): 'markdown' or 'json'

## Contributing

Contributions are welcome! Please ensure:

1. Follow the MCP best practices outlined in the code
2. Add comprehensive tests for new features
3. Update documentation for any API changes
4. Maintain backward compatibility

## License

This project is licensed under the MIT License.

## Support

For issues and questions:

1. Check the troubleshooting section
2. Verify Azure authentication and permissions
3. Review the Azure Resource Graph documentation
4. File an issue with detailed error information

## Resources

- [Azure Resource Graph Documentation](https://docs.microsoft.com/en-us/azure/governance/resource-graph/)
- [KQL Reference](https://docs.microsoft.com/en-us/azure/data-explorer/kusto/query/)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Azure CLI Documentation](https://docs.microsoft.com/en-us/cli/azure/)

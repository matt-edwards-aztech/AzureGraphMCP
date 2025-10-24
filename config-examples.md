# Azure Resource Graph MCP Server Configuration Examples

## Claude Desktop Configuration

### macOS/Linux Configuration
File: `~/.config/claude-desktop/config.json`

```json
{
  "mcpServers": {
    "azure-resource-graph": {
      "command": "python",
      "args": ["/absolute/path/to/azure_resource_graph_mcp.py"],
      "env": {
        "AZURE_CLIENT_ID": "your-service-principal-client-id",
        "AZURE_CLIENT_SECRET": "your-service-principal-secret",
        "AZURE_TENANT_ID": "your-azure-tenant-id"
      }
    }
  }
}
```

### Windows Configuration  
File: `%APPDATA%\Claude\config.json`

```json
{
  "mcpServers": {
    "azure-resource-graph": {
      "command": "python",
      "args": ["C:\\path\\to\\azure_resource_graph_mcp.py"],
      "env": {
        "AZURE_CLIENT_ID": "your-service-principal-client-id",
        "AZURE_CLIENT_SECRET": "your-service-principal-secret", 
        "AZURE_TENANT_ID": "your-azure-tenant-id"
      }
    }
  }
}
```

### Using Azure CLI Authentication (Simpler for Development)
```json
{
  "mcpServers": {
    "azure-resource-graph": {
      "command": "python",
      "args": ["/path/to/azure_resource_graph_mcp.py"]
    }
  }
}
```

## Environment Variables Setup

### Option 1: Service Principal (Recommended for Production)
```bash
# Set these environment variables
export AZURE_CLIENT_ID="12345678-1234-1234-1234-123456789abc"
export AZURE_CLIENT_SECRET="your-secret-value-here"
export AZURE_TENANT_ID="87654321-4321-4321-4321-cba987654321"

# Test the configuration
python azure_resource_graph_mcp.py
```

### Option 2: Azure CLI (Recommended for Development)
```bash
# Login to Azure CLI
az login

# Verify login
az account show

# Run the MCP server (will use CLI credentials)
python azure_resource_graph_mcp.py
```

## Other MCP Client Configurations

### Continue (VS Code Extension)
File: `.continue/config.json`

```json
{
  "models": [
    {
      "title": "Claude with Azure Resources",
      "provider": "anthropic",
      "model": "claude-3-5-sonnet-20241022",
      "contextLength": 200000,
      "mcpServers": [
        {
          "name": "azure-resource-graph",
          "command": "python",
          "args": ["/path/to/azure_resource_graph_mcp.py"],
          "env": {
            "AZURE_CLIENT_ID": "your-client-id",
            "AZURE_CLIENT_SECRET": "your-client-secret",
            "AZURE_TENANT_ID": "your-tenant-id"
          }
        }
      ]
    }
  ]
}
```

### MCP Inspector (for Testing)
```bash
# Install MCP Inspector
npm install -g @modelcontextprotocol/inspector

# Run with your server
npx @modelcontextprotocol/inspector python /path/to/azure_resource_graph_mcp.py
```

## Production Deployment Configuration

### Docker Container Setup
File: `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy server code
COPY azure_resource_graph_mcp.py .

# Set environment variables (override at runtime)
ENV AZURE_CLIENT_ID=""
ENV AZURE_CLIENT_SECRET=""
ENV AZURE_TENANT_ID=""

# Run the server
CMD ["python", "azure_resource_graph_mcp.py"]
```

### Docker Compose Setup
File: `docker-compose.yml`

```yaml
version: '3.8'
services:
  azure-resource-graph-mcp:
    build: .
    environment:
      - AZURE_CLIENT_ID=${AZURE_CLIENT_ID}
      - AZURE_CLIENT_SECRET=${AZURE_CLIENT_SECRET}
      - AZURE_TENANT_ID=${AZURE_TENANT_ID}
    ports:
      - "8000:8000"
    command: python azure_resource_graph_mcp.py --transport http --port 8000
```

### Kubernetes Deployment
File: `deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: azure-resource-graph-mcp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: azure-resource-graph-mcp
  template:
    metadata:
      labels:
        app: azure-resource-graph-mcp
    spec:
      containers:
      - name: mcp-server
        image: azure-resource-graph-mcp:latest
        ports:
        - containerPort: 8000
        env:
        - name: AZURE_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: azure-credentials
              key: client-id
        - name: AZURE_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: azure-credentials
              key: client-secret
        - name: AZURE_TENANT_ID
          valueFrom:
            secretKeyRef:
              name: azure-credentials
              key: tenant-id
        command: ["python", "azure_resource_graph_mcp.py", "--transport", "http", "--port", "8000"]
---
apiVersion: v1
kind: Secret
metadata:
  name: azure-credentials
type: Opaque
stringData:
  client-id: "your-client-id"
  client-secret: "your-client-secret"
  tenant-id: "your-tenant-id"
---
apiVersion: v1
kind: Service
metadata:
  name: azure-resource-graph-mcp-service
spec:
  selector:
    app: azure-resource-graph-mcp
  ports:
    - protocol: TCP
      port: 8000
      targetPort: 8000
  type: LoadBalancer
```

## Azure Service Principal Setup

### Creating a Service Principal

```bash
# Create a service principal with Reader role
az ad sp create-for-rbac --name "azure-resource-graph-mcp" --role "Reader" --scopes "/subscriptions/YOUR_SUBSCRIPTION_ID"

# Output will be:
# {
#   "appId": "12345678-1234-1234-1234-123456789abc",      # Use as AZURE_CLIENT_ID
#   "displayName": "azure-resource-graph-mcp",
#   "password": "your-generated-secret",                   # Use as AZURE_CLIENT_SECRET
#   "tenant": "87654321-4321-4321-4321-cba987654321"     # Use as AZURE_TENANT_ID
# }
```

### Granting Resource Graph Permissions

```bash
# Grant Resource Graph Reader role at subscription level
az role assignment create \
  --assignee "12345678-1234-1234-1234-123456789abc" \
  --role "Reader" \
  --scope "/subscriptions/YOUR_SUBSCRIPTION_ID"

# For management group access (optional)
az role assignment create \
  --assignee "12345678-1234-1234-1234-123456789abc" \
  --role "Reader" \
  --scope "/providers/Microsoft.Management/managementGroups/YOUR_MG_ID"
```

## Security Best Practices

### Environment Variables
- Never commit credentials to version control
- Use `.env` files for local development (add to `.gitignore`)
- Use secure secret management in production

### Azure Permissions
- Follow principle of least privilege
- Use managed identities when possible
- Regularly rotate service principal secrets
- Monitor access logs

### Network Security
- Use HTTPS in production deployments
- Implement proper authentication for HTTP transport
- Consider VPN or private endpoints for sensitive environments

## Troubleshooting Configuration

### Test Authentication
```bash
# Test service principal authentication
curl -X POST "https://login.microsoftonline.com/$AZURE_TENANT_ID/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=$AZURE_CLIENT_ID&client_secret=$AZURE_CLIENT_SECRET&scope=https://management.azure.com/.default"

# Test Azure CLI authentication
az account get-access-token --resource https://management.azure.com/
```

### Verify MCP Server
```bash
# Test server startup
timeout 5s python azure_resource_graph_mcp.py

# Test with MCP Inspector
npx @modelcontextprotocol/inspector python azure_resource_graph_mcp.py
```

### Common Issues

1. **Authentication Failed**
   - Check environment variables are set correctly
   - Verify service principal credentials
   - Ensure `az login` is completed for CLI auth

2. **Permission Denied**
   - Verify Reader role assignment
   - Check subscription access
   - Confirm Resource Graph permissions

3. **Server Won't Start**
   - Check Python dependencies are installed
   - Verify file paths in configuration
   - Check for syntax errors in server code

4. **No Tools Available**
   - Verify MCP client can connect to server
   - Check stdout/stderr for error messages
   - Ensure proper transport configuration

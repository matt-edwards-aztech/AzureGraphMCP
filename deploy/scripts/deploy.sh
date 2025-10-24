#!/bin/bash

# Azure Resource Graph MCP Server Deployment Script
# This script deploys the Azure Resource Graph MCP Server to Azure App Service

set -e

# Configuration
RESOURCE_GROUP="azure-graph-mcp-rg"
LOCATION="uksouth"
DEPLOYMENT_NAME="azure-graph-mcp-deployment-$(date +%Y%m%d-%H%M%S)"
APP_NAME="azure-graph-mcp-uksouth"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if required tools are installed
check_requirements() {
    print_status "Checking requirements..."
    
    if ! command -v az &> /dev/null; then
        print_error "Azure CLI is not installed. Please install it first."
        exit 1
    fi
    
    if ! command -v git &> /dev/null; then
        print_error "Git is not installed. Please install it first."
        exit 1
    fi
    
    print_success "All requirements satisfied"
}

# Check Azure login status
check_azure_login() {
    print_status "Checking Azure login status..."
    
    if ! az account show &> /dev/null; then
        print_error "You are not logged in to Azure. Please run 'az login' first."
        exit 1
    fi
    
    SUBSCRIPTION_NAME=$(az account show --query name -o tsv)
    SUBSCRIPTION_ID=$(az account show --query id -o tsv)
    print_success "Logged in to Azure subscription: $SUBSCRIPTION_NAME ($SUBSCRIPTION_ID)"
}

# Get service principal credentials
get_service_principal() {
    print_status "Checking for service principal credentials..."
    
    if [[ -z "$AZURE_CLIENT_ID" || -z "$AZURE_CLIENT_SECRET" || -z "$AZURE_TENANT_ID" ]]; then
        print_warning "Service principal environment variables not set."
        print_status "The deployment will create the app without service principal authentication."
        print_status "You can set these environment variables later in the Azure portal:"
        print_status "- AZURE_CLIENT_ID"
        print_status "- AZURE_CLIENT_SECRET" 
        print_status "- AZURE_TENANT_ID"
        
        AZURE_CLIENT_ID=""
        AZURE_CLIENT_SECRET=""
        AZURE_TENANT_ID=""
    else
        print_success "Service principal credentials found"
    fi
}

# Create resource group
create_resource_group() {
    print_status "Creating resource group '$RESOURCE_GROUP' in '$LOCATION'..."
    
    if az group show --name "$RESOURCE_GROUP" &> /dev/null; then
        print_warning "Resource group '$RESOURCE_GROUP' already exists"
    else
        az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
        print_success "Resource group '$RESOURCE_GROUP' created"
    fi
}

# Deploy infrastructure
deploy_infrastructure() {
    print_status "Deploying infrastructure using Bicep template..."
    
    # Change to the script directory to find the bicep template
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BICEP_FILE="$SCRIPT_DIR/../bicep/main.bicep"
    
    if [[ ! -f "$BICEP_FILE" ]]; then
        print_error "Bicep template not found at $BICEP_FILE"
        exit 1
    fi
    
    az deployment group create \
        --resource-group "$RESOURCE_GROUP" \
        --template-file "$BICEP_FILE" \
        --name "$DEPLOYMENT_NAME" \
        --parameters \
            location="$LOCATION" \
            azureClientId="$AZURE_CLIENT_ID" \
            azureClientSecret="$AZURE_CLIENT_SECRET" \
            azureTenantId="$AZURE_TENANT_ID"
    
    print_success "Infrastructure deployment completed"
}

# Get deployment outputs
get_deployment_outputs() {
    print_status "Getting deployment outputs..."
    
    WEB_APP_NAME=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query properties.outputs.webAppName.value -o tsv)
    
    WEB_APP_URL=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query properties.outputs.webAppUrl.value -o tsv)
    
    MCP_ENDPOINT=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query properties.outputs.mcpEndpoint.value -o tsv)
    
    HTTP_ENDPOINT=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query properties.outputs.httpEndpoint.value -o tsv)
    
    print_success "Web App Name: $WEB_APP_NAME"
    print_success "Web App URL: $WEB_APP_URL"
    print_success "MCP Endpoint: $MCP_ENDPOINT"
    print_success "HTTP Endpoint: $HTTP_ENDPOINT"
}

# Deploy application code
deploy_application() {
    print_status "Deploying application code..."
    
    # Get the repository root directory (assuming script is in deploy/scripts)
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    
    # Create a temporary deployment directory
    TEMP_DIR=$(mktemp -d)
    
    # Copy necessary files
    cp "$REPO_ROOT/azure_graph_mcp_multi.py" "$TEMP_DIR/"
    cp "$REPO_ROOT/requirements-multi.txt" "$TEMP_DIR/requirements.txt"
    
    # Create startup script
    cat > "$TEMP_DIR/startup.sh" << 'EOF'
#!/bin/bash
echo "Starting Azure Resource Graph MCP Server..."
python azure_graph_mcp_multi.py
EOF
    chmod +x "$TEMP_DIR/startup.sh"
    
    # Deploy using zip deployment
    cd "$TEMP_DIR"
    zip -r deployment.zip .
    
    az webapp deployment source config-zip \
        --resource-group "$RESOURCE_GROUP" \
        --name "$WEB_APP_NAME" \
        --src deployment.zip
    
    # Cleanup
    rm -rf "$TEMP_DIR"
    
    print_success "Application deployment completed"
}

# Configure app startup
configure_startup() {
    print_status "Configuring app startup..."
    
    az webapp config set \
        --resource-group "$RESOURCE_GROUP" \
        --name "$WEB_APP_NAME" \
        --startup-file "startup.sh"
    
    print_success "Startup configuration completed"
}

# Test deployment
test_deployment() {
    print_status "Testing deployment..."
    
    # Wait a bit for the app to start
    sleep 10
    
    # Test health endpoint
    if curl -f -s "$WEB_APP_URL/health" > /dev/null; then
        print_success "Health endpoint is responding"
    else
        print_warning "Health endpoint is not responding yet. The app may still be starting up."
    fi
    
    # Test root endpoint
    if curl -f -s "$WEB_APP_URL/" > /dev/null; then
        print_success "Root endpoint is responding"
    else
        print_warning "Root endpoint is not responding yet. The app may still be starting up."
    fi
}

# Main deployment function
main() {
    print_status "Starting Azure Resource Graph MCP Server deployment..."
    
    check_requirements
    check_azure_login
    get_service_principal
    create_resource_group
    deploy_infrastructure
    get_deployment_outputs
    deploy_application
    configure_startup
    test_deployment
    
    print_success "Deployment completed successfully!"
    echo ""
    print_status "📋 Deployment Summary:"
    echo "  • Resource Group: $RESOURCE_GROUP"
    echo "  • Web App: $WEB_APP_NAME"
    echo "  • Web App URL: $WEB_APP_URL"
    echo "  • Claude Desktop endpoint: $MCP_ENDPOINT"
    echo "  • N8N HTTP endpoint: $HTTP_ENDPOINT"
    echo "  • Info page: $WEB_APP_URL/mcp-info"
    echo ""
    print_status "🔧 Next Steps:"
    echo "  1. Configure Azure authentication (if not already done):"
    echo "     - Set environment variables in Azure Portal"
    echo "     - Or use Azure CLI: az login"
    echo "  2. Add to Claude Desktop config:"
    echo "     {\"mcpServers\": {\"azure-graph\": {\"command\": \"mcp-remote\", \"args\": [\"$MCP_ENDPOINT\"]}}}"
    echo "  3. Test with N8N using endpoint: $HTTP_ENDPOINT"
    echo ""
    print_success "Azure Resource Graph MCP Server is ready!"
}

# Run main function
main "$@"
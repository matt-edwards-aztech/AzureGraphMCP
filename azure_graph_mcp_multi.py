#!/usr/bin/env python3
"""
Azure Resource Graph Multi-Transport MCP Server
Supports both Claude Desktop mcp-remote and N8N direct HTTP
"""

import json
import logging
import os
import uuid
import subprocess
from typing import Any, Dict, List, Optional
from datetime import datetime

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app)

# Azure Resource Graph API configuration
API_BASE_URL = "https://management.azure.com"
DEFAULT_API_VERSION = "2024-04-01"
HISTORY_API_VERSION = "2021-06-01-preview"
OPERATIONS_API_VERSION = "2022-10-01"
CHARACTER_LIMIT = 25000

# Authentication functions
async def get_access_token() -> str:
    """Get Azure AD access token for Resource Graph API."""
    # Try Managed Identity first (best for Azure App Service)
    try:
        return await get_managed_identity_token()
    except Exception as e:
        logger.info(f"Managed Identity not available: {e}")
    
    # Try environment variables (Service Principal)
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET") 
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    if all([client_id, client_secret, tenant_id]):
        return await get_service_principal_token(client_id, client_secret, tenant_id)
    
    # Fall back to Azure CLI (for local development)
    return await get_cli_token()

async def get_managed_identity_token() -> str:
    """Get token using Azure Managed Identity (IMDS)."""
    # Azure Instance Metadata Service (IMDS) endpoint
    identity_endpoint = "http://169.254.169.254/metadata/identity/oauth2/token"
    
    headers = {
        "Metadata": "true"
    }
    
    params = {
        "api-version": "2018-02-01",
        "resource": "https://management.azure.com/"
    }
    
    # Use client ID if specified for user-assigned managed identity
    client_id = os.getenv("AZURE_CLIENT_ID")
    if client_id:
        params["client_id"] = client_id
    
    try:
        response = requests.get(
            identity_endpoint,
            headers=headers,
            params=params,
            timeout=10
        )
        response.raise_for_status()
        token_data = response.json()
        return token_data["access_token"]
    except Exception as e:
        raise ValueError(f"Failed to get Managed Identity token: {e}")

async def get_service_principal_token(client_id: str, client_secret: str, tenant_id: str) -> str:
    """Get token using service principal credentials."""
    response = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://management.azure.com/.default"
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30
    )
    response.raise_for_status()
    token_data = response.json()
    return token_data["access_token"]

async def get_cli_token() -> str:
    """Get token from Azure CLI."""
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://management.azure.com/", "--query", "accessToken", "--output", "tsv"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        raise ValueError(f"Failed to get Azure CLI token. Please run 'az login' or set environment variables: {e}")

def make_api_request(method: str, endpoint: str, token: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make authenticated request to Azure Resource Graph API."""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        if method.upper() == "POST":
            response = requests.post(url, json=data, headers=headers, params=params, timeout=30)
        elif method.upper() == "GET":
            response = requests.get(url, headers=headers, params=params, timeout=30)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
            
        response.raise_for_status()
        return response.json()
        
    except requests.HTTPError as e:
        error_detail = ""
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
        raise ValueError(f"Azure API error ({e.response.status_code}): {error_detail}")
    except requests.Timeout:
        raise ValueError("Request timed out. Try reducing the scope or adding filters to your query.")
    except Exception as e:
        raise ValueError(f"Request failed: {str(e)}")

def format_response(data: Dict[str, Any], format_type: str, title: str = "Results") -> str:
    """Format API response based on requested format."""
    if format_type == "json":
        return json.dumps(data, indent=2, default=str)
    
    # Markdown format
    result = [f"# {title}\n"]
    
    # Add metadata
    if "totalRecords" in data:
        result.append(f"**Total Records:** {data['totalRecords']}")
    if "count" in data:
        result.append(f"**Returned:** {data['count']}")
    if data.get("resultTruncated"):
        result.append("⚠️ **Results truncated** - use pagination or filters for complete data")
    
    # Add pagination info
    if "$skipToken" in data:
        result.append(f"📄 **Next Page Available** - use skipToken: `{data['$skipToken'][:50]}...`")
    
    result.append("")
    
    # Format main data
    if "data" in data and data["data"]:
        result.append("## Resources\n")
        for i, item in enumerate(data["data"][:20], 1):  # Limit display items
            if isinstance(item, dict):
                result.append(f"### {i}. {item.get('name', 'Unknown')}")
                if "type" in item:
                    result.append(f"**Type:** {item['type']}")
                if "location" in item:
                    result.append(f"**Location:** {item['location']}")
                if "resourceGroup" in item:
                    result.append(f"**Resource Group:** {item['resourceGroup']}")
                if "id" in item:
                    result.append(f"**ID:** `{item['id']}`")
                if "tags" in item and item["tags"]:
                    tag_strings = [f"{k}={v}" for k, v in item["tags"].items()]
                    result.append(f"**Tags:** {', '.join(tag_strings)}")
                result.append("")
        
        if len(data["data"]) > 20:
            result.append(f"... and {len(data['data']) - 20} more items (use JSON format for complete data)\n")
    
    # Format facets if present
    if "facets" in data and data["facets"]:
        result.append("## Facets\n")
        for facet in data["facets"]:
            if facet.get("resultType") == "FacetResult":
                result.append(f"### {facet['expression']}")
                if "data" in facet and facet["data"]:
                    for item in facet["data"][:10]:  # Show top 10
                        count = item.get("count", item.get("count_", "N/A"))
                        key = next((v for k, v in item.items() if k != "count" and k != "count_"), "Unknown")
                        result.append(f"- **{key}:** {count}")
                result.append("")
            elif facet.get("resultType") == "FacetError":
                result.append(f"### ❌ {facet['expression']} (Error)")
                if "errors" in facet:
                    for error in facet["errors"]:
                        result.append(f"- {error.get('message', 'Unknown error')}")
                result.append("")
    
    response_text = "\n".join(result)
    
    # Check character limit
    if len(response_text) > CHARACTER_LIMIT:
        truncation_point = CHARACTER_LIMIT - 200
        response_text = response_text[:truncation_point] + f"\n\n⚠️ **Response truncated at {CHARACTER_LIMIT} characters.** Use JSON format for complete data or add filters to reduce results."
    
    return response_text

def build_search_query(params: Dict[str, Any]) -> str:
    """Build KQL query from search parameters."""
    query_parts = ["Resources"]
    where_conditions = []
    
    if params.get("resource_type"):
        where_conditions.append(f"type =~ '{params['resource_type']}'")
    
    if params.get("location"):
        where_conditions.append(f"location =~ '{params['location']}'")
        
    if params.get("resource_group"):
        where_conditions.append(f"resourceGroup =~ '{params['resource_group']}'")
        
    if params.get("name_filter"):
        where_conditions.append(f"name contains '{params['name_filter']}'")
        
    if params.get("tag_filter"):
        tag_filter = params["tag_filter"]
        if "=" in tag_filter:
            tag_key, tag_value = tag_filter.split("=", 1)
            where_conditions.append(f"tags['{tag_key.strip()}'] =~ '{tag_value.strip()}'")
        else:
            where_conditions.append(f"tags has '{tag_filter}'")
    
    if where_conditions:
        query_parts.append(f"| where {' and '.join(where_conditions)}")
    
    # Project fields
    if params.get("include_properties"):
        query_parts.append("| project id, name, type, location, resourceGroup, tags, properties")
    else:
        query_parts.append("| project id, name, type, location, resourceGroup, tags")
    
    # Add limit
    if params.get("limit"):
        query_parts.append(f"| limit {params['limit']}")
    
    return " ".join(query_parts)

# Tool implementations
async def azure_resource_graph_query(query: str, subscriptions: list = None, management_groups: list = None, 
                                    facets: list = None, options: dict = None, response_format: str = "markdown") -> str:
    """Execute a KQL query against Azure Resource Graph."""
    try:
        token = await get_access_token()
        
        # Build request payload
        request_data = {"query": query}
        
        if subscriptions:
            request_data["subscriptions"] = subscriptions
        if management_groups:
            request_data["managementGroups"] = management_groups
        if facets:
            request_data["facets"] = facets
        if options:
            request_data["options"] = options
        
        # Make API request
        endpoint = f"/providers/Microsoft.ResourceGraph/resources"
        response = make_api_request(
            method="POST",
            endpoint=endpoint,
            token=token,
            data=request_data,
            params={"api-version": DEFAULT_API_VERSION}
        )
        
        return format_response(response, response_format, "Azure Resource Graph Query Results")
        
    except Exception as e:
        error_msg = f"Failed to execute Azure Resource Graph query: {str(e)}"
        logger.error(error_msg)
        return f"❌ **Error:** {error_msg}\n\n💡 **Tips:**\n- Ensure you're logged in with 'az login'\n- Check your query syntax\n- Verify subscription/management group access\n- Try reducing scope or adding filters"

async def azure_resource_graph_history(query: str, subscriptions: list = None, management_groups: list = None,
                                     options: dict = None, interval: str = None, response_format: str = "markdown") -> str:
    """Query the history of Azure resources."""
    try:
        token = await get_access_token()
        
        # Build request payload
        request_data = {"query": query}
        
        if subscriptions:
            request_data["subscriptions"] = subscriptions
        if management_groups:
            request_data["managementGroups"] = management_groups
        if options:
            request_data["options"] = options
        if interval:
            request_data["interval"] = interval
        
        # Make API request to history endpoint
        endpoint = f"/providers/Microsoft.ResourceGraph/resourcesHistory"
        response = make_api_request(
            method="POST",
            endpoint=endpoint,
            token=token,
            data=request_data,
            params={"api-version": HISTORY_API_VERSION}
        )
        
        return format_response(response, response_format, "Azure Resource History Results")
        
    except Exception as e:
        error_msg = f"Failed to query Azure Resource Graph history: {str(e)}"
        logger.error(error_msg)
        return f"❌ **Error:** {error_msg}\n\n💡 **Tips:**\n- Resource history is in preview and may have limited availability\n- Ensure you have proper permissions for historical data access\n- Try a simpler query or shorter time interval"

async def azure_resource_graph_operations(response_format: str = "markdown") -> str:
    """List all available Azure Resource Graph REST API operations."""
    try:
        token = await get_access_token()
        
        # Make API request to operations endpoint
        endpoint = f"/providers/Microsoft.ResourceGraph/operations"
        response = make_api_request(
            method="GET",
            endpoint=endpoint,
            token=token,
            params={"api-version": OPERATIONS_API_VERSION}
        )
        
        if response_format == "json":
            return json.dumps(response, indent=2)
        
        # Format as markdown
        result = ["# Azure Resource Graph Operations\n"]
        
        if "value" in response:
            for operation in response["value"]:
                name = operation.get("name", "Unknown")
                display = operation.get("display", {})
                provider = display.get("provider", "")
                resource = display.get("resource", "")
                op_name = display.get("operation", "")
                description = display.get("description", "")
                
                result.append(f"## {name}")
                if provider:
                    result.append(f"**Provider:** {provider}")
                if resource:
                    result.append(f"**Resource:** {resource}")
                if op_name:
                    result.append(f"**Operation:** {op_name}")
                if description:
                    result.append(f"**Description:** {description}")
                result.append("")
        
        return "\n".join(result)
        
    except Exception as e:
        error_msg = f"Failed to list Azure Resource Graph operations: {str(e)}"
        logger.error(error_msg)
        return f"❌ **Error:** {error_msg}"

async def azure_resource_graph_search_resources(resource_type: str = None, location: str = None,
                                               resource_group: str = None, name_filter: str = None,
                                               tag_filter: str = None, subscriptions: list = None,
                                               limit: int = 50, include_properties: bool = False,
                                               response_format: str = "markdown") -> str:
    """Search for Azure resources using simplified filters."""
    try:
        token = await get_access_token()
        
        # Build search parameters
        params = {
            "resource_type": resource_type,
            "location": location,
            "resource_group": resource_group,
            "name_filter": name_filter,
            "tag_filter": tag_filter,
            "limit": limit,
            "include_properties": include_properties
        }
        
        # Build KQL query from search parameters
        kql_query = build_search_query(params)
        
        # Build request payload
        request_data = {"query": kql_query}
        
        if subscriptions:
            request_data["subscriptions"] = subscriptions
        
        # Make API request
        endpoint = f"/providers/Microsoft.ResourceGraph/resources"
        response = make_api_request(
            method="POST",
            endpoint=endpoint,
            token=token,
            data=request_data,
            params={"api-version": DEFAULT_API_VERSION}
        )
        
        # Add search criteria to response
        if response_format == "markdown":
            search_info = ["# Azure Resource Search Results\n"]
            search_info.append("## Search Criteria")
            
            if resource_type:
                search_info.append(f"**Resource Type:** {resource_type}")
            if location:
                search_info.append(f"**Location:** {location}")
            if resource_group:
                search_info.append(f"**Resource Group:** {resource_group}")
            if name_filter:
                search_info.append(f"**Name Contains:** {name_filter}")
            if tag_filter:
                search_info.append(f"**Tag Filter:** {tag_filter}")
            if subscriptions:
                search_info.append(f"**Subscriptions:** {', '.join(subscriptions[:3])}{'...' if len(subscriptions) > 3 else ''}")
                
            search_info.append(f"**Generated Query:** `{kql_query}`\n")
            
            formatted_response = format_response(response, response_format, "Search Results")
            return "\n".join(search_info) + "\n" + formatted_response
        else:
            # Add search metadata to JSON response
            response["search_criteria"] = {
                "resource_type": resource_type,
                "location": location,
                "resource_group": resource_group,
                "name_filter": name_filter,
                "tag_filter": tag_filter,
                "subscriptions": subscriptions,
                "generated_query": kql_query
            }
            return format_response(response, response_format)
        
    except Exception as e:
        error_msg = f"Failed to search Azure resources: {str(e)}"
        logger.error(error_msg)
        return f"❌ **Error:** {error_msg}\n\n💡 **Tips:**\n- Check your search criteria\n- Ensure you have access to the specified subscriptions\n- Try broadening your search filters"

# MCP request handler
def handle_mcp_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle MCP request and return response."""
    import asyncio
    
    method = data.get("method")
    request_id = data.get("id")
    params = data.get("params", {})
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "azure-graph-multi-mcp",
                    "version": "1.0.0"
                }
            }
        }
        
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "azure_resource_graph_query",
                        "description": "Execute KQL queries against Azure Resource Graph",
                        "inputSchema": {
                            "type": "object",
                            "required": ["query"],
                            "properties": {
                                "query": {"type": "string", "description": "KQL query to execute"},
                                "subscriptions": {"type": "array", "items": {"type": "string"}, "description": "Subscription IDs to query"},
                                "management_groups": {"type": "array", "items": {"type": "string"}, "description": "Management group names to query"},
                                "facets": {"type": "array", "description": "Additional statistics requests"},
                                "options": {"type": "object", "description": "Query options (pagination, scope, format)"},
                                "response_format": {"type": "string", "enum": ["markdown", "json"], "description": "Output format"}
                            }
                        }
                    },
                    {
                        "name": "azure_resource_graph_search_resources", 
                        "description": "Search for Azure resources using simplified filters",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "resource_type": {"type": "string", "description": "Resource type filter"},
                                "location": {"type": "string", "description": "Azure region filter"},
                                "resource_group": {"type": "string", "description": "Resource group name filter"},
                                "name_filter": {"type": "string", "description": "Resource name filter"},
                                "tag_filter": {"type": "string", "description": "Tag filter (e.g., 'environment=prod')"},
                                "subscriptions": {"type": "array", "items": {"type": "string"}, "description": "Subscription IDs to search"},
                                "limit": {"type": "number", "minimum": 1, "maximum": 1000, "description": "Maximum results"},
                                "include_properties": {"type": "boolean", "description": "Include detailed properties"},
                                "response_format": {"type": "string", "enum": ["markdown", "json"], "description": "Output format"}
                            }
                        }
                    },
                    {
                        "name": "azure_resource_graph_history",
                        "description": "Query Azure resource history and changes over time",
                        "inputSchema": {
                            "type": "object",
                            "required": ["query"],
                            "properties": {
                                "query": {"type": "string", "description": "KQL query for resource history"},
                                "subscriptions": {"type": "array", "items": {"type": "string"}, "description": "Subscription IDs to query"},
                                "management_groups": {"type": "array", "items": {"type": "string"}, "description": "Management group names to query"},
                                "options": {"type": "object", "description": "Query options"},
                                "interval": {"type": "string", "description": "Time interval (ISO 8601 format)"},
                                "response_format": {"type": "string", "enum": ["markdown", "json"], "description": "Output format"}
                            }
                        }
                    },
                    {
                        "name": "azure_resource_graph_operations",
                        "description": "List available Azure Resource Graph operations",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "response_format": {"type": "string", "enum": ["markdown", "json"], "description": "Output format"}
                            }
                        }
                    }
                ]
            }
        }
        
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if tool_name == "azure_resource_graph_query":
                result = loop.run_until_complete(azure_resource_graph_query(
                    query=arguments.get("query"),
                    subscriptions=arguments.get("subscriptions"),
                    management_groups=arguments.get("management_groups"),
                    facets=arguments.get("facets"),
                    options=arguments.get("options"),
                    response_format=arguments.get("response_format", "markdown")
                ))
            elif tool_name == "azure_resource_graph_search_resources":
                result = loop.run_until_complete(azure_resource_graph_search_resources(
                    resource_type=arguments.get("resource_type"),
                    location=arguments.get("location"),
                    resource_group=arguments.get("resource_group"),
                    name_filter=arguments.get("name_filter"),
                    tag_filter=arguments.get("tag_filter"),
                    subscriptions=arguments.get("subscriptions"),
                    limit=arguments.get("limit", 50),
                    include_properties=arguments.get("include_properties", False),
                    response_format=arguments.get("response_format", "markdown")
                ))
            elif tool_name == "azure_resource_graph_history":
                result = loop.run_until_complete(azure_resource_graph_history(
                    query=arguments.get("query"),
                    subscriptions=arguments.get("subscriptions"),
                    management_groups=arguments.get("management_groups"),
                    options=arguments.get("options"),
                    interval=arguments.get("interval"),
                    response_format=arguments.get("response_format", "markdown")
                ))
            elif tool_name == "azure_resource_graph_operations":
                result = loop.run_until_complete(azure_resource_graph_operations(
                    response_format=arguments.get("response_format", "markdown")
                ))
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unknown tool: {tool_name}"
                    }
                }
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": result
                        }
                    ]
                }
            }
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": f"Tool execution failed: {str(e)}"
                }
            }
        finally:
            loop.close()
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }

@app.route('/')
def root():
    """Root endpoint with server information."""
    return jsonify({
        "name": "Azure Resource Graph Multi-Transport MCP Server",
        "version": "1.0.0",
        "status": "running",
        "description": "Multi-transport MCP server for Azure Resource Graph queries",
        "endpoints": {
            "claude_mcp": "/mcp (for mcp-remote)",
            "n8n_http": "/mcp-http (for direct HTTP)",
            "health": "/health"
        },
        "tools": [
            "azure_resource_graph_query",
            "azure_resource_graph_search_resources", 
            "azure_resource_graph_history",
            "azure_resource_graph_operations"
        ]
    })

@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "protocol": "Multi-Transport MCP"})

# Claude Desktop endpoint (mcp-remote compatible)
@app.route('/mcp', methods=['GET', 'POST'])
def mcp_claude_endpoint():
    """Unified endpoint for Claude Desktop mcp-remote (both SSE and messages)."""
    if request.method == 'GET':
        # SSE endpoint
        def event_stream():
            logger.info("Claude Desktop SSE connection established")
            
            # Send endpoint event - point to the same /mcp endpoint for POST
            endpoint_event = {
                "endpoint": "https://azure-graph-mcp-uksouth.azurewebsites.net/mcp"
            }
            yield f"event: endpoint\ndata: {json.dumps(endpoint_event)}\n\n"
            
            # Keep alive
            try:
                import time
                while True:
                    yield f"event: ping\ndata: {json.dumps({'time': datetime.now().isoformat()})}\n\n"
                    time.sleep(30)
            except GeneratorExit:
                logger.info("SSE connection closed")
        
        return Response(
            event_stream(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*'
            }
        )
    
    elif request.method == 'POST':
        # Message endpoint
        try:
            data = request.get_json()
            if not data:
                return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}), 400
            
            logger.info(f"Claude Desktop message: {data.get('method')}")
            response = handle_mcp_request(data)
            return jsonify(response)
            
        except Exception as e:
            logger.error(f"Claude message error: {e}")
            return jsonify({
                "jsonrpc": "2.0",
                "id": data.get("id") if data else None,
                "error": {"code": -32000, "message": f"Internal error: {str(e)}"}
            }), 500

# N8N/Direct HTTP endpoint
@app.route('/mcp-http', methods=['POST'])
def mcp_http_direct():
    """Direct HTTP endpoint for N8N and other platforms."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}), 400
        
        logger.info(f"HTTP MCP request: {data.get('method')}")
        response = handle_mcp_request(data)
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"HTTP MCP error: {e}")
        return jsonify({
            "jsonrpc": "2.0",
            "id": data.get("id") if data else None,
            "error": {"code": -32000, "message": f"Internal error: {str(e)}"}
        }), 500

@app.route('/mcp-info')
def mcp_info():
    """Information about connecting to this MCP server."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Azure Resource Graph Multi-Transport MCP Server</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }
            pre { background: #f5f5f5; padding: 20px; border-radius: 5px; overflow-x: auto; }
            .endpoint { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
        </style>
    </head>
    <body>
        <h1>Azure Resource Graph Multi-Transport MCP Server</h1>
        <p>This server supports multiple transport methods for maximum compatibility.</p>
        
        <div class="endpoint">
            <h2>🖥️ Claude Desktop (mcp-remote)</h2>
            <p><strong>Endpoint:</strong> <code>https://azure-graph-mcp-uksouth.azurewebsites.net/mcp</code></p>
            <pre>{
  "mcpServers": {
    "azure-graph": {
      "command": "mcp-remote",
      "args": [
        "https://azure-graph-mcp-uksouth.azurewebsites.net/mcp"
      ]
    }
  }
}</pre>
        </div>
        
        <div class="endpoint">
            <h2>🔗 N8N / Direct HTTP</h2>
            <p><strong>Endpoint:</strong> <code>https://azure-graph-mcp-uksouth.azurewebsites.net/mcp-http</code></p>
            <p>Make direct HTTP POST requests with MCP JSON-RPC payloads.</p>
            <pre>curl -X POST https://azure-graph-mcp-uksouth.azurewebsites.net/mcp-http \\
  -H "Content-Type: application/json" \\
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'</pre>
        </div>
        
        <h2>🛠️ Available Tools</h2>
        <ul>
            <li><strong>azure_resource_graph_query</strong> - Execute KQL queries against Azure Resource Graph</li>
            <li><strong>azure_resource_graph_search_resources</strong> - Search for resources using simplified filters</li>
            <li><strong>azure_resource_graph_history</strong> - Query resource history and changes over time</li>
            <li><strong>azure_resource_graph_operations</strong> - List available Azure Resource Graph operations</li>
        </ul>
        
        <h2>🔐 Authentication</h2>
        <p>Configure Azure authentication via:</p>
        <ul>
            <li><strong>Azure CLI:</strong> Run <code>az login</code></li>
            <li><strong>Service Principal:</strong> Set environment variables:
                <ul>
                    <li>AZURE_CLIENT_ID</li>
                    <li>AZURE_CLIENT_SECRET</li>
                    <li>AZURE_TENANT_ID</li>
                </ul>
            </li>
        </ul>
        
        <h2>📋 Example Queries</h2>
        <ul>
            <li>"List all virtual machines in East US"</li>
            <li>"Find all storage accounts with production tags"</li>
            <li>"Show resource distribution by location"</li>
            <li>"Track changes to network security groups"</li>
        </ul>
    </body>
    </html>
    """

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    logger.info(f"Starting Azure Resource Graph Multi-Transport MCP Server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)
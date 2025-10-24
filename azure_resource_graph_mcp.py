#!/usr/bin/env python3
"""
Azure Resource Graph MCP Server

This MCP server provides tools to query Azure resources using the Azure Resource Graph REST API.
It enables AI assistants to explore Azure infrastructure, track resource changes, and analyze
resource configurations across subscriptions and management groups.

Key Features:
- Execute KQL queries against Azure resources
- Query resource history and changes
- Search resources with filters
- Support for subscription, management group, and tenant scopes
- Proper pagination and result formatting
- Azure AD OAuth2 authentication
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator, ConfigDict

# Constants
CHARACTER_LIMIT = 25000
API_BASE_URL = "https://management.azure.com"
DEFAULT_API_VERSION = "2024-04-01"
HISTORY_API_VERSION = "2021-06-01-preview" 
OPERATIONS_API_VERSION = "2022-10-01"

# Initialize FastMCP server
mcp = FastMCP("azure_resource_graph_mcp")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


class ResultFormat(str, Enum):
    """Azure Resource Graph result format."""
    TABLE = "table"
    OBJECT_ARRAY = "objectArray"


class AuthorizationScopeFilter(str, Enum):
    """Authorization scope filter for resource queries."""
    AT_SCOPE_AND_BELOW = "AtScopeAndBelow"
    AT_SCOPE_AND_ABOVE = "AtScopeAndAbove"
    AT_SCOPE_EXACT = "AtScopeExact"
    AT_SCOPE_ABOVE_AND_BELOW = "AtScopeAboveAndBelow"


class SortOrder(str, Enum):
    """Sort order for facets."""
    ASC = "asc"
    DESC = "desc"


# Input Models
class FacetRequestOptions(BaseModel):
    """Options for facet evaluation."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    top: Optional[int] = Field(
        default=None,
        alias="$top",
        description="Maximum number of facet rows (1-1000)",
        ge=1,
        le=1000
    )
    filter: Optional[str] = Field(
        default=None,
        description="Filter condition for the facet (e.g., \"resourceGroup contains 'test'\")"
    )
    sort_by: Optional[str] = Field(
        default=None,
        alias="sortBy",
        description="Column name or expression to sort on (defaults to count)"
    )
    sort_order: Optional[SortOrder] = Field(
        default=SortOrder.DESC,
        alias="sortOrder",
        description="Sort order: 'asc' or 'desc'"
    )


class FacetRequest(BaseModel):
    """Request to compute additional statistics over query results."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    expression: str = Field(
        ...,
        description="Column or list of columns to summarize by (e.g., 'location', 'resourceGroup')"
    )
    options: Optional[FacetRequestOptions] = Field(
        default=None,
        description="Facet evaluation options"
    )


class QueryRequestOptions(BaseModel):
    """Options for query evaluation."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    top: Optional[int] = Field(
        default=None,
        alias="$top", 
        description="Maximum number of rows to return (1-1000)",
        ge=1,
        le=1000
    )
    skip: Optional[int] = Field(
        default=None,
        alias="$skip",
        description="Number of rows to skip from beginning",
        ge=0
    )
    skip_token: Optional[str] = Field(
        default=None,
        alias="$skipToken",
        description="Continuation token for pagination"
    )
    allow_partial_scopes: Optional[bool] = Field(
        default=False,
        alias="allowPartialScopes",
        description="Allow partial scopes if subscription limits are exceeded"
    )
    authorization_scope_filter: Optional[AuthorizationScopeFilter] = Field(
        default=AuthorizationScopeFilter.AT_SCOPE_AND_BELOW,
        alias="authorizationScopeFilter",
        description="Authorization level for returned resources"
    )
    result_format: Optional[ResultFormat] = Field(
        default=ResultFormat.OBJECT_ARRAY,
        alias="resultFormat",
        description="Format of query results: 'table' or 'objectArray'"
    )


class ResourceGraphQueryInput(BaseModel):
    """Input for Azure Resource Graph query operations."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    query: str = Field(
        ...,
        description="KQL query to execute (e.g., 'Resources | where type =~ \"Microsoft.Compute/virtualMachines\" | limit 5')",
        min_length=1,
        max_length=10000
    )
    subscriptions: Optional[List[str]] = Field(
        default=None,
        description="Azure subscription IDs to query (e.g., ['sub1-guid', 'sub2-guid'])",
        max_items=1000
    )
    management_groups: Optional[List[str]] = Field(
        default=None,
        alias="managementGroups",
        description="Management group names to query (e.g., ['mg1', 'ProductionMG'])",
        max_items=1000
    )
    facets: Optional[List[FacetRequest]] = Field(
        default=None,
        description="Facet requests for additional statistics",
        max_items=10
    )
    options: Optional[QueryRequestOptions] = Field(
        default=None,
        description="Query evaluation options (pagination, scope, format)"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for machine-readable"
    )

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate KQL query."""
        if not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()

    @field_validator('subscriptions')
    @classmethod 
    def validate_subscriptions(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate subscription GUIDs."""
        if v is None:
            return v
        return [sub.strip() for sub in v if sub.strip()]

    @field_validator('management_groups')
    @classmethod
    def validate_management_groups(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate management group names."""
        if v is None:
            return v
        return [mg.strip() for mg in v if mg.strip()]


class ResourceHistoryInput(BaseModel):
    """Input for resource history queries."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    query: str = Field(
        ...,
        description="KQL query for resource history (e.g., 'Resources | where type =~ \"Microsoft.Compute/virtualMachines\"')",
        min_length=1,
        max_length=10000
    )
    subscriptions: Optional[List[str]] = Field(
        default=None,
        description="Azure subscription IDs to query",
        max_items=1000
    )
    management_groups: Optional[List[str]] = Field(
        default=None,
        alias="managementGroups", 
        description="Management group names to query",
        max_items=1000
    )
    options: Optional[QueryRequestOptions] = Field(
        default=None,
        description="Query options for pagination and filtering"
    )
    interval: Optional[str] = Field(
        default=None,
        description="Time interval for history (ISO 8601 format, e.g., 'PT1H' for 1 hour)"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'"
    )


class ResourceSearchInput(BaseModel):
    """Input for simplified resource search with filters."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    resource_type: Optional[str] = Field(
        default=None,
        description="Resource type filter (e.g., 'Microsoft.Compute/virtualMachines', 'Microsoft.Storage/storageAccounts')"
    )
    location: Optional[str] = Field(
        default=None,
        description="Azure region/location filter (e.g., 'eastus', 'westeurope')"
    )
    resource_group: Optional[str] = Field(
        default=None,
        description="Resource group name filter"
    )
    name_filter: Optional[str] = Field(
        default=None,
        description="Resource name filter (supports wildcards with 'contains' logic)"
    )
    tag_filter: Optional[str] = Field(
        default=None,
        description="Tag filter (e.g., 'environment=prod' or 'team=data')"
    )
    subscriptions: Optional[List[str]] = Field(
        default=None,
        description="Subscription IDs to search within",
        max_items=1000
    )
    limit: Optional[int] = Field(
        default=50,
        description="Maximum number of results to return",
        ge=1,
        le=1000
    )
    include_properties: bool = Field(
        default=False,
        description="Include detailed resource properties in results"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'"
    )


# Utility Functions
async def get_access_token() -> str:
    """
    Get Azure AD access token for Resource Graph API.
    
    Uses Azure CLI authentication or environment variables.
    """
    # Try environment variables first
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET") 
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    if all([client_id, client_secret, tenant_id]):
        return await get_service_principal_token(client_id, client_secret, tenant_id)
    
    # Fall back to Azure CLI
    return await get_cli_token()


async def get_service_principal_token(client_id: str, client_secret: str, tenant_id: str) -> str:
    """Get token using service principal credentials."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://management.azure.com/.default"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()
        token_data = response.json()
        return token_data["access_token"]


async def get_cli_token() -> str:
    """Get token from Azure CLI."""
    try:
        import subprocess
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://management.azure.com/", "--query", "accessToken", "--output", "tsv"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        raise ValueError(f"Failed to get Azure CLI token. Please run 'az login' or set environment variables: {e}")


async def make_api_request(
    method: str,
    endpoint: str, 
    token: str,
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Make authenticated request to Azure Resource Graph API."""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if method.upper() == "POST":
                response = await client.post(url, json=data, headers=headers, params=params)
            elif method.upper() == "GET":
                response = await client.get(url, headers=headers, params=params)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_data = e.response.json()
                error_detail = error_data.get("error", {}).get("message", str(e))
            except:
                error_detail = str(e)
            raise ValueError(f"Azure API error ({e.response.status_code}): {error_detail}")
        except httpx.TimeoutException:
            raise ValueError("Request timed out. Try reducing the scope or adding filters to your query.")
        except Exception as e:
            raise ValueError(f"Request failed: {str(e)}")


def build_search_query(params: ResourceSearchInput) -> str:
    """Build KQL query from search parameters."""
    query_parts = ["Resources"]
    
    where_conditions = []
    
    if params.resource_type:
        where_conditions.append(f"type =~ '{params.resource_type}'")
    
    if params.location:
        where_conditions.append(f"location =~ '{params.location}'")
        
    if params.resource_group:
        where_conditions.append(f"resourceGroup =~ '{params.resource_group}'")
        
    if params.name_filter:
        where_conditions.append(f"name contains '{params.name_filter}'")
        
    if params.tag_filter:
        if "=" in params.tag_filter:
            tag_key, tag_value = params.tag_filter.split("=", 1)
            where_conditions.append(f"tags['{tag_key.strip()}'] =~ '{tag_value.strip()}'")
        else:
            where_conditions.append(f"tags has '{params.tag_filter}'")
    
    if where_conditions:
        query_parts.append(f"| where {' and '.join(where_conditions)}")
    
    # Project fields
    if params.include_properties:
        query_parts.append("| project id, name, type, location, resourceGroup, tags, properties")
    else:
        query_parts.append("| project id, name, type, location, resourceGroup, tags")
    
    # Add limit
    if params.limit:
        query_parts.append(f"| limit {params.limit}")
    
    return " ".join(query_parts)


def format_response(data: Dict[str, Any], format_type: ResponseFormat, title: str = "Results") -> str:
    """Format API response based on requested format."""
    if format_type == ResponseFormat.JSON:
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


# MCP Tools
@mcp.tool(
    name="azure_resource_graph_query",
    annotations={
        "title": "Azure Resource Graph Query",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def azure_resource_graph_query(params: ResourceGraphQueryInput) -> str:
    """
    Execute a KQL query against Azure Resource Graph to explore and analyze Azure resources.
    
    This tool allows you to query Azure resources across subscriptions and management groups
    using the powerful Kusto Query Language (KQL). You can filter, aggregate, and analyze
    your Azure infrastructure.
    
    Args:
        params (ResourceGraphQueryInput): Query parameters containing:
            - query (str): KQL query string (e.g., 'Resources | where type =~ "Microsoft.Compute/virtualMachines" | limit 5')
            - subscriptions (Optional[List[str]]): Subscription IDs to query
            - management_groups (Optional[List[str]]): Management group names to query  
            - facets (Optional[List[FacetRequest]]): Additional statistics to compute
            - options (Optional[QueryRequestOptions]): Pagination and formatting options
            - response_format (ResponseFormat): Output format ('markdown' or 'json')
    
    Returns:
        str: Query results in the requested format, including resources, metadata, and facets
        
    Example queries:
        - List all VMs: 'Resources | where type =~ "Microsoft.Compute/virtualMachines" | project name, location'
        - Count by location: 'Resources | summarize count() by location'  
        - Find resources by tag: 'Resources | where tags["environment"] =~ "production"'
    """
    try:
        token = await get_access_token()
        
        # Build request payload
        request_data = {
            "query": params.query
        }
        
        if params.subscriptions:
            request_data["subscriptions"] = params.subscriptions
            
        if params.management_groups:
            request_data["managementGroups"] = params.management_groups
            
        if params.facets:
            request_data["facets"] = [facet.model_dump(by_alias=True, exclude_none=True) for facet in params.facets]
            
        if params.options:
            request_data["options"] = params.options.model_dump(by_alias=True, exclude_none=True)
        
        # Make API request
        endpoint = f"/providers/Microsoft.ResourceGraph/resources"
        response = await make_api_request(
            method="POST",
            endpoint=endpoint,
            token=token,
            data=request_data,
            params={"api-version": DEFAULT_API_VERSION}
        )
        
        return format_response(response, params.response_format, "Azure Resource Graph Query Results")
        
    except Exception as e:
        error_msg = f"Failed to execute Azure Resource Graph query: {str(e)}"
        logger.error(error_msg)
        return f"❌ **Error:** {error_msg}\n\n💡 **Tips:**\n- Ensure you're logged in with 'az login'\n- Check your query syntax\n- Verify subscription/management group access\n- Try reducing scope or adding filters"


@mcp.tool(
    name="azure_resource_graph_history",
    annotations={
        "title": "Azure Resource Graph History", 
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def azure_resource_graph_history(params: ResourceHistoryInput) -> str:
    """
    Query the history of Azure resources to track changes and modifications over time.
    
    This tool provides access to historical snapshots of Azure resources, allowing you to
    analyze how your infrastructure has changed, track configuration modifications, and
    investigate incidents or compliance requirements.
    
    Args:
        params (ResourceHistoryInput): History query parameters containing:
            - query (str): KQL query for resource history
            - subscriptions (Optional[List[str]]): Subscription IDs to query
            - management_groups (Optional[List[str]]): Management group names to query
            - options (Optional[QueryRequestOptions]): Query options for pagination
            - interval (Optional[str]): Time interval for history (ISO 8601 format)
            - response_format (ResponseFormat): Output format ('markdown' or 'json')
    
    Returns:
        str: Historical resource data showing changes over time
        
    Example queries:
        - Track VM changes: 'Resources | where type =~ "Microsoft.Compute/virtualMachines" | where name == "myvm"'
        - Storage account modifications: 'Resources | where type =~ "Microsoft.Storage/storageAccounts"'
    """
    try:
        token = await get_access_token()
        
        # Build request payload
        request_data = {
            "query": params.query
        }
        
        if params.subscriptions:
            request_data["subscriptions"] = params.subscriptions
            
        if params.management_groups:
            request_data["managementGroups"] = params.management_groups
            
        if params.options:
            request_data["options"] = params.options.model_dump(by_alias=True, exclude_none=True)
            
        if params.interval:
            request_data["interval"] = params.interval
        
        # Make API request to history endpoint
        endpoint = f"/providers/Microsoft.ResourceGraph/resourcesHistory"
        response = await make_api_request(
            method="POST",
            endpoint=endpoint,
            token=token,
            data=request_data,
            params={"api-version": HISTORY_API_VERSION}
        )
        
        return format_response(response, params.response_format, "Azure Resource History Results")
        
    except Exception as e:
        error_msg = f"Failed to query Azure Resource Graph history: {str(e)}"
        logger.error(error_msg)
        return f"❌ **Error:** {error_msg}\n\n💡 **Tips:**\n- Resource history is in preview and may have limited availability\n- Ensure you have proper permissions for historical data access\n- Try a simpler query or shorter time interval"


@mcp.tool(
    name="azure_resource_graph_operations",
    annotations={
        "title": "Azure Resource Graph Operations",
        "readOnlyHint": True,
        "destructiveHint": False, 
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def azure_resource_graph_operations(response_format: ResponseFormat = ResponseFormat.MARKDOWN) -> str:
    """
    List all available Azure Resource Graph REST API operations.
    
    This tool retrieves the complete list of operations supported by the Azure Resource Graph
    service, including their descriptions and capabilities. Useful for understanding what
    actions are available and their purposes.
    
    Args:
        response_format (ResponseFormat): Output format ('markdown' or 'json')
    
    Returns:
        str: List of available operations with descriptions
    """
    try:
        token = await get_access_token()
        
        # Make API request to operations endpoint
        endpoint = f"/providers/Microsoft.ResourceGraph/operations"
        response = await make_api_request(
            method="GET",
            endpoint=endpoint,
            token=token,
            params={"api-version": OPERATIONS_API_VERSION}
        )
        
        if response_format == ResponseFormat.JSON:
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


@mcp.tool(
    name="azure_resource_graph_search_resources",
    annotations={
        "title": "Azure Resource Search",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True, 
        "openWorldHint": True
    }
)
async def azure_resource_graph_search_resources(params: ResourceSearchInput) -> str:
    """
    Search for Azure resources using simplified filters instead of writing KQL queries.
    
    This tool provides an easier way to find Azure resources without needing to know KQL syntax.
    You can filter by resource type, location, resource group, name patterns, and tags.
    
    Args:
        params (ResourceSearchInput): Search parameters containing:
            - resource_type (Optional[str]): Resource type filter (e.g., 'Microsoft.Compute/virtualMachines')
            - location (Optional[str]): Azure region filter (e.g., 'eastus')
            - resource_group (Optional[str]): Resource group name filter
            - name_filter (Optional[str]): Resource name filter (supports contains logic)
            - tag_filter (Optional[str]): Tag filter (e.g., 'environment=prod')
            - subscriptions (Optional[List[str]]): Subscription IDs to search
            - limit (Optional[int]): Maximum results to return (1-1000)
            - include_properties (bool): Include detailed resource properties
            - response_format (ResponseFormat): Output format ('markdown' or 'json')
    
    Returns:
        str: Filtered list of Azure resources matching the search criteria
        
    Example usage:
        - Find all VMs: resource_type='Microsoft.Compute/virtualMachines'
        - Find production resources: tag_filter='environment=production'  
        - Find resources in East US: location='eastus'
        - Find storage accounts: resource_type='Microsoft.Storage/storageAccounts'
    """
    try:
        token = await get_access_token()
        
        # Build KQL query from search parameters
        kql_query = build_search_query(params)
        
        # Build request payload
        request_data = {
            "query": kql_query
        }
        
        if params.subscriptions:
            request_data["subscriptions"] = params.subscriptions
        
        # Make API request
        endpoint = f"/providers/Microsoft.ResourceGraph/resources"
        response = await make_api_request(
            method="POST",
            endpoint=endpoint,
            token=token,
            data=request_data,
            params={"api-version": DEFAULT_API_VERSION}
        )
        
        # Add search criteria to response
        if params.response_format == ResponseFormat.MARKDOWN:
            search_info = ["# Azure Resource Search Results\n"]
            search_info.append("## Search Criteria")
            
            if params.resource_type:
                search_info.append(f"**Resource Type:** {params.resource_type}")
            if params.location:
                search_info.append(f"**Location:** {params.location}")
            if params.resource_group:
                search_info.append(f"**Resource Group:** {params.resource_group}")
            if params.name_filter:
                search_info.append(f"**Name Contains:** {params.name_filter}")
            if params.tag_filter:
                search_info.append(f"**Tag Filter:** {params.tag_filter}")
            if params.subscriptions:
                search_info.append(f"**Subscriptions:** {', '.join(params.subscriptions[:3])}{'...' if len(params.subscriptions) > 3 else ''}")
                
            search_info.append(f"**Generated Query:** `{kql_query}`\n")
            
            formatted_response = format_response(response, params.response_format, "Search Results")
            return "\n".join(search_info) + "\n" + formatted_response
        else:
            # Add search metadata to JSON response
            response["search_criteria"] = {
                "resource_type": params.resource_type,
                "location": params.location,
                "resource_group": params.resource_group,
                "name_filter": params.name_filter,
                "tag_filter": params.tag_filter,
                "subscriptions": params.subscriptions,
                "generated_query": kql_query
            }
            return format_response(response, params.response_format)
        
    except Exception as e:
        error_msg = f"Failed to search Azure resources: {str(e)}"
        logger.error(error_msg)
        return f"❌ **Error:** {error_msg}\n\n💡 **Tips:**\n- Check your search criteria\n- Ensure you have access to the specified subscriptions\n- Try broadening your search filters"


# Main execution
if __name__ == "__main__":
    # Run with stdio transport for desktop integration
    mcp.run()

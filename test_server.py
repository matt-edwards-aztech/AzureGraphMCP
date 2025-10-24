#!/usr/bin/env python3
"""
Azure Resource Graph MCP Server Test Script

This script tests the Azure Resource Graph MCP server setup by:
1. Verifying authentication
2. Testing basic API connectivity
3. Running sample queries
4. Validating tool functionality

Run this script to ensure your setup is working correctly before integrating
with Claude Desktop or other MCP clients.
"""

import asyncio
import json
import os
import sys
from typing import Dict, Any

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from azure_resource_graph_mcp import (
        get_access_token,
        make_api_request,
        azure_resource_graph_query,
        azure_resource_graph_search_resources,
        azure_resource_graph_operations,
        ResourceGraphQueryInput,
        ResourceSearchInput,
        ResponseFormat
    )
except ImportError as e:
    print(f"❌ Error importing MCP server modules: {e}")
    print("Make sure azure_resource_graph_mcp.py is in the same directory as this test script.")
    sys.exit(1)

class TestRunner:
    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.token = None

    async def run_all_tests(self):
        """Run all tests and report results."""
        print("🧪 Azure Resource Graph MCP Server Test Suite")
        print("=" * 50)
        
        # Test 1: Authentication
        await self.test_authentication()
        
        # Test 2: Basic API connectivity
        await self.test_api_connectivity()
        
        # Test 3: Simple resource query
        await self.test_simple_query()
        
        # Test 4: Resource search functionality
        await self.test_resource_search()
        
        # Test 5: Operations listing
        await self.test_operations_list()
        
        # Test 6: Error handling
        await self.test_error_handling()
        
        # Report final results
        self.print_final_results()

    async def test_authentication(self):
        """Test Azure authentication."""
        print("\n🔐 Test 1: Authentication")
        try:
            self.token = await get_access_token()
            if self.token and len(self.token) > 0:
                print("✅ Authentication successful")
                print(f"   Token received (length: {len(self.token)})")
                self.tests_passed += 1
            else:
                print("❌ Authentication failed - empty token")
                self.tests_failed += 1
        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            print("💡 Tips:")
            print("   - Run 'az login' if using Azure CLI authentication")
            print("   - Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID for service principal")
            print("   - Ensure you have proper Azure permissions")
            self.tests_failed += 1

    async def test_api_connectivity(self):
        """Test basic API connectivity."""
        print("\n🌐 Test 2: API Connectivity")
        if not self.token:
            print("❌ Skipping - no authentication token")
            self.tests_failed += 1
            return
            
        try:
            response = await make_api_request(
                method="GET",
                endpoint="/providers/Microsoft.ResourceGraph/operations",
                token=self.token,
                params={"api-version": "2022-10-01"}
            )
            
            if "value" in response:
                print("✅ API connectivity successful")
                print(f"   Retrieved {len(response['value'])} operations")
                self.tests_passed += 1
            else:
                print("❌ API connectivity failed - unexpected response format")
                self.tests_failed += 1
                
        except Exception as e:
            print(f"❌ API connectivity failed: {e}")
            print("💡 Tips:")
            print("   - Check your network connectivity")
            print("   - Verify Azure permissions")
            print("   - Ensure Resource Graph is available in your tenant")
            self.tests_failed += 1

    async def test_simple_query(self):
        """Test a simple resource query."""
        print("\n📊 Test 3: Simple Resource Query")
        try:
            query_input = ResourceGraphQueryInput(
                query="Resources | limit 5",
                response_format=ResponseFormat.JSON
            )
            
            result = await azure_resource_graph_query(query_input)
            
            # Parse the JSON result
            parsed_result = json.loads(result)
            
            if "data" in parsed_result:
                print("✅ Simple query successful")
                print(f"   Retrieved {len(parsed_result.get('data', []))} resources")
                if parsed_result.get("data"):
                    sample_resource = parsed_result["data"][0]
                    print(f"   Sample resource: {sample_resource.get('name', 'Unknown')}")
                self.tests_passed += 1
            else:
                print("❌ Simple query failed - no data in response")
                print(f"   Response: {result[:200]}...")
                self.tests_failed += 1
                
        except Exception as e:
            print(f"❌ Simple query failed: {e}")
            print("💡 Tips:")
            print("   - Check if you have any resources in your subscription")
            print("   - Verify subscription access permissions")
            self.tests_failed += 1

    async def test_resource_search(self):
        """Test the simplified resource search functionality."""
        print("\n🔍 Test 4: Resource Search")
        try:
            search_input = ResourceSearchInput(
                limit=3,
                response_format=ResponseFormat.JSON
            )
            
            result = await azure_resource_graph_search_resources(search_input)
            
            # Parse the JSON result
            parsed_result = json.loads(result)
            
            if "data" in parsed_result:
                print("✅ Resource search successful")
                print(f"   Found {len(parsed_result.get('data', []))} resources")
                if "search_criteria" in parsed_result:
                    print(f"   Generated query: {parsed_result['search_criteria'].get('generated_query', 'N/A')}")
                self.tests_passed += 1
            else:
                print("❌ Resource search failed - no data in response")
                self.tests_failed += 1
                
        except Exception as e:
            print(f"❌ Resource search failed: {e}")
            self.tests_failed += 1

    async def test_operations_list(self):
        """Test listing available operations."""
        print("\n📋 Test 5: Operations List")
        try:
            result = await azure_resource_graph_operations(ResponseFormat.JSON)
            
            # Parse the JSON result
            parsed_result = json.loads(result)
            
            if "value" in parsed_result and parsed_result["value"]:
                print("✅ Operations list successful")
                print(f"   Available operations: {len(parsed_result['value'])}")
                
                # Show a few operations
                for i, op in enumerate(parsed_result["value"][:3]):
                    name = op.get("name", "Unknown")
                    description = op.get("display", {}).get("description", "No description")
                    print(f"   {i+1}. {name}: {description}")
                    
                self.tests_passed += 1
            else:
                print("❌ Operations list failed - no operations returned")
                self.tests_failed += 1
                
        except Exception as e:
            print(f"❌ Operations list failed: {e}")
            self.tests_failed += 1

    async def test_error_handling(self):
        """Test error handling with invalid queries."""
        print("\n🚨 Test 6: Error Handling")
        try:
            # Test with invalid KQL query
            query_input = ResourceGraphQueryInput(
                query="INVALID KQL QUERY SYNTAX",
                response_format=ResponseFormat.MARKDOWN
            )
            
            result = await azure_resource_graph_query(query_input)
            
            # Should return an error message
            if "❌" in result or "Error" in result:
                print("✅ Error handling successful")
                print("   Invalid query properly handled with error message")
                self.tests_passed += 1
            else:
                print("❌ Error handling failed - invalid query should return error")
                print(f"   Unexpected result: {result[:200]}...")
                self.tests_failed += 1
                
        except Exception as e:
            print(f"❌ Error handling test failed: {e}")
            self.tests_failed += 1

    def print_final_results(self):
        """Print the final test results."""
        total_tests = self.tests_passed + self.tests_failed
        
        print("\n" + "=" * 50)
        print("📊 Test Results Summary")
        print("=" * 50)
        print(f"Total tests run: {total_tests}")
        print(f"✅ Passed: {self.tests_passed}")
        print(f"❌ Failed: {self.tests_failed}")
        
        if self.tests_failed == 0:
            print("\n🎉 All tests passed! Your Azure Resource Graph MCP server is ready to use.")
            print("\n📝 Next steps:")
            print("1. Add the server to your Claude Desktop configuration")
            print("2. Restart Claude Desktop")
            print("3. Start querying your Azure resources!")
        else:
            success_rate = (self.tests_passed / total_tests) * 100 if total_tests > 0 else 0
            print(f"\n⚠️  {self.tests_failed} test(s) failed (Success rate: {success_rate:.1f}%)")
            print("\n🔧 Please fix the issues above before using the MCP server.")
            
        print("\n📚 For help, see:")
        print("- README.md for setup instructions")
        print("- config-examples.md for configuration examples")

async def main():
    """Main test function."""
    print("Azure Resource Graph MCP Server Test Script")
    print("This script will test your server setup and configuration.\n")
    
    # Check if required files exist
    required_files = ["azure_resource_graph_mcp.py", "requirements.txt"]
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        print(f"❌ Missing required files: {missing_files}")
        print("Make sure you have all the necessary files in the current directory.")
        return
    
    # Check environment variables
    print("🔍 Environment Check:")
    cli_available = os.system("az account show > /dev/null 2>&1") == 0
    sp_vars_set = all([
        os.getenv("AZURE_CLIENT_ID"),
        os.getenv("AZURE_CLIENT_SECRET"), 
        os.getenv("AZURE_TENANT_ID")
    ])
    
    if cli_available:
        print("✅ Azure CLI authentication available")
    elif sp_vars_set:
        print("✅ Service Principal environment variables set")
    else:
        print("❌ No authentication method configured")
        print("Please either:")
        print("1. Run 'az login' to use Azure CLI authentication, or")
        print("2. Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and AZURE_TENANT_ID environment variables")
        return
    
    # Run the tests
    test_runner = TestRunner()
    await test_runner.run_all_tests()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n💥 Unexpected error during testing: {e}")
        sys.exit(1)

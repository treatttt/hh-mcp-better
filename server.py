#!/usr/bin/env python3
"""HeadHunter MCP Server.

This module provides a Model Context Protocol (MCP) server for interacting with
the HeadHunter job search API. The server exposes various tools for searching
vacancies, retrieving detailed job information, managing applications, and
handling user authentication through OAuth.

The module implements the MCP protocol to allow AI assistants to interact with
HeadHunter's API services, including both public API endpoints (for searching
vacancies and employers) and authenticated endpoints (for managing resumes and
applications).

Main components:
    - MCP Server setup with stdio transport
    - Tool definitions for various HeadHunter API operations
    - Request handling and response formatting
    - OAuth authentication support

Tools:
    hh_search_vacancies: Search for job vacancies with various filters
    hh_get_vacancy: Get detailed information about a specific vacancy
    hh_get_employer: Retrieve employer/company information
    hh_get_similar: Find similar vacancies for a given vacancy
    hh_get_areas: Get list of available regions/areas for filtering
    hh_get_dictionaries: Retrieve all filter dictionaries from HeadHunter
    hh_apply_to_vacancy: Submit job applications (requires OAuth)
    hh_get_negotiations: Get user's application history (requires OAuth)
    hh_get_resumes: List user's resumes (requires OAuth)
    hh_get_resume: Get detailed resume information (requires OAuth)
"""

import asyncio
import json
from typing import Any
from dotenv import load_dotenv

from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
import mcp.server.stdio

from applications import ApplicationDisabledError, ApplicationService
from hh_client import HHClient
from output_safety import (
    external_document,
    external_field,
    resume_full,
    resume_summary,
)
from validation import (
    DECIMAL_ID_SCHEMA_PATTERN,
    MAX_AREA_ID,
    MAX_COVER_LETTER_LENGTH,
    MAX_PAGE,
    MAX_PER_PAGE,
    MAX_SALARY,
    MAX_SEARCH_TEXT_LENGTH,
    RESUME_ID_SCHEMA_PATTERN,
    InvalidInputError,
)

load_dotenv()

app = Server("hh-api")
hh_client = HHClient()
application_service = ApplicationService(hh_client)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return the list of available MCP tools for HeadHunter API.

    This function defines all the tools that can be called by MCP clients
    to interact with the HeadHunter API. It includes both public tools
    (for searching vacancies and getting employer information) and
    authenticated tools (for managing applications and resumes).

    The tools are organized into several categories:
    - Vacancy search and retrieval
    - Employer information
    - Similar vacancies
    - Reference data (areas, dictionaries)
    - User operations (applications, resumes) - require OAuth

    Returns:
        list[Tool]: A list of Tool objects defining the available MCP tools,
            each with its name, description, and input schema.
    """
    return [
        Tool(
            name="hh_search_vacancies",
            description="Search for job vacancies on HeadHunter. Returns list of vacancies matching criteria.",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_SEARCH_TEXT_LENGTH,
                        "description": "Search query (job title, keywords, skills)",
                    },
                    "area": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_AREA_ID,
                        "description": "Region ID (1=Moscow, 2=SPb, 113=Russia). Use hh_get_areas to find IDs.",
                    },
                    "experience": {
                        "type": "string",
                        "enum": [
                            "noExperience",
                            "between1And3",
                            "between3And6",
                            "moreThan6",
                        ],
                        "description": "Required experience level",
                    },
                    "employment": {
                        "type": "string",
                        "enum": ["full", "part", "project", "volunteer", "probation"],
                        "description": "Employment type",
                    },
                    "schedule": {
                        "type": "string",
                        "enum": [
                            "fullDay",
                            "shift",
                            "flexible",
                            "remote",
                            "flyInFlyOut",
                        ],
                        "description": "Work schedule",
                    },
                    "salary": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": MAX_SALARY,
                        "description": "Minimum salary",
                    },
                    "only_with_salary": {
                        "type": "boolean",
                        "description": "Show only vacancies with specified salary",
                    },
                    "per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_PER_PAGE,
                        "description": "Results per page (max 100)",
                        "default": 20,
                    },
                    "page": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": MAX_PAGE,
                        "description": "Page number (0-indexed)",
                        "default": 0,
                    },
                },
            },
        ),
        Tool(
            name="hh_get_vacancy",
            description="Get detailed information about specific vacancy by ID",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "vacancy_id": {
                        "type": "string",
                        "pattern": DECIMAL_ID_SCHEMA_PATTERN,
                        "description": "Vacancy ID from search results",
                    }
                },
                "required": ["vacancy_id"],
            },
        ),
        Tool(
            name="hh_get_employer",
            description="Get information about employer/company by ID",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "employer_id": {
                        "type": "string",
                        "pattern": DECIMAL_ID_SCHEMA_PATTERN,
                        "description": "Employer ID from vacancy data",
                    }
                },
                "required": ["employer_id"],
            },
        ),
        Tool(
            name="hh_get_similar",
            description="Get similar vacancies for a specific vacancy",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "vacancy_id": {
                        "type": "string",
                        "pattern": DECIMAL_ID_SCHEMA_PATTERN,
                        "description": "Vacancy ID",
                    }
                },
                "required": ["vacancy_id"],
            },
        ),
        Tool(
            name="hh_get_areas",
            description="Get list of all available regions/areas with IDs for filtering",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        ),
        Tool(
            name="hh_get_dictionaries",
            description="Get all dictionaries (experience, employment, schedule, etc.) for filtering",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        ),
        Tool(
            name="hh_prepare_application",
            description=(
                "Prepare an application preview and one-time confirmation token. "
                "This does not submit the application."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "vacancy_id": {
                        "type": "string",
                        "pattern": DECIMAL_ID_SCHEMA_PATTERN,
                        "description": "Vacancy ID to apply to",
                    },
                    "resume_id": {
                        "type": "string",
                        "pattern": RESUME_ID_SCHEMA_PATTERN,
                        "description": "Resume ID to use for application",
                    },
                    "letter": {
                        "type": "string",
                        "maxLength": MAX_COVER_LETTER_LENGTH,
                        "description": "Cover letter text (optional)",
                    },
                },
                "required": ["vacancy_id", "resume_id"],
            },
        ),
        Tool(
            name="hh_confirm_application",
            description=(
                "Submit exactly the previously previewed application using its "
                "one-time confirmation token."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "confirmation_token": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "One-time token from hh_prepare_application",
                    }
                },
                "required": ["confirmation_token"],
            },
        ),
        Tool(
            name="hh_get_negotiations",
            description="Get user's application history and status (requires OAuth). Supports pagination.",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_PER_PAGE,
                        "description": "Results per page (max 100)",
                        "default": 20,
                    },
                    "page": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": MAX_PAGE,
                        "description": "Page number (0-indexed)",
                        "default": 0,
                    },
                },
            },
        ),
        Tool(
            name="hh_get_resumes",
            description="Get list of user's resumes (requires OAuth)",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        ),
        Tool(
            name="hh_get_resume",
            description=(
                "Get a minimized resume view without names or contact information "
                "(requires OAuth)"
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "resume_id": {
                        "type": "string",
                        "pattern": RESUME_ID_SCHEMA_PATTERN,
                        "description": "Resume ID",
                    }
                },
                "required": ["resume_id"],
            },
        ),
        Tool(
            name="hh_get_resume_full",
            description=(
                "Explicitly get bounded personal and contact data for a resume. "
                "Use only when the user asks for the full resume (requires OAuth)."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "resume_id": {
                        "type": "string",
                        "pattern": RESUME_ID_SCHEMA_PATTERN,
                        "description": "Resume ID",
                    }
                },
                "required": ["resume_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str, arguments: Any
) -> list[TextContent | ImageContent | EmbeddedResource]:
    """Execute a HeadHunter API tool call.

    This function serves as the main dispatcher for all HeadHunter MCP tool
    calls. It handles the execution of various tools including vacancy search,
    detailed information retrieval, application management, and resume
    operations. The function processes the tool arguments, makes the
    appropriate API calls through the HHClient, and formats the responses
    for the MCP client.

    The function handles both public API calls (no authentication required)
    and authenticated calls (OAuth token required). For authenticated calls,
    appropriate error handling is provided when tokens are missing or invalid.

    Args:
        name (str): The name of the tool to execute. Must be one of the
            supported tool names defined in list_tools().
        arguments (Any): The arguments for the tool call. The structure
            depends on the specific tool being called and matches the
            inputSchema defined for that tool.

    Returns:
        list[TextContent | ImageContent | EmbeddedResource]: A list containing
            the formatted response from the HeadHunter API. Typically contains
            a single TextContent object with the formatted result data.

    Raises:
        Exception: Various exceptions may be raised during API calls,
            authentication issues, or data processing errors. All exceptions
            are caught and returned as error messages to the MCP client.
    """
    try:
        if name == "hh_search_vacancies":
            result = await hh_client.search_vacancies(**arguments)

            items = result.get("items", [])
            summary = f"Found {result.get('found', 0)} vacancies (showing {len(items)})"

            formatted_items = []
            for item in items[:10]:
                salary_info = "Not specified"
                if item.get("salary"):
                    sal = item["salary"]
                    from_sal = sal.get("from", "")
                    to_sal = sal.get("to", "")
                    currency = sal.get("currency", "")
                    if from_sal and to_sal:
                        salary_info = f"{from_sal}-{to_sal} {currency}"
                    elif from_sal:
                        salary_info = f"from {from_sal} {currency}"
                    elif to_sal:
                        salary_info = f"up to {to_sal} {currency}"

                formatted_items.append(
                    f"[{item['id']}] {external_field(item['name'])}\n"
                    f"  Company: {external_field(item.get('employer', {}).get('name', 'N/A'))}\n"
                    f"  Salary: {salary_info}\n"
                    f"  Area: {item.get('area', {}).get('name', 'N/A')}\n"
                    f"  URL: {item.get('alternate_url', 'N/A')}\n"
                )

            return [
                TextContent(
                    type="text", text=f"{summary}\n\n" + "\n".join(formatted_items)
                )
            ]

        elif name == "hh_get_vacancy":
            result = await hh_client.get_vacancy(arguments["vacancy_id"])

            salary_info = "Not specified"
            if result.get("salary"):
                sal = result["salary"]
                from_sal = sal.get("from", "")
                to_sal = sal.get("to", "")
                currency = sal.get("currency", "")
                if from_sal and to_sal:
                    salary_info = f"{from_sal}-{to_sal} {currency}"
                elif from_sal:
                    salary_info = f"from {from_sal} {currency}"
                elif to_sal:
                    salary_info = f"up to {to_sal} {currency}"

            formatted = f"""
Vacancy: {result.get('name')}
Company: {result.get('employer', {}).get('name', 'N/A')}
Salary: {salary_info}
Area: {result.get('area', {}).get('name', 'N/A')}
Experience: {result.get('experience', {}).get('name', 'N/A')}
Employment: {result.get('employment', {}).get('name', 'N/A')}
Schedule: {result.get('schedule', {}).get('name', 'N/A')}

Description:
{external_document(result.get('description', 'No description'))}

Key Skills:
{', '.join([s.get('name', '') for s in result.get('key_skills', [])])}

URL: {result.get('alternate_url', 'N/A')}
"""

            return [TextContent(type="text", text=formatted)]

        elif name == "hh_get_employer":
            result = await hh_client.get_employer(arguments["employer_id"])
            safe_result = {
                "id": result.get("id"),
                "name": external_field(result.get("name")),
                "description": external_document(result.get("description")),
                "site_url": result.get("site_url"),
                "alternate_url": result.get("alternate_url"),
                "area": result.get("area"),
                "industries": result.get("industries", [])[:50],
            }
            return [
                TextContent(
                    type="text",
                    text=json.dumps(safe_result, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "hh_get_similar":
            result = await hh_client.get_similar_vacancies(arguments["vacancy_id"])
            items = result.get("items", [])

            formatted_items = []
            for item in items:
                formatted_items.append(
                    f"[{item['id']}] {external_field(item['name'])} - "
                    f"{external_field(item.get('employer', {}).get('name', 'N/A'))}"
                )

            return [
                TextContent(
                    type="text",
                    text="\n".join(formatted_items)
                    if formatted_items
                    else "No similar vacancies found",
                )
            ]

        elif name == "hh_get_areas":
            result = await hh_client.get_areas()
            return [
                TextContent(
                    type="text", text=json.dumps(result, indent=2, ensure_ascii=False)
                )
            ]

        elif name == "hh_get_dictionaries":
            result = await hh_client.get_dictionaries()
            return [
                TextContent(
                    type="text", text=json.dumps(result, indent=2, ensure_ascii=False)
                )
            ]

        elif name == "hh_prepare_application":
            result = await application_service.prepare(**arguments)
            return [
                TextContent(
                    type="text",
                    text=(
                        "Application preview created. Review every field, then use "
                        "hh_confirm_application with the one-time token.\n"
                        + json.dumps(result, indent=2, ensure_ascii=False)
                    ),
                )
            ]

        elif name == "hh_confirm_application":
            result = await application_service.confirm(arguments["confirmation_token"])
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "hh_get_negotiations":
            per_page = arguments.get("per_page", 20)
            page = arguments.get("page", 0)
            result = await hh_client.get_negotiations(per_page=per_page, page=page)

            items = result.get("items", [])
            total = result.get("found", 0)
            summary = f"Total applications: {total} (showing page {page}, {len(items)} items)\n\n"

            formatted_items = []
            for item in items:
                vacancy = item.get("vacancy", {})
                state = item.get("state", {}).get("name", "Unknown")
                created = item.get("created_at", "N/A")

                formatted_items.append(
                    f"[{vacancy.get('id', 'N/A')}] {vacancy.get('name', 'N/A')}\n"
                    f"  Company: {vacancy.get('employer', {}).get('name', 'N/A')}\n"
                    f"  Status: {state}\n"
                    f"  Applied: {created}\n"
                )

            return [TextContent(type="text", text=summary + "\n".join(formatted_items))]

        elif name == "hh_get_resumes":
            result = await hh_client.get_resumes()
            items = result.get("items", [])

            formatted_items = []
            for item in items:
                status = (
                    "✅ Published"
                    if item.get("status", {}).get("id") == "published"
                    else "⏸️ Not published"
                )
                formatted_items.append(
                    f"[{item['id']}] {item.get('title', 'No title')}\n"
                    f"  Status: {status}\n"
                    f"  Updated: {item.get('updated_at', 'N/A')}\n"
                    f"  Views: {item.get('views_count', 0)}\n"
                )

            return [
                TextContent(
                    type="text",
                    text=f"Your resumes ({len(items)}):\n\n"
                    + "\n".join(formatted_items),
                )
            ]

        elif name == "hh_get_resume":
            result = await hh_client.get_resume(arguments["resume_id"])
            return [
                TextContent(
                    type="text",
                    text=json.dumps(resume_summary(result), indent=2, ensure_ascii=False),
                )
            ]

        elif name == "hh_get_resume_full":
            result = await hh_client.get_resume(arguments["resume_id"])
            return [
                TextContent(
                    type="text",
                    text=json.dumps(resume_full(result), indent=2, ensure_ascii=False),
                )
            ]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except InvalidInputError as e:
        return [TextContent(type="text", text=f"Invalid input: {e}")]
    except ApplicationDisabledError as e:
        return [TextContent(type="text", text=f"Application disabled: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Initialize and run the HeadHunter MCP server.

    This function serves as the entry point for the HeadHunter MCP server.
    It sets up the standard input/output (stdio) transport for communication
    with MCP clients and starts the server with the necessary initialization
    options.

    The server runs indefinitely, handling incoming MCP requests until
    terminated. The stdio transport allows the server to communicate with
    MCP clients through standard input and output streams, making it suitable
    for use with AI assistants and other MCP-compatible applications.
    """
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

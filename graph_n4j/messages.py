"""Short CLI diagnostics. Full driver and provider errors are available with --verbose."""

import errno
import re

import httpx
from git.exc import GitCommandError
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable


def explain_error(exc: Exception, command: str) -> str:
    if isinstance(exc, AuthError):
        return "Neo4j rejected the login. Check NEO4J_USER and NEO4J_PASSWORD."
    if isinstance(exc, ServiceUnavailable):
        return "Cannot reach Neo4j. Start the database and check its Bolt address in NEO4J_URI."
    if isinstance(exc, Neo4jError):
        if command == "cypher":
            return (
                "Neo4j could not run the query. Check the Cypher syntax and database permissions."
            )
    if isinstance(exc, FileNotFoundError):
        return "Could not find the requested file or folder. Check the path and try again."
    if isinstance(exc, PermissionError):
        return "Access denied. Check read and write permissions for the project and cache folders."
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "Storage is full. Free space on the affected drive and run the command again."
    if isinstance(exc, GitCommandError):
        return "Git could not read the repository. Check the URL, revision and repository access."
    if command == "ask":
        key = re.search(r"\b[A-Z]+_API_KEY\b", str(exc)) if isinstance(exc, ValueError) else None
        if key:
            return f"Provider credentials are missing. Set {key.group()} and retry your question."
        status = getattr(exc, "status_code", None)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
        if status in (401, 403):
            return "The provider rejected the request. Check the API key and model permissions."
        if status == 429:
            return "The provider reached its request limit. Check your quota or try again later."
        if isinstance(exc, httpx.RequestError):
            return (
                "Cannot reach the model server. Check its address and that the service is running."
            )
    return f"Could not finish '{command}'. Run graph-n4j --verbose {command} with the same arguments for details."

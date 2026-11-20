"""Short CLI diagnostics. Full driver and provider errors are available with --verbose."""

import errno
import logging
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
        if command == "clear" and "MemoryPoolOutOfMemoryError" in (exc.code or ""):
            return (
                "Neo4j ran out of transaction memory during deletion. "
                "Earlier batches may have finished. Wait for other database writes "
                "to finish, then repeat the same clear command."
            )
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
        if status == 404:
            return "The model or endpoint was not found. Check the provider URL and select an available model with --model before ask."
        if status in (400, 413, 422):
            return f"The provider rejected the model request (HTTP {status}). Check the model name and context limit, or run with --verbose for the provider's reason."
        if isinstance(status, int) and status >= 500:
            return f"The provider returned a server error (HTTP {status}). Retry your question later."
        if status == 429:
            return "The provider reached its request limit. Check your quota or try again later."
        if isinstance(exc, httpx.RequestError):
            return (
                "Cannot reach the model server. Check its address and that the service is running."
            )
    return f"Could not finish '{command}'. Run graph-n4j --verbose {command} with the same arguments for details."

class DiagnosticFormatter(logging.Formatter):
    """Keep server objects, query text and tracebacks in verbose output."""

    def __init__(self, command: str):
        super().__init__()
        self.command = command

    def format(self, record: logging.LogRecord) -> str:
        level = "Error" if record.levelno >= logging.ERROR else "Warning"
        detail = record.getMessage()
        hint = f"Run graph-n4j --verbose {self.command} with the same arguments for details."
        if record.name.startswith("neo4j"):
            if "MemoryPoolOutOfMemoryError" in detail:
                message = "Neo4j reached its transaction memory limit."
                hint = "Wait for other writes to finish, then retry the command."
            elif record.name == "neo4j.notifications":
                if "DEPRECATION" in detail or "deprecated" in detail.lower():
                    message = "Neo4j accepted a query that uses older syntax."
                    hint = "If you wrote the query, update its syntax before upgrading Neo4j."
                elif "property key does not exist" in detail.lower():
                    message = "The query references a property missing from this database."
                    hint = "Check the property name and confirm the repository has been indexed."
                else:
                    message = "Neo4j issued a query advisory."
            else:
                message = "Neo4j reported a database issue."
        else:
            # Avoid printing serialized exceptions or multi-line payloads from libraries.
            message = detail.splitlines()[0] if detail else record.name
            if len(message) > 180:
                message = message[:177] + "..."
        return f"{level}: {message}\nHint: {hint}"

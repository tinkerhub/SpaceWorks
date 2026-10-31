"""Conservative shell lexer with explicit facts for unsupported shell grammar.

This is not a Bash interpreter. Every executable unit carries a whole-context
review fact; command, expansion, literal sh-c and heredoc vectors remain visible
to reviewers rather than being accepted under a command-name allowlist.
"""
import re
import shlex
from pathlib import PurePosixPath

from .embedded_scan import digest, scan_embedded


def scan_shell(text, owner="<shell>", first_line=1, embedded=None):
    result = {"sites": [], "calls": [], "symbols": {owner: digest(text)}, "dependencies": []}
    aliases = {}

    def emit(line, category, shape, facts=()):
        result["sites"].append({"owner": owner, "line": line, "column": 0,
            "category": category, "shape": digest(shape), "unresolved": list(facts)})

    def merge(data):
        for key in ("sites", "calls", "dependencies"):
            result[key].extend(data[key])
        result["symbols"].update(data["symbols"])

    def payload(language, body, line, label):
        nested_owner = f"{owner}.{label}@{line}"
        if embedded and language == "javascript":
            merge(embedded(body, nested_owner, line))
        elif language == "shell":
            merge(scan_shell(body, nested_owner, line, embedded))
        else:
            merge(scan_embedded(language, body, nested_owner, line))

    def command(tokens, line):
        if not tokens:
            return
        while tokens and tokens[0] in {"if", "then", "elif", "else", "do", "while", "until", "!", "{"}:
            tokens = tokens[1:]
        while tokens and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", tokens[0]):
            tokens = tokens[1:]
        while tokens and tokens[0] in {"env", "exec", "command", "sudo"}:
            tokens = tokens[1:]
        if not tokens:
            return
        raw = tokens[0]
        executable = PurePosixPath(raw).name
        target = aliases.get(executable, executable)
        result["calls"].append({"owner": owner, "target": target, "line": line, "column": 0})
        if "$" in raw or "`" in raw:
            emit(line, "unresolved_dynamic", repr(tokens), ("dynamic_shell_callee",))
        if executable == "alias":
            for token in tokens[1:]:
                if "=" in token:
                    name, value = token.split("=", 1)
                    aliases[name] = "<shell-alias:" + digest(value) + ">"
            emit(line, "unresolved_dynamic", repr(tokens), ("shell_alias_definition",))
        if executable in {"psql", "pg_restore", "pg_dump", "mysql", "sqlite3"}:
            emit(line, "shell_psql", repr(tokens))
            for flag in ("-c", "--command", "-e", "--execute"):
                if flag in tokens and tokens.index(flag) + 1 < len(tokens):
                    payload("sql", tokens[tokens.index(flag) + 1], line, "sql-argument")
            for token in tokens[1:]:
                if token.startswith(("--command=", "--execute=")):
                    payload("sql", token.split("=", 1)[1], line, "sql-argument")
        if executable in {"aws", "mc", "s3cmd", "rclone"}:
            emit(line, "object_storage", repr(tokens))
        if executable in {"bash", "sh", "dash", "zsh", "python", "python3", "node"}:
            language = "shell" if executable in {"bash", "sh", "dash", "zsh"} else (
                "javascript" if executable == "node" else "python")
            flag = "-e" if executable == "node" else "-c"
            if flag in tokens:
                at = tokens.index(flag) + 1
                if at < len(tokens):
                    payload(language, tokens[at], line, "inline")
                    if re.search(r"[$`]", tokens[at]):
                        emit(line, "unresolved_dynamic", repr(tokens), ("shell_expanded_inline_program",))
                else:
                    emit(line, "unresolved_dynamic", repr(tokens), ("missing_inline_program",))
        if executable in {"eval", "source", "."}:
            emit(line, "unresolved_dynamic", repr(tokens), ("shell_dynamic_evaluation",))

    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = first_line + index
        logical = lines[index]
        index += 1
        while logical.rstrip().endswith("\\") and index < len(lines):
            logical = logical.rstrip()[:-1] + lines[index]
            index += 1
        if not logical.strip() or logical.lstrip().startswith("#"):
            continue
        for expansion in re.finditer(r"\$(?:\{[^}]*\}|[A-Za-z_][A-Za-z_0-9]*|\([^)]*\))|`[^`]*`", logical):
            emit(line, "env_expansion", expansion.group())
        if re.search(r"\$\(|`|\b(?:if|then|else|fi|for|while|case|function|select|coproc)\b|[()]", logical):
            emit(line, "unresolved_dynamic", logical, ("shell_compound_or_substitution_grammar",))
        try:
            lexer = shlex.shlex(logical, posix=True, punctuation_chars=";&|()")
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
        except ValueError:
            emit(line, "unresolved_dynamic", logical, ("shell_lex_error",))
            continue
        group = []
        for token in tokens + [";"]:
            if token and set(token) <= set(";&|()"):
                command(group, line)
                group = []
            else:
                group.append(token)
        heredocs = list(re.finditer(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\2", logical))
        if "<<" in logical and not heredocs:
            emit(line, "unresolved_dynamic", logical, ("dynamic_heredoc_delimiter",))
        for match in heredocs:
            body, start = [], first_line + index
            while index < len(lines):
                current = lines[index]
                index += 1
                candidate = current.lstrip("\t") if match.group(1) else current
                if candidate.rstrip("\r\n") == match.group(3):
                    break
                body.append(candidate)
            else:
                emit(line, "unresolved_dynamic", logical, ("unterminated_heredoc",))
            language = "unknown"
            if re.search(r"\b(?:python|python3)\b", logical):
                language = "python"
            elif re.search(r"\bnode\b", logical):
                language = "javascript"
            elif re.search(r"\b(?:psql|sqlite3|mysql)\b", logical):
                language = "sql"
            elif re.search(r"\b(?:bash|sh|dash|zsh)\b", logical):
                language = "shell"
            else:
                for extension, value in (("py", "python"), ("m?js", "javascript"), ("sh", "shell"), ("sql", "sql")):
                    if re.search(r"\." + extension + r"(?:[\s'\"]|$)", logical):
                        language = value
                        break
            payload(language, "".join(body), start, "heredoc")
            if not match.group(2):
                emit(line, "unresolved_dynamic", "".join(body), ("shell_expanded_heredoc",))
    emit(first_line, "unresolved_dynamic", text, ("shell_whole_context_review_required",))
    result["dependencies"] = sorted(set(result["dependencies"]))
    return result

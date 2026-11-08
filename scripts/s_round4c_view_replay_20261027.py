#!/usr/bin/env python3
"""Pure forwarding replay request conversion, without changing the J engine."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import re

import s_tag_wrapper_prototype_20261027 as parser
import s_round4c_postdeadline_20261027 as post


def forward(source, template, arguments, sources):
    definitions = [d for d in parser.definitions(sources[source]) if d["name"] == template]
    post.require(len(definitions) == 1, "unique target definition required")
    definition = definitions[0]
    ports, variables = parser.inspect_ports(definition)
    if any(p["tags"] for p in ports if p["direction"] == "input"):
        text, tags, info = parser.render_prototype(source, sources[source], template, arguments, sources)
        post.require(text is not None, info.get("generation_refusal", "tag wrapper refused"))
        return text, ports, tags
    post.require(len(arguments) == len(definition["parameters"]), "argument arity differs")
    bridge = "__S_ReplayForward"
    identifiers = {t.text for text in sources.values() for t in parser.tokenize(text)}
    post.require(bridge not in identifiers and "__s_tag_target" not in identifiers, "generated name collision")
    lines = ['pragma circom 2.1.6;', '', 'include ' + json.dumps(str(source)) + ';', '',
             f'template {bridge}({", ".join(definition["parameters"])}) {{',
             *parser.dimension_declarations(definition, ports, variables, sources)]
    for port in ports:
        dimensions = ''.join('[' + parser.text_of(d) + ']' for d in port['dimensions'])
        lines.append(f'    signal {port["direction"]} {port["name"]}{dimensions};')
    lines.append(f'    component __s_tag_target = {template}({", ".join(definition["parameters"])});')
    for direction in ("input", "output"):
        for i, port in enumerate(ports):
            if port["direction"] != direction:
                continue
            def wire(level, indices):
                indent = '    ' * (level + 1)
                if level == len(port["dimensions"]):
                    name = port["name"] + ''.join('[' + n + ']' for n in indices)
                    left, right = ("__s_tag_target." + name, name) if direction == "input" else (name, "__s_tag_target." + name)
                    lines.append(f'{indent}{left} <== {right};')
                else:
                    index = f'__s_tag_{"i" if direction == "input" else "o"}_{i}_{level}'
                    post.require(index not in identifiers, "generated loop name collision")
                    lines.append(f'{indent}for (var {index} = 0; {index} < {parser.text_of(port["dimensions"][level])}; {index}++) {{')
                    wire(level + 1, indices + [index])
                    lines.append(indent + '}')
            wire(0, [])
    lines += ['}', '', f'component main = {bridge}({", ".join(arguments)});', '']
    return '\n'.join(lines), ports, []


def assignment(value, fmt, ports):
    source = value if fmt == "named" else value["7_assignment"] if fmt == "zkfuzz" else None
    post.require(isinstance(source, dict), "unsupported candidate assignment")
    result = {}
    inputs = {p["name"]: p for p in ports}
    for name, value in source.items():
        post.require(name.startswith("main.") and isinstance(value, (str, int)) and
                     not isinstance(value, bool) and re.fullmatch(r"[0-9]+", str(value)), "noncanonical candidate")
        result["main.__s_tag_target." + name[5:]] = str(value)
        head = re.split(r"[.\[]", name[5:], maxsplit=1)[0]
        if head in inputs and "." not in name[5:]:
            result[name] = str(value)
            port = inputs[head]
            if port["direction"] == "input" and port["tags"]:
                i = ports.index(port)
                result["main.__s_tag_input_" + str(i) + name[5 + len(head):]] = str(value)
    return result


def convert(row, folder):
    """Source closure pins are supplied by preparation, never discovered recursively."""
    folder = post.checked_output(folder)
    folder.mkdir(parents=True, exist_ok=False)
    _, request = post.read_pin(row["request"])
    post.require(request["schema"] == "zkfdo-lifting-request-v1" and "component_view" not in request,
                 "only legacy replay requests can be converted")
    # Resolve the one include exactly as in the recorded preparation wrapper.
    source, template, arguments = parser.original_call(Path(request["source_root"]).joinpath(request["component_wrapper"]).read_text())
    sources = {}
    original_root = Path(request["source_root"]).resolve()
    relocated = {}
    for item in row["source_closure"]:
        path = post.checked_input(item["path"])
        post.require(post.sha(path) == item["sha256"], "source closure changed")
        post.require(path.is_relative_to(original_root), "source outside declared root requires an explicit relocation plan")
        text = path.read_text()
        post.require(not re.search(r'include\s+"/', text), "absolute include requires a separately verified relocation")
        target = folder / "source" / path.relative_to(original_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        relocated[path] = target
        sources[target] = text
    post.require(source in relocated, "target definition missing from pinned closure")
    source = relocated[source]
    post.require(source in sources, "target definition missing from pinned closure")
    text, ports, tags = forward(source, template, arguments, sources)
    wrapper = folder / "forward.circom"
    wrapper.write_text(text)
    original = post.write_new(folder / "original-fragment.json", {
        "original_request": row["request"], "template": template, "arguments": arguments,
        "source_closure": row["source_closure"]})
    candidate_path = Path(request["source_root"]) / request["candidate"]["path"]
    post.require(post.sha(candidate_path) == row["candidate"]["sha256"], "candidate SHA differs")
    candidate = post.write_new(folder / "candidate.json", assignment(json.loads(candidate_path.read_text()),
                                request["candidate"]["format"], ports))
    view = post.write_new(folder / "view.json", {"schema": "zkfdo-component-view-v1",
        "target_prefix": "main.__s_tag_target", "target_template": template,
        "target_source": str(source), "target_source_sha256": post.sha(source),
        "wrapper_sha256": post.sha(wrapper), "original_fragment_spec": original["path"],
        "original_fragment_spec_sha256": original["sha256"], "concrete_arguments": arguments,
        "attached_without_enforcement": [{"input": t["input"], "tag": tag["name"], "value": tag["value"]}
                                          for t in tags for tag in t["tags"]]})
    converted = copy.deepcopy(request)
    original_entry = original_root / request["entrypoint"]
    post.require(original_entry in relocated, "entrypoint missing from explicit source closure")
    base = folder / "base-input.json"
    base.write_bytes((original_root / request["base_input"]).read_bytes())
    converted.update(schema="zkfdo-lifting-request-v2.3", component_wrapper=str(wrapper),
                     source_root=str(folder), entrypoint=str(relocated[original_entry]), base_input=str(base),
                     candidate={"format": "named", "path": candidate["path"]},
                     component_view={"spec": view["path"], "sha256": view["sha256"]})
    return {"request": post.write_new(folder / "request.json", converted),
            "original_request_sha256": row["request"]["sha256"], "candidate": candidate,
            "wrapper": {"path": str(wrapper), "sha256": post.sha(wrapper)}, "view": view,
            "inputs": [{"path": str(p), "sha256": post.sha(p)} for p in
                       [wrapper, base, *sources, Path(candidate["path"])]],
            "compiled_or_judged": False}
